"""
Main Flask application file.

Handles:
- Flask app initialization.
- OAuth 2.0 authentication setup with Twitter and Google using Flask-Dance.
- Routes for home page, login/logout, OAuth callbacks.
- API endpoints for:
    - Twitter tweet count estimation (`/twitter/estimate`).
    - Asynchronous tweet download to Google Drive (`/twitter/download`).
    - Checking status of Celery tasks (`/task_status/<task_id>`).
    - Listing files on Google Drive (`/drive/list_files`).
- Test routes for authenticated API calls (`/twitter/profile`, `/drive/myfiles_test`).
"""
from flask import Flask, session, redirect, url_for, jsonify, request
from flask_dance.contrib.twitter import make_twitter_blueprint, twitter
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer.storage.session import SessionStorage
from flask_dance.consumer import oauth_authorized, oauth_error
from core_logic.config import FLASK_SECRET_KEY, TWITTER_CLIENT_ID, TWITTER_CLIENT_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from core_logic import twitter_client, drive_client, utils
from datetime import datetime
import os
import logging
import io
import json
# Celery specific imports for task status
from celery.result import AsyncResult
# Assuming celery_app_setup.py is in the same directory (twitter_google_drive_app)
from .celery_app_setup import celery_app # Relative import for celery_app instance

# Basic logging setup for the app
# Consider moving to a more structured logging configuration (e.g., from a settings file or dictConfig)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY # Essential for session management and Flask-Dance

# Ensure log and data directories from config exist (config.py already does this)
from core_logic.config import LOGS_PATH, ACTORS_BASE_DIR
logger.info(f"Log path configured to: {LOGS_PATH}")
logger.info(f"Actors base directory (local data example) configured to: {ACTORS_BASE_DIR}")


# --- OAuth Blueprints Setup ---
# Twitter OAuth: Uses OAuth 1.0a by default with Flask-Dance.
# For Twitter API v2 specific endpoints, OAuth 2.0 PKCE might be required,
# which could involve a custom Flask-Dance provider or different token handling.
twitter_bp = make_twitter_blueprint(
    api_key=TWITTER_CLIENT_ID,          # Twitter App's "API Key"
    api_secret=TWITTER_CLIENT_SECRET,   # Twitter App's "API Key Secret"
    redirect_to="twitter_authorized_route", # Route name for callback after Twitter auth
    storage=SessionStorage(token_key='twitter_oauth_token') # Store token in Flask session
)
app.register_blueprint(twitter_bp, url_prefix="/auth")

# Google OAuth: Uses OAuth 2.0.
google_bp = make_google_blueprint(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    scope=[ # Requested permissions from the user
        "openid",                                      # Standard OpenID Connect scope
        "https://www.googleapis.com/auth/userinfo.email",    # Access user's email address
        "https://www.googleapis.com/auth/userinfo.profile",  # Access user's basic profile info
        "https://www.googleapis.com/auth/drive.file"     # Full access to files created or opened by the app
        # Consider more granular scopes like 'drive.appdata' or 'drive.readonly' if full file access isn't needed.
    ],
    redirect_to="google_authorized_route", # Route name for callback after Google auth
    storage=SessionStorage(token_key='google_oauth_token') # Store token in Flask session
)
app.register_blueprint(google_bp, url_prefix="/auth")

# --- Basic Routes (Home, Logout, OAuth Callbacks) ---
@app.route('/')
def home():
    """Displays authentication status and links to login or test authenticated actions."""
    twitter_authed = twitter.authorized
    google_authed = google.authorized

    auth_status_parts = [
        f"<h2>Authentication Status:</h2>",
        f"Twitter Authenticated: {twitter_authed}",
        f"Google Authenticated: {google_authed}",
        "<br><br>-- Actions --"
    ]
    login_links = ['<p><a href="/">Home</a></p>']
    if not twitter_authed:
        login_links.append('<a href="/auth/twitter">Login with Twitter</a>')
    else:
        login_links.append('<a href="/twitter/profile">View Twitter Profile (Test)</a>')
        login_links.append('<a href="/auth/twitter/logout">Logout Twitter</a>')
    if not google_authed:
        login_links.append('<a href="/auth/google">Login with Google</a>')
    else:
        login_links.append('<a href="/drive/myfiles_test">List Google Drive Files (Test)</a>')
        login_links.append('<a href="/auth/google/logout">Logout Google</a>')
    return "<br>".join(auth_status_parts + login_links)

