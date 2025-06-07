"""
Celery tasks for asynchronous operations.

This module defines Celery tasks, primarily for handling long-running processes
like downloading tweets and saving them to Google Drive, without blocking the
main web application.

Tasks defined here are registered with the Celery application instance created
in `celery_app_setup.py`. They rely on helper functions to reconstruct API clients
(Twitter, Google Drive) using OAuth tokens passed from the web application context.
"""
from .celery_app_setup import celery_app # Relative import for Celery app instance
from core_logic import twitter_client, drive_client, config, utils
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest # For token refresh
from googleapiclient.discovery import build
import tweepy # For Twitter client reconstruction
import logging
import os # Though not directly used in this version of tasks.py, often useful
import io # For handling byte streams (e.g., for file uploads)
import json # For serializing data to JSON
from datetime import datetime, timezone # For consistent datetime handling

# Configure a logger specific to tasks for better clarity in logs
task_logger = logging.getLogger(__name__)
# Basic logging config if this module is somehow run in a context where no handlers are set
if not task_logger.handlers: # Avoid adding handlers multiple times if Celery sets them up
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')


def get_drive_service_for_task(google_token_dict):
    """
    Reconstructs and returns a Google Drive API service client for use in Celery tasks.

    Uses a Google OAuth token dictionary (typically retrieved from Flask session and
    passed to the task) and client credentials from `core_logic.config`.
    Handles token refresh if a refresh token is available and the access token is expired.

    Args:
        google_token_dict (dict): The Google OAuth token dictionary. Expected to contain
                                  'access_token', and optionally 'refresh_token', 'scope'.
    Returns:
        googleapiclient.discovery.Resource or None: Initialized Google Drive service, or None on failure.
    """
    if not google_token_dict or 'access_token' not in google_token_dict:
        task_logger.error("Celery Task: Invalid or missing Google token for get_drive_service_for_task.")
        return None
    try:
        credentials = Credentials(
            token=google_token_dict['access_token'],
            refresh_token=google_token_dict.get('refresh_token'),
            token_uri='https://oauth2.googleapis.com/token',
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            scopes=google_token_dict.get('scope', ['https://www.googleapis.com/auth/drive.file']) # Default scope
        )
        if credentials.expired and credentials.refresh_token:
            task_logger.info("Celery Task: Google token expired, attempting refresh.")
            try:
                credentials.refresh(GoogleAuthRequest()) # google-auth library handles the refresh request
                task_logger.info("Celery Task: Google token refreshed successfully.")
            except Exception as refresh_err:
                task_logger.error(f"Celery Task: Failed to refresh Google token: {refresh_err}", exc_info=True)
                return None # Critical if refresh fails
        service = build('drive', 'v3', credentials=credentials, static_discovery=False)
        task_logger.info("Celery Task: Google Drive service client built successfully.")
        return service
    except Exception as e:
        task_logger.error(f"Celery Task: Failed to build Google Drive service: {e}", exc_info=True)
        return None

def get_twitter_client_for_task(twitter_token_dict):
    """
    Reconstructs and returns a Tweepy API client for use in Celery tasks.

    Uses a Twitter OAuth token dictionary (typically from Flask session, passed to task)
    and consumer keys from `core_logic.config`. Assumes OAuth 1.0a tokens by default,
    as commonly provided by Flask-Dance's default Twitter blueprint.
    The client is configured with `wait_on_rate_limit=True`.

    Args:
        twitter_token_dict (dict): The Twitter OAuth token dictionary. Expected for OAuth 1.0a:
                                   {'oauth_token': '...', 'oauth_token_secret': '...'}.
    Returns:
        tweepy.Client or None: Initialized Tweepy client, or None on failure.
    """
    if not twitter_token_dict:
        task_logger.error("Celery Task: Invalid or missing Twitter token for get_twitter_client_for_task.")
        return None
    if 'oauth_token' in twitter_token_dict and 'oauth_token_secret' in twitter_token_dict: # OAuth 1.0a
        task_logger.info("Celery Task: Initializing Tweepy client with OAuth 1.0a token.")
        try:
            client = tweepy.Client(
                consumer_key=config.TWITTER_CLIENT_ID,
                consumer_secret=config.TWITTER_CLIENT_SECRET,
                access_token=twitter_token_dict['oauth_token'],
                access_token_secret=twitter_token_dict['oauth_token_secret'],
                wait_on_rate_limit=True # Important for background tasks to handle rate limits gracefully
            )
            # Optional: A light test call like client.get_me() could verify token validity immediately.
            # test_auth = client.get_me()
            # if not (test_auth and test_auth.data):
            #     task_logger.error("Celery Task: Twitter client test (get_me) failed. Token might be invalid.")
            #     return None
            task_logger.info("Celery Task: Tweepy client (OAuth 1.0a) initialized successfully.")
            return client
        except Exception as e:
            task_logger.error(f"Celery Task: Failed to create Tweepy client (OAuth 1.0a): {e}", exc_info=True)
            return None
    # Add elif for OAuth 2.0 user context bearer token if Flask-Dance is ever configured for that
    else:
        task_logger.error(f"Celery Task: Twitter token format not recognized for client creation. Keys: {list(twitter_token_dict.keys()) if twitter_token_dict else 'None'}")
        return None

