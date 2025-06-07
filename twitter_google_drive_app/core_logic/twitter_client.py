"""
Module for handling Twitter API interactions.

This module includes functions for:
- Initializing Tweepy clients (app-only and user-context via OAuth).
- Fetching user information (e.g., user ID from username).
- Building search queries for the Twitter API.
- Estimating tweet counts for queries within a date range.
- Fetching tweets and their associated data (media, users, polls, places) using pagination.

It relies on configurations set in `core_logic.config` (API keys, field lists)
and uses Flask-Dance for OAuth token management in the web app context.
"""
import tweepy
import time
import logging
import pandas as pd
from . import config # Use relative import: from . import config
from flask_dance.contrib.twitter import twitter as twitter_blueprint # Access the blueprint proxy
from datetime import datetime as dt, timezone, timedelta # Added for explicit datetime operations

# Configure logging
logger = logging.getLogger(__name__)

# --- App-Only OAuth Client Management ---
_twitter_clients = [] # For app-only bearer tokens
_current_client_index = 0

def load_bearer_tokens():
    """Loads app-only bearer tokens from `config.TWITTER_BEARER_TOKEN`."""
    tokens_str = config.TWITTER_BEARER_TOKEN
    if not tokens_str:
        logger.info("No app-only TWITTER_BEARER_TOKEN found in config. Skipping app-auth client init.")
        return []
    if isinstance(tokens_str, str):
        return [token.strip() for token in tokens_str.split(',') if token.strip()]
    elif isinstance(tokens_str, list):
        return [token for token in tokens_str if token.strip()]
    else:
        logger.error("TWITTER_BEARER_TOKEN in config is not in a valid format (string or list).")
        return []

def initialize_app_only_twitter_clients():
    """
    Initializes Tweepy clients for each app-only bearer token found in config.
    Stores these clients in a module-level list for round-robin usage.
    """
    global _twitter_clients
    _twitter_clients = []
    bearer_tokens = load_bearer_tokens()
    if not bearer_tokens or (len(bearer_tokens) == 1 and "your_twitter_bearer_token" in bearer_tokens[0].lower()):
        logger.warning("Using placeholder or no Twitter App-Only Bearer API token. App-only API calls will fail.")
        return _twitter_clients
    for token_value in bearer_tokens:
        if token_value:
            try:
                client = tweepy.Client(bearer_token=token_value, wait_on_rate_limit=False)
                _twitter_clients.append({"client": client, "token": token_value, "rate_limit_until": 0, "type": "app-only"})
                logger.info("Successfully initialized App-Only Twitter client.")
            except Exception as e:
                logger.error(f"Failed to initialize App-Only Twitter client: {e}")
        else:
            logger.warning("Empty app-only token string found in configuration.")
    if not _twitter_clients: logger.info("No App-Only Twitter clients were initialized.")
    return _twitter_clients

def get_next_available_app_client_fn():
    """
    Retrieves the next available app-only Tweepy client from the pool.
    Implements basic round-robin and rate-limit avoidance (waits if all clients are limited).
    Raises:
        Exception: If no app-only clients are initialized or available after waiting.
    Returns:
        tweepy.Client: An initialized Tweepy client.
    """
    global _current_client_index
    if not _twitter_clients:
        logger.info("No app-only clients available. Attempting to initialize...")
        initialize_app_only_twitter_clients()
        if not _twitter_clients:
             raise Exception("App-Only Twitter clients are not initialized and unavailable.")
    start_index = _current_client_index
    while True:
        client_info = _twitter_clients[_current_client_index]
        if time.time() > client_info.get("rate_limit_until", 0):
            logger.info(f"Using App-Only client index {_current_client_index}")
            _current_client_index = (_current_client_index + 1) % len(_twitter_clients)
            return client_info["client"]
        _current_client_index = (_current_client_index + 1) % len(_twitter_clients)
        if _current_client_index == start_index: # Cycled through all clients
            soonest_available_time = min(c.get("rate_limit_until", float('inf')) for c in _twitter_clients)
            wait_time = soonest_available_time - time.time()
            if wait_time > 0:
                logger.warning(f"All App-Only clients rate-limited. Waiting for {wait_time:.2f} seconds...")
                time.sleep(wait_time)
            # Retry finding a client (could be the one that just became available or continue waiting)
            # Potentially add max retries or total wait time here
    raise Exception("No available App-Only Twitter client after waiting.")