@app.route("/auth/twitter/logout")
def twitter_logout():
    """Clears Twitter token from session."""
    session.pop("twitter_oauth_token", None)
    logger.info("User logged out from Twitter session.")
    return redirect(url_for("home"))

@app.route("/auth/google/logout")
def google_logout():
    """Clears Google token from session and attempts to revoke it."""
    token_key = google_bp.storage.token_key
    token = session.get(token_key)
    if token and 'access_token' in token:
        try: # Attempt to revoke the token with Google
            import requests # Ensure 'requests' is in requirements.txt
            revoke_url = 'https://oauth2.googleapis.com/revoke'
            response = requests.post(revoke_url, params={'token': token['access_token']},
                                     headers={'content-type': 'application/x-www-form-urlencoded'})
            if response.status_code == 200: logger.info("Successfully revoked Google token.")
            else: logger.warning(f"Failed to revoke Google token. Status: {response.status_code}, Body: {response.text}")
        except Exception as e: logger.error(f"Error during Google token revocation: {e}", exc_info=True)
    session.pop(token_key, None)
    logger.info("User logged out from Google session.")
    return redirect(url_for("home"))

@app.route('/auth/twitter/authorized')
def twitter_authorized_route():
    """Callback route after Twitter authorization."""
    if not twitter.authorized:
        logger.warning("Twitter authorization failed or was denied by user.")
        return "Twitter authorization failed or was denied. Please try again."
    logger.info("Twitter authorization successful.")
    return redirect(url_for("home"))

@app.route('/auth/google/authorized')
def google_authorized_route():
    """Callback route after Google authorization."""
    if not google.authorized:
        logger.warning("Google authorization failed or was denied by user.")
        return "Google authorization failed or was denied. Please try again."
    logger.info("Google authorization successful.")
    return redirect(url_for("home"))

# --- Test Routes for Authenticated API Calls (demonstration purposes) ---
@app.route('/twitter/profile')
def twitter_profile_test():
    """Tests fetching user's Twitter profile using the stored OAuth token."""
    if not twitter.authorized:
        return redirect(url_for("twitter.login"))
    logger.info("Attempting to fetch Twitter profile using Flask-Dance direct call (users/me).")
    try:
        # Twitter API v2 'users/me' endpoint. Fields can be customized.
        resp = twitter.get("users/me", params={"user.fields": "id,username,name,created_at,description,public_metrics"})
        if resp.ok:
            user_data = resp.json().get('data', {})
            logger.info(f"Successfully fetched Twitter profile for user: {user_data.get('username')}")
            return jsonify(user_data)
        else:
            logger.error(f"Failed to get Twitter profile: {resp.status_code} - {resp.text}")
            return f"Failed to get Twitter profile: {resp.status_code} {resp.text}", resp.status_code
    except Exception as e:
        logger.error(f"Exception fetching Twitter profile: {e}", exc_info=True)
        return f"Error fetching Twitter profile: {str(e)}", 500

@app.route('/drive/myfiles_test')
def list_drive_files_test():
    """Tests listing files from user's Google Drive root using stored OAuth token."""
    if not google.authorized:
        return redirect(url_for("google.login"))
    logger.info("Attempting to list Google Drive files (root, 10 files) using Flask-Dance direct call.")
    try:
        resp = google.get("https://www.googleapis.com/drive/v3/files",
                          params={"pageSize": 10, "fields": "files(id, name, mimeType, webViewLink)"})
        if resp.ok:
            logger.info("Successfully listed Google Drive files (up to 10).")
            return jsonify(resp.json())
        else:
            logger.error(f"Failed to list Google Drive files: {resp.status_code} - {resp.text}")
            return f"Failed to list Google Drive files: {resp.status_code} {resp.text}", resp.status_code
    except Exception as e:
        logger.error(f"Exception listing Google Drive files: {e}", exc_info=True)
        return f"Error listing Google Drive files: {str(e)}", 500

# --- OAuth Event Handlers (for logging/debugging OAuth process) ---
@oauth_authorized.connect_via(twitter_bp)
def twitter_logged_in(blueprint, token):
    logger.info(f"Twitter OAuth successful via {blueprint.name}. Token keys: {list(token.keys()) if token else 'None'}.")