@celery_app.task(bind=True, name="tasks.download_tweets_task")
def download_tweets_task(self, user_twitter_token, user_google_token, download_params_dict):
    """
    Celery task to download tweets based on parameters and save them to Google Drive.

    Args:
        self (celery.Task): The Celery task instance (automatically passed with bind=True).
        user_twitter_token (dict): User's Twitter OAuth token.
        user_google_token (dict): User's Google OAuth token.
        download_params_dict (dict): Parameters for the download, including:
            - "accounts" (list of str): Twitter usernames.
            - "queries" (list of str): Search query strings.
            - "start_date" (str): ISO 8601 format start date.
            - "end_date" (str): ISO 8601 format end date.
            - "FIMI_Event" (str): Name for the main event folder on Google Drive.
            - "download_limit_per_task" (int): Max tweets to download for this task.
    Raises:
        Exception: If critical errors occur (e.g., client init failure, unrecoverable API error),
                   Celery will mark the task as FAILED.
    Returns:
        dict: A summary of the task result, including status, number of tweets downloaded,
              and Google Drive file details if successful.
    """
    task_id = self.request.id # Unique ID for this task instance
    task_logger.info(f"[Task ID: {task_id}] Starting download_tweets_task. Params: {download_params_dict}")
    self.update_state(state='STARTED', meta={'status': 'Initializing API clients...', 'params_received': download_params_dict})

    tweepy_client = get_twitter_client_for_task(user_twitter_token)
    drive_svc = get_drive_service_for_task(user_google_token)

    if not tweepy_client:
        task_logger.critical(f"[Task ID: {task_id}] CRITICAL: Failed to initialize Twitter client. Task cannot proceed.")
        raise Exception("Twitter client initialization failed in Celery task.") # Celery will mark as FAILED
    if not drive_svc:
        task_logger.critical(f"[Task ID: {task_id}] CRITICAL: Failed to initialize Google Drive service. Task cannot proceed.")
        raise Exception("Google Drive service initialization failed in Celery task.")
    task_logger.info(f"[Task ID: {task_id}] API clients initialized successfully.")

    # Extract and parse download parameters
    accounts = download_params_dict.get('accounts', [])
    queries = download_params_dict.get('queries', [])
    start_date_str = download_params_dict.get('start_date')
    end_date_str = download_params_dict.get('end_date')
    fimi_event_name = download_params_dict.get('FIMI_Event', 'DefaultFIMIEvent') # Default if not provided
    download_limit = int(download_params_dict.get('download_limit_per_task', 100)) # Default limit

    try: # Validate and convert dates
        if not start_date_str or not end_date_str: raise ValueError("Start and end dates are mandatory.")
        start_dt = datetime.fromisoformat(start_date_str).replace(tzinfo=timezone.utc) # Assume UTC
        end_dt = datetime.fromisoformat(end_date_str).replace(tzinfo=timezone.utc)     # Assume UTC
    except ValueError as ve:
        task_logger.error(f"[Task ID: {task_id}] Invalid date format in parameters: {ve}")
        raise Exception(f"Invalid date format. Ensure dates are ISO standard: {ve}")

    # Determine the primary search target and construct the API query
    # This logic might need to be more sophisticated if multiple accounts/queries are processed per task.
    # For now, assumes one main target for this specific task instance.
    target_identifier = "" # Used for folder naming
    api_search_query = ""  # Actual query for Twitter API
    if accounts:
        target_identifier = accounts[0] # Use first account as primary identifier
        base_query = f"from:{target_identifier}"
        # If queries are also present, append the first one to the account query
        api_search_query = base_query + (f" {queries[0]}" if queries and queries[0] else "")
    elif queries and queries[0]: # No accounts, use the first query
        target_identifier = utils.sanitize_filename(queries[0][:30]) # Slug from query
        api_search_query = queries[0]
    else:
        task_logger.error(f"[Task ID: {task_id}] No valid accounts or queries provided.")
        raise ValueError("Task requires at least one account or query.")

    task_logger.info(f"[Task ID: {task_id}] Target: '{target_identifier}', API Query: '{api_search_query}'")
    self.update_state(state='PROGRESS', meta={'status': f'Processing: {target_identifier}', 'query': api_search_query})

    # Create Google Drive folder structure: Event -> Target (Account/Query)
    event_folder = utils.sanitize_filename(fimi_event_name)
    event_folder_id = drive_client.find_or_create_folder_on_service(drive_svc, event_folder, parent_id=None)
    if not event_folder_id: raise Exception(f"Failed to ensure Event folder '{event_folder}' on Drive.")
    task_logger.info(f"[Task ID: {task_id}] Drive Event folder: '{event_folder}' (ID: {event_folder_id})")

    target_subfolder = utils.sanitize_filename(target_identifier)
    final_save_folder_id = drive_client.find_or_create_folder_on_service(drive_svc, target_subfolder, parent_id=event_folder_id)
    if not final_save_folder_id: raise Exception(f"Failed to ensure Target subfolder '{target_subfolder}' on Drive.")
    task_logger.info(f"[Task ID: {task_id}] Drive Target subfolder: '{target_subfolder}' (ID: {final_save_folder_id})")

    self.update_state(state='PROGRESS', meta={'status': f'Fetching tweets for: {api_search_query}'})
    fetched_data = twitter_client.fetch_tweets_for_task(
        tweepy_client=tweepy_client, api_query=api_search_query,
        start_time_dt=start_dt, end_time_dt=end_dt,
        tweet_fields=config.TWEET_FIELDS_COMPREHENSIVE, expansions=config.EXPANSIONS_COMPREHENSIVE,
        user_fields=config.USER_FIELDS_COMPREHENSIVE, media_fields=config.MEDIA_FIELDS_COMPREHENSIVE,
        poll_fields=config.POLL_FIELDS_COMPREHENSIVE, place_fields=config.PLACE_FIELDS_COMPREHENSIVE,
        max_tweets_to_fetch_for_this_task=download_limit
    )

    if fetched_data.get("error"):
        task_logger.error(f"[Task ID: {task_id}] Error fetching tweets: {fetched_data['error']}")
        raise Exception(f"Error during tweet fetching: {fetched_data['error']}")

    num_tweets_collected = fetched_data.get("meta", {}).get("total_collected", 0)
    task_logger.info(f"[Task ID: {task_id}] Fetched {num_tweets_collected} tweets for '{api_search_query}'.")
    self.update_state(state='PROGRESS', meta={'status': f'Fetched {num_tweets_collected} tweets. Preparing to save to Drive...'})

    if num_tweets_collected > 0:
        # Use a FIMI-style slug for the filename, including a timestamp for uniqueness
        timestamp_slug = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        file_slug = utils.get_fimi_slug(target_identifier, "download", start_dt, end_dt) # search_type="download"
        drive_filename = f"{file_slug}_{timestamp_slug}.json"

        # Prepare data for JSON serialization (already dicts from fetch_tweets_for_task)
        json_content = io.BytesIO(json.dumps(fetched_data, indent=2, ensure_ascii=False).encode('utf-8'))

        upload_details = drive_client.upload_file_to_drive_on_service(
            drive_service=drive_svc, file_source=json_content, file_name_on_drive=drive_filename,
            drive_folder_id=final_save_folder_id, content_type='application/json'
        )
        if not upload_details or 'id' not in upload_details:
            task_logger.error(f"[Task ID: {task_id}] Failed to upload file to Drive. Details: {upload_details}")
            raise Exception(f"Failed to upload file to Google Drive. Error: {upload_details.get('error', 'Unknown') if isinstance(upload_details, dict) else 'Upload failed'}")

        task_logger.info(f"[Task ID: {task_id}] Saved {num_tweets_collected} tweets to Drive: {drive_filename} (ID: {upload_details['id']})")
        return {'status': 'SUCCESS', 'tweets_downloaded': num_tweets_collected,
                'drive_file_id': upload_details['id'], 'file_name': drive_filename,
                'drive_folder_id': final_save_folder_id, 'message': 'Download and upload successful.'}
    else:
        task_logger.info(f"[Task ID: {task_id}] No tweets found for criteria. Nothing to save.")
        return {'status': 'SUCCESS', 'tweets_downloaded': 0, 'message': 'No tweets found for the specified criteria.'}
