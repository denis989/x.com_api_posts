"""
Application Configuration Management.

This module loads environment variables from a .env file and sets up
configuration values used throughout the application. It includes API keys,
Flask settings, Celery settings, and paths for storing data and logs.
It also defines constants for Twitter API field requests.

Sensitive information should be stored in the .env file and not committed to
version control. An .env.example file provides a template for required variables.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file located in the parent directory (project root)
# Ensures that this config module can be imported from various places (app, tasks, tests)
# and still find the .env file correctly.
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=dotenv_path)

# --- Flask Application Settings ---
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "you-should-set-a-strong-secret-key-in-production")
# Example: FLASK_ENV = os.getenv("FLASK_ENV", "production")

# --- Twitter API Credentials ---
# For user authentication (OAuth 1.0a or OAuth 2.0 PKCE)
TWITTER_CLIENT_ID = os.getenv("TWITTER_CLIENT_ID")      # Twitter App's API Key / Client ID
TWITTER_CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET")# Twitter App's API Key Secret / Client Secret

# Optional: For App-Only Authentication (if specific endpoints require it)
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# --- Google API Credentials ---
# For user authentication (OAuth 2.0)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
# Path to service account key file (JSON) if using a service account for specific backend tasks.
# For user-driven OAuth flow in the web app, this is typically not used.
GOOGLE_DRIVE_CREDENTIALS_FILE = os.getenv("GOOGLE_DRIVE_CREDENTIALS_FILE_PATH_IF_SERVICE_ACCOUNT") # Or None

# --- Application Paths ---
# BASE_APP_PATH points to this directory (core_logic)
BASE_APP_PATH = os.path.abspath(os.path.dirname(__file__))
# LOGS_PATH is project_root/logs
LOGS_PATH = os.path.join(BASE_APP_PATH, "..", "logs")
# ACTORS_BASE_DIR is project_root/downloaded_data/actors (example for local data storage if needed)
ACTORS_BASE_DIR = os.path.join(BASE_APP_PATH, "..", "downloaded_data", "actors")

# Ensure necessary directories exist at startup
os.makedirs(LOGS_PATH, exist_ok=True)
os.makedirs(ACTORS_BASE_DIR, exist_ok=True) # This might be for local data, Drive is primary for tweet downloads

# --- Celery Configuration ---
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

# --- Twitter API Request Field Constants ---
# These lists define the fields to request from the Twitter API v2.
TWEET_FIELDS_COMPREHENSIVE = [
    "attachments", "author_id", "context_annotations", "conversation_id",
    "created_at", "edit_controls", "edit_history_tweet_ids", "entities",
    "geo", "id", "in_reply_to_user_id", "lang", "possibly_sensitive",
    "public_metrics", "referenced_tweets", "reply_settings", "source", "text",
    "withheld"
]

EXPANSIONS_COMPREHENSIVE = [
    "attachments.media_keys", "attachments.poll_ids", "author_id",
    "edit_history_tweet_ids", "entities.mentions.username", "geo.place_id",
    "in_reply_to_user_id", "referenced_tweets.id", "referenced_tweets.id.author_id"
]

USER_FIELDS_COMPREHENSIVE = [
    "created_at", "description", "entities", "id", "location", "name",
    "pinned_tweet_id", "profile_image_url", "protected", "public_metrics",
    "url", "username", "verified", "verified_type", "withheld"
]

MEDIA_FIELDS_COMPREHENSIVE = [
    "alt_text", "duration_ms", "height", "media_key", "non_public_metrics",
    "organic_metrics", "preview_image_url", "promoted_metrics", "public_metrics",
    "type", "url", "variants", "width"
]

POLL_FIELDS_COMPREHENSIVE = [
    "duration_minutes", "end_datetime", "id", "options", "voting_status"
]

PLACE_FIELDS_COMPREHENSIVE = [
    "contained_within", "country", "country_code", "full_name", "geo", "id",
    "name", "place_type"
]


# --- Deprecated Notebook Path References (for historical context if needed) ---
OLD_BASE_DRIVE_PATH_REF = "/content/drive/My Drive/ENC/Data/"
OLD_LOGS_PATH_NOTEBOOK_REF = os.path.join(OLD_BASE_DRIVE_PATH_REF, "logs")
OLD_ACTORS_BASE_DIR_NOTEBOOK_REF = os.path.join(OLD_BASE_DRIVE_PATH_REF, "actors")
OLD_KEYS_PATH_NOTEBOOK_REF = os.path.join(OLD_BASE_DRIVE_PATH_REF, "keys")

# --- Startup Configuration Checks (output to console during development) ---
# These help verify that the .env file is loaded and essential variables are set.
if __name__ != "__main__": # Only print warnings if imported, not if run directly (if ever)
    if not FLASK_SECRET_KEY or FLASK_SECRET_KEY == "you-should-set-a-strong-secret-key-in-production":
        print("WARNING: FLASK_SECRET_KEY is not set securely. Please update it in your .env file for production.")
    for var_name in ["TWITTER_CLIENT_ID", "TWITTER_CLIENT_SECRET", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]:
        if not globals().get(var_name):
            print(f"WARNING: {var_name} is not set in .env. Application may not function correctly.")
    if CELERY_BROKER_URL == "redis://localhost:6379/0":
        print("INFO: Using default CELERY_BROKER_URL (redis://localhost:6379/0). Ensure Redis is running for Celery.")
    if CELERY_RESULT_BACKEND == "redis://localhost:6379/0":
        print("INFO: Using default CELERY_RESULT_BACKEND (redis://localhost:6379/0).")