def _update_app_client_rate_limit_info_fn(client_obj, rate_limit_reset_timestamp):
    """Internal helper to update rate limit status for an app-only client."""
    global _twitter_clients
    for client_info in _twitter_clients:
        if client_info["client"] == client_obj:
            client_info["rate_limit_until"] = rate_limit_reset_timestamp
            logger.info(f"Updated rate limit for App-Only client (token ending ...{client_info['token'][-4:]}) until {pd.to_datetime(rate_limit_reset_timestamp, unit='s')}")
            break

# --- User Context OAuth Client ---
def get_user_tweepy_client():
    """
    Initializes and returns a Tweepy client using the user's OAuth token
    obtained via Flask-Dance from the current session.

    Assumes Flask-Dance's Twitter blueprint is using OAuth 1.0a by default.
    The client is configured with `wait_on_rate_limit=True`.

    Returns:
        tweepy.Client or None: An initialized Tweepy client if authorization is
                               successful and token is valid, otherwise None.
    """
    if not twitter_blueprint.authorized:
        logger.warning("Twitter not authorized via Flask-Dance. Cannot get user_tweepy_client.")
        return None
    token = twitter_blueprint.token
    if 'oauth_token' in token and 'oauth_token_secret' in token: # OAuth 1.0a token
        logger.info("Found OAuth 1.0a token. Initializing Tweepy client for user context.")
        try:
            client = tweepy.Client(
                consumer_key=config.TWITTER_CLIENT_ID,
                consumer_secret=config.TWITTER_CLIENT_SECRET,
                access_token=token['oauth_token'],
                access_token_secret=token['oauth_token_secret'],
                wait_on_rate_limit=True # Recommended for user-facing operations
            )
            # Optional: Test client validity with a lightweight call like get_me()
            # test_user = client.get_me()
            # if not (test_user and test_user.data):
            #     logger.warning("get_me() check failed for user OAuth client. Token might be invalid.")
            #     return None
            return client
        except Exception as e:
            logger.error(f"Failed to initialize Tweepy client with user OAuth 1.0a token: {e}", exc_info=True)
            return None
    # Add elif block here for OAuth 2.0 PKCE user token if Flask-Dance setup changes
    else:
        logger.error(f"Twitter token from Flask-Dance not in expected OAuth 1.0a format. Keys: {token.keys() if token else 'None'}")
        return None

# --- User Information ---
_user_id_cache = {}
def get_user_id_from_username_cached_fn(username, use_user_auth=False):
    """
    Fetches a user's ID from their username using the Twitter API.
    Results are cached in memory to reduce redundant API calls.

    Args:
        username (str): The Twitter username (screen name).
        use_user_auth (bool): If True, attempts to use the user-authenticated client.
                              Otherwise, uses an app-only client.
    Returns:
        str or None: The user ID if found, otherwise None.
    """
    if username in _user_id_cache:
        logger.info(f"User ID for '{username}' found in cache: {_user_id_cache[username]}")
        return _user_id_cache[username]
    client_to_use = get_user_tweepy_client() if use_user_auth else get_next_available_app_client_fn()
    if not client_to_use:
        client_type = "user-auth" if use_user_auth else "app-only"
        logger.error(f"No {client_type} Twitter client available to fetch user ID for '{username}'.")
        return None
    try:
        user_response = client_to_use.get_user(username=username)
        if user_response.data:
            user_id = user_response.data.id
            _user_id_cache[username] = user_id
            logger.info(f"Fetched user ID for '{username}': {user_id}")
            return user_id
        else:
            logger.warning(f"User '{username}' not found or error in response: {user_response.errors}")
            return None
    except tweepy.TweepyException as e: # More specific exceptions can be caught
        logger.error(f"Tweepy exception fetching ID for '{username}': {e}", exc_info=True)
        # Rate limit handling for app-only client if not using wait_on_rate_limit for it
        if not use_user_auth and isinstance(e, tweepy.TooManyRequests) and e.response is not None:
             reset_time = int(e.response.headers.get('x-rate-limit-reset', time.time() + 900))
             _update_app_client_rate_limit_info_fn(client_to_use, reset_time)
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching ID for '{username}': {e}", exc_info=True)
        return None