@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    logger.info(f"Google OAuth successful via {blueprint.name}. Token keys: {list(token.keys()) if token else 'None'}.")
    if token and 'refresh_token' not in token:
        logger.warning("Google OAuth token does not include a refresh_token. Offline access will be limited.")
@oauth_error.connect_via(twitter_bp)
def twitter_oauth_error(blueprint, error, error_description=None, error_uri=None):
    logger.error(f"Twitter OAuth error ({blueprint.name}): {error}, Desc: {error_description}, URI: {error_uri}")
@oauth_error.connect_via(google_bp)
def google_oauth_error(blueprint, error, error_description=None, error_uri=None):
    logger.error(f"Google OAuth error ({blueprint.name}): {error}, Desc: {error_description}, URI: {error_uri}")

# --- Core API Endpoints ---
@app.route('/twitter/estimate', methods=['POST'])
def twitter_estimate_api():
    """
    API endpoint to estimate tweet counts for given accounts/queries and date range.
    Expects JSON payload with: "accounts" (list), "queries" (list),
    "start_date" (str YYYY-MM-DD), "end_date" (str YYYY-MM-DD).
    At least one of accounts or queries must be provided.
    """
    if not twitter.authorized:
        return jsonify({"error": "User not authenticated with Twitter"}), 401
    try:
        data = request.get_json()
        if not data: return jsonify({"error": "Invalid or missing JSON payload"}), 400
        accounts = data.get("accounts", [])
        queries = data.get("queries", [])
        start_date_str, end_date_str = data.get("start_date"), data.get("end_date")
        if not (accounts or queries) or not start_date_str or not end_date_str:
            return jsonify({"error": "Missing required parameters (accounts/queries, start_date, end_date)"}), 400
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError: return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
    except Exception as e: return jsonify({"error": f"Invalid request: {str(e)}"}), 400

    client = twitter_client.get_user_tweepy_client()
    if not client: return jsonify({"error": "Twitter client initialization failed."}), 500

    search_terms = [f"from:{acc}" for acc in accounts if acc] + [q for q in queries if q]
    if not search_terms: return jsonify({"error": "No valid search terms derived from accounts or queries."}), 400

    estimation_results = []
    for term in search_terms:
        logger.info(f"Estimating for term: '{term}', Start: {start_dt}, End: {end_dt}")
        try:
            result = twitter_client.get_single_task_estimate(
                tweepy_client=client, api_query=term, start_time_dt=start_dt, end_time_dt=end_dt,
                granularity=data.get("granularity", "day") # Allow granularity from request
            )
            estimation_results.append(result)
        except Exception as e:
            logger.error(f"Error during estimation for term '{term}': {e}", exc_info=True)
            estimation_results.append({"term": term, "estimated_count": 0, "status": f"error: {str(e)}"})
    return jsonify(estimation_results)

@app.route('/twitter/download', methods=['POST'])
def twitter_download_api():
    """
    API endpoint to start an asynchronous task for downloading tweets.
    Expects JSON payload with: "accounts", "queries", "start_date", "end_date",
    "FIMI_Event" (for Drive folder naming), "download_limit_per_task".
    """
    if not twitter.authorized: return jsonify({"error": "User not authenticated with Twitter"}), 401
    if not google.authorized: return jsonify({"error": "User not authenticated with Google Drive"}), 401
    try:
        data = request.get_json()
        if not data: return jsonify({"error": "Invalid or missing JSON payload"}), 400
        accounts = data.get("accounts", [])
        queries = data.get("queries", [])
        start_date_str, end_date_str = data.get("start_date"), data.get("end_date")
        if not (accounts or queries) or not start_date_str or not end_date_str:
            return jsonify({"error": "Missing required parameters (accounts/queries, start_date, end_date)"}), 400
        # Ensure dates are valid before passing to Celery task (ISO format expected by task)
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
        download_task_params = {
            "accounts": accounts, "queries": queries,
            "start_date": start_dt.isoformat(), "end_date": end_dt.isoformat(),
            "FIMI_Event": data.get("FIMI_Event", "DefaultFIMIEvent"), # Celery task should use a default too
            "download_limit_per_task": int(data.get("download_limit_per_task", 100))
        }
    except ValueError: return jsonify({"error": "Invalid date format or number. Use YYYY-MM-DD for dates."}), 400
    except Exception as e: return jsonify({"error": f"Invalid request: {str(e)}"}), 400

    user_twitter_token = session.get('twitter_oauth_token')
    user_google_token = session.get('google_oauth_token')
    if not user_twitter_token or not user_google_token:
        return jsonify({"error": "User tokens not found in session."}), 401

    from tasks import download_tweets_task # Import Celery task
    try:
        logger.info(f"Queuing download_tweets_task with params: {download_task_params}")
        task = download_tweets_task.delay(
            user_twitter_token=user_twitter_token,
            user_google_token=user_google_token,
            download_params_dict=download_task_params
        )
        logger.info(f"Download task queued. Task ID: {task.id}")
        return jsonify({"message": "Download task successfully queued.", "task_id": task.id}), 202
    except Exception as e:
        logger.error(f"Failed to queue Celery task: {e}", exc_info=True)
        return jsonify({"error": f"Failed to queue download task: {str(e)}"}), 500