# --- Query Construction ---
def build_full_search_query_fn(query_template, actor_screen_name, other_params=None):
    """Builds a Twitter search query string using a template and parameters."""
    # This is a basic implementation; more complex logic from notebook might be needed.
    query = query_template.format(actor_screen_name, actor_screen_name) # Assumes two placeholders for actor
    if other_params: query += f" {other_params}"
    logger.info(f"Built search query: {query}")
    return query

# --- Tweet Count Estimation ---
def get_single_task_estimate(tweepy_client, api_query, start_time_dt, end_time_dt, granularity="day"):
    """
    Estimates tweet counts for a given query and time range using the Twitter API v2.

    Args:
        tweepy_client (tweepy.Client): An initialized Tweepy client.
        api_query (str): The search query string.
        start_time_dt (datetime): Start datetime (inclusive), preferably timezone-aware (UTC).
        end_time_dt (datetime): End datetime (exclusive), preferably timezone-aware (UTC).
        granularity (str): 'day' or 'hour'. For 'all' counts, 'minute' is also valid.
                           If None, total count is fetched without time breakdown.

    Returns:
        dict: Contains estimated_count, status, and potentially data_breakdown or error details.
    """
    logger.info(f"Estimating counts for query='{api_query}', start='{start_time_dt}', end='{end_time_dt}', granularity='{granularity}'")
    if not tweepy_client:
        return {"query": api_query, "estimated_count": 0, "status": "error_client_not_provided", "details": "Tweepy client is None."}
    try:
        # Ensure datetimes are in ISO 8601 format and UTC for Twitter API
        start_iso = (start_time_dt.astimezone(timezone.utc) if start_time_dt.tzinfo else start_time_dt.replace(tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")
        end_iso = (end_time_dt.astimezone(timezone.utc) if end_time_dt.tzinfo else end_time_dt.replace(tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")

        now_utc = dt.now(timezone.utc)
        compare_start_dt = start_time_dt.astimezone(timezone.utc) if start_time_dt.tzinfo else start_time_dt.replace(tzinfo=timezone.utc)

        count_method_name = "get_recent_tweets_count"
        if compare_start_dt < (now_utc - timedelta(days=6)):
             if hasattr(tweepy_client, 'get_all_tweets_count'):
                 count_method = tweepy_client.get_all_tweets_count
                 count_method_name = "get_all_tweets_count"
                 logger.info("Query start time >7 days old; using get_all_tweets_count (requires Academic Access).")
             else:
                 return {"query": api_query, "estimated_count": 0, "status": "error_data_range_unsupported", "details": "Data older than 7 days and Academic Access method not available."}
        else:
            count_method = tweepy_client.get_recent_tweets_count
            logger.info("Using get_recent_tweets_count.")

        count_args = {"query": api_query, "start_time": start_iso, "end_time": end_iso}
        if granularity and (count_method_name == 'get_all_tweets_count' or granularity != 'day'):
            count_args["granularity"] = granularity

        response = count_method(**count_args)
        if response and response.meta and "total_tweet_count" in response.meta:
            return {"query": api_query, "estimated_count": response.meta["total_tweet_count"], "status": "success",
                    "granularity_used": count_args.get("granularity"), "data_breakdown": response.data }
        elif response and response.errors:
            return {"query": api_query, "estimated_count": 0, "status": "error_api_response", "details": response.errors}
        else:
            details = str(response) if response is not None else "No response object"
            if hasattr(response, 'meta') and response.meta is not None and "total_tweet_count" not in response.meta:
                details = f"Response meta missing 'total_tweet_count'. Meta: {response.meta}"
            return {"query": api_query, "estimated_count": 0, "status": "error_unexpected_response", "details": details }
    except tweepy.TweepyException as e:
        return {"query": api_query, "estimated_count": 0, "status": "error_tweepy_exception", "details": str(e)}
    except Exception as e:
        return {"query": api_query, "estimated_count": 0, "status": "error_unknown", "details": str(e)}

# --- Tweet Fetching ---
def fetch_tweets_for_task(tweepy_client, api_query, start_time_dt, end_time_dt,
                          tweet_fields, expansions, user_fields, media_fields, poll_fields, place_fields,
                          max_tweets_to_fetch_for_this_task=100):
    """
    Fetches tweets and associated data for a given query and time range using Paginator.

    Args:
        tweepy_client (tweepy.Client): Initialized Tweepy client (user-context recommended, with wait_on_rate_limit=True).
        api_query (str): The Twitter API search query.
        start_time_dt (datetime): Start datetime (inclusive), preferably UTC.
        end_time_dt (datetime): End datetime (exclusive), preferably UTC.
        tweet_fields, expansions, ... : Lists of fields to request from Twitter API.
        max_tweets_to_fetch_for_this_task (int): Maximum number of tweets to retrieve for this specific task.

    Returns:
        dict: A dictionary containing lists of tweet data, included objects (media, users, etc.),
              metadata about the fetch, or an error dictionary if issues occur.
    """
    logger.info(f"Fetching tweets: Query='{api_query}', Start='{start_time_dt}', End='{end_time_dt}', Limit='{max_tweets_to_fetch_for_this_task}'")
    if not tweepy_client:
        return {"error": "Tweepy client not provided.", "query": api_query, "tweets_data": [], "meta": {"total_collected": 0}}

    start_iso = (start_time_dt.astimezone(timezone.utc) if start_time_dt.tzinfo else start_time_dt.replace(tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")
    end_iso = (end_time_dt.astimezone(timezone.utc) if end_time_dt.tzinfo else end_time_dt.replace(tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z")

    all_tweets_data, all_includes_media, all_includes_users, all_includes_polls, all_includes_places = [], [], [], [], []
    tweets_collected_count = 0

    try:
        now_utc = dt.now(timezone.utc)
        compare_start_dt = start_time_dt.astimezone(timezone.utc) if start_time_dt.tzinfo else start_time_dt.replace(tzinfo=timezone.utc)

        paginator_method_name = "search_recent_tweets"
        if hasattr(tweepy_client, "search_all_tweets") and compare_start_dt < (now_utc - timedelta(days=6)):
            paginator_method = tweepy_client.search_all_tweets
            logger.info("Using search_all_tweets (Academic Access) for fetching.")
        else:
            paginator_method = tweepy_client.search_recent_tweets
            logger.info("Using search_recent_tweets for fetching.")

        # Max results per page for search_all_tweets can be up to 500, for search_recent_tweets up to 100.
        # Paginator's limit parameter is for total items. max_results is per-page.
        # We want to respect max_tweets_to_fetch_for_this_task overall.
        # Tweepy's Paginator itself can take a `limit` argument for total items.
        # However, to manage per-page max_results correctly based on endpoint limits:
        page_max_results = 100 # Default for recent_search
        if paginator_method_name == "search_all_tweets":
            page_max_results = 500 # Can be higher for academic access to "all" endpoint.

        # If max_tweets_to_fetch_for_this_task is less than page_max_results, use it for the first page.
        # Paginator itself doesn't have a per-page max_results that dynamically adjusts with overall limit.
        # We handle overall limit by breaking the loop.

        paginator = tweepy.Paginator(
            paginator_method, query=api_query, start_time=start_iso, end_time=end_iso,
            tweet_fields=tweet_fields, expansions=expansions, user_fields=user_fields,
            media_fields=media_fields, poll_fields=poll_fields, place_fields=place_fields,
            max_results=page_max_results
        )

        for response in paginator:
            if response.data:
                num_found_in_page = len(response.data)
                for t in response.data: all_tweets_data.append(t.data)
                if response.includes:
                    if 'media' in response.includes: all_includes_media.extend([m.data for m in response.includes['media']])
                    if 'users' in response.includes: all_includes_users.extend([u.data for u in response.includes['users']])
                    if 'polls' in response.includes: all_includes_polls.extend([p.data for p in response.includes['polls']])
                    if 'places' in response.includes: all_includes_places.extend([pl.data for pl in response.includes['places']])
                tweets_collected_count += num_found_in_page
                logger.info(f"Collected {tweets_collected_count}/{max_tweets_to_fetch_for_this_task if max_tweets_to_fetch_for_this_task else 'all'} tweets for query '{api_query}'...")
            if max_tweets_to_fetch_for_this_task and tweets_collected_count >= max_tweets_to_fetch_for_this_task:
                logger.info(f"Reached download limit ({max_tweets_to_fetch_for_this_task}) for query '{api_query}'.")
                # Truncate if over limit due to last page
                # This logic is slightly complex if we fetch page by page and then check limit.
                # Paginator's own limit is better if precise numbers are critical on first call.
                # For now, this break is fine.
                break

        logger.info(f"Finished fetching. Total tweets collected: {tweets_collected_count} for query '{api_query}'.")
        # Truncate results if collected more than limit in the last page
        if max_tweets_to_fetch_for_this_task and tweets_collected_count > max_tweets_to_fetch_for_this_task:
            # This requires careful handling of includes as well, to match the truncated tweets.
            # Simplification: For now, we assume the `break` above is sufficient and might collect slightly more.
            # Or, we rely on Paginator's `limit` argument if it can be passed dynamically.
            # For this implementation, the break is the primary limiting factor.
            pass

        return {
            "query": api_query, "status": "success",
            "tweets_data": all_tweets_data[:max_tweets_to_fetch_for_this_task] if max_tweets_to_fetch_for_this_task else all_tweets_data,
            "includes_media": all_includes_media, # Note: includes are not truncated to match tweets here; could be refined
            "includes_users": all_includes_users,
            "includes_polls": all_includes_polls,
            "includes_places": all_includes_places,
            "meta": {"total_collected": min(tweets_collected_count, max_tweets_to_fetch_for_this_task) if max_tweets_to_fetch_for_this_task else tweets_collected_count}
        }
    except tweepy.TweepyException as e: # Client should have wait_on_rate_limit=True
        logger.error(f"TweepyException fetching tweets for query='{api_query}': {e}", exc_info=True)
        return {"error": f"Tweepy API error: {str(e)}", "query": api_query, "tweets_data": all_tweets_data, "meta": {"total_collected": tweets_collected_count}}
    except Exception as e:
        logger.error(f"Unexpected error fetching tweets for query='{api_query}': {e}", exc_info=True)
        return {"error": f"Unexpected error: {str(e)}", "query": api_query, "tweets_data": all_tweets_data, "meta": {"total_collected": tweets_collected_count}}


# --- Legacy function name from notebook refactoring (prefer fetch_tweets_for_task) ---
def trigger_actual_download_process_phase4_fn(*args, **kwargs):
    """Legacy wrapper for fetch_tweets_for_task."""
    logger.warning("trigger_actual_download_process_phase4_fn is deprecated. Use fetch_tweets_for_task.")
    # Assuming the arguments match or can be mapped to fetch_tweets_for_task
    # This mapping depends on the exact signature of the old function.
    # For simplicity, let's assume direct pass-through if possible, or raise error.
    # This function was: (query, start_time, end_time, tweet_fields, expansions, media_fields,
    #                    poll_fields, user_fields, place_fields, max_results_per_call=100,
    #                    limit=None, use_user_auth=False)

    # Map old params to new ones if necessary:
    # client = get_user_tweepy_client() if kwargs.get('use_user_auth') else get_next_available_app_client_fn()
    # api_query = kwargs.get('query')
    # ... and so on for all fields. max_tweets_to_fetch_for_this_task = kwargs.get('limit')

    # This is a simplified call, real mapping might be needed.
    # return fetch_tweets_for_task(client, api_query, start_time_dt, end_time_dt, ...)
    raise NotImplementedError("trigger_actual_download_process_phase4_fn is deprecated and not fully mapped to new functions.")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    logger.info("Testing twitter_client.py (OAuth aspects require running Flask app)...")
    from dotenv import load_dotenv
    import os
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(dotenv_path): load_dotenv(dotenv_path)
    import importlib
    importlib.reload(config)
    app_clients = initialize_app_only_twitter_clients()
    if app_clients: logger.info(f"{len(app_clients)} App-Only Twitter client(s) initialized.")
    else: logger.warning("No App-Only Twitter clients initialized.")
    logger.info("twitter_client.py standalone checks completed.")