# --- Task Status Endpoint ---
@app.route('/task_status/<task_id>')
def task_status(task_id):
    """Polls Celery for the status of a given task ID."""
    if not (google.authorized or twitter.authorized): # Basic auth check
        return jsonify({"error": "User not authenticated"}), 401
    task_result = AsyncResult(task_id, app=celery_app)
    response_data = {'task_id': task_id, 'state': task_result.state, 'info': {}}
    if task_result.state == 'PENDING': response_data['info']['status'] = 'Task is pending.'
    elif task_result.state == 'STARTED': response_data['info'] = task_result.info if isinstance(task_result.info, dict) else {'status': str(task_result.info)}
    elif task_result.state == 'PROGRESS': response_data['info'] = task_result.info if isinstance(task_result.info, dict) else {'status': str(task_result.info)}
    elif task_result.state == 'SUCCESS': response_data['info'] = {'status': 'Task completed successfully.', 'result': task_result.info}
    elif task_result.state == 'FAILURE':
        response_data['info'] = {'status': 'Task failed.',
                                 'error_type': type(task_result.info).__name__ if task_result.info else 'Unknown',
                                 'error_message': str(task_result.info) if task_result.info else 'No details.'}
    else: response_data['info'] = {'status': f'Task state: {task_result.state}', 'details': str(task_result.info)}
    return jsonify(response_data)

@app.route('/drive/list_files', methods=['GET'])
def drive_list_files_api():
    """
    Lists files/folders in a specified Google Drive folder.
    Query Parameters:
        - folder_id (str, optional): ID of the Drive folder. Defaults to root.
        - folder_name (str, optional): Name of the folder. Used if folder_id is not provided.
        - parent_folder_id (str, optional): Parent ID if searching by folder_name in a specific location.
        - item_type (str, optional): 'files' or 'folders'. Defaults to all.
    """
    if not google.authorized: return jsonify({"error": "User not authenticated with Google Drive"}), 401
    folder_id, folder_name = request.args.get('folder_id'), request.args.get('folder_name')
    parent_folder_id = request.args.get('parent_folder_id')
    item_type_filter = request.args.get('item_type') # e.g., 'files' or 'folders'
    target_folder_id_to_list = folder_id
    try:
        if not target_folder_id_to_list and folder_name:
            logger.info(f"Searching for Drive folder: '{folder_name}' (Parent: '{parent_folder_id or 'root'}')")
            found_id = drive_client.find_folder_id(folder_name, parent_folder_id=parent_folder_id)
            if not found_id: return jsonify({"error": f"Folder '{folder_name}' not found."}), 404
            target_folder_id_to_list = found_id

        folder_display_name = target_folder_id_to_list if target_folder_id_to_list else 'root'
        logger.info(f"Listing items for Drive folder ID: '{folder_display_name}', Type: '{item_type_filter or 'all'}'")
        items = drive_client.list_drive_items(folder_id=target_folder_id_to_list, item_type=item_type_filter)

        if items is not None: return jsonify({"folder_id_listed": folder_display_name, "items": items})
        else: return jsonify({"error": f"Failed to list items for folder ID '{folder_display_name}'."}), 500
    except Exception as e:
        logger.error(f"Exception in /drive/list_files: {e}", exc_info=True)
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    logger.info("Starting Flask application for development...")
    # For dev, ensure Werkzeug reloader can find Celery app if using `flask run --reload`
    # This might involve ensuring celery_app_setup is imported early or structure allows it.
    # Host 0.0.0.0 makes it accessible on local network if needed.
    app.run(debug=True, host="0.0.0.0", port=5000)
