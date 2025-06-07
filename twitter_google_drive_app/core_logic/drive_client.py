"""
Module for handling Google Drive API interactions.

This module provides functions to:
- Obtain an authenticated Google Drive API service client using Flask-Dance (for web requests).
- Find, create, and manage folders on Google Drive.
- Upload files (from path or stream) to Google Drive.
- List items within a Google Drive folder.

It includes two sets of Drive interaction functions:
1. Functions that accept an initialized `drive_service` object: These are
   intended for use in contexts where the service object is managed externally,
   such as Celery tasks (`..._on_service` suffixed functions).
2. Functions that internally call `get_drive_service()`: These use Flask-Dance
   to get user credentials from the session and are suitable for direct use
   in Flask route handlers.

Error handling for API calls and unexpected issues is included.
"""
import logging
import os
import io # For stream handling
import mimetypes # For guessing file types

# Google API Client libraries
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload # For uploads
# Flask-Dance proxy to access Google token
from flask_dance.contrib.google import google as google_blueprint
# App configuration
from . import config # For GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

logger = logging.getLogger(__name__)

def get_drive_service():
    """
    Builds and returns an authenticated Google Drive API v3 service client.

    Uses OAuth credentials obtained by Flask-Dance from the current user's session.
    This function is intended for use within Flask request contexts.

    Returns:
        googleapiclient.discovery.Resource or None: An initialized Drive service
        object if successful, otherwise None.
    """
    if not google_blueprint.authorized:
        logger.warning("Google account not authorized via Flask-Dance. Cannot get Drive service.")
        return None
    token = google_blueprint.token
    if not token or 'access_token' not in token: # Basic token validation
        logger.error("Invalid or missing Google OAuth token from Flask-Dance session.")
        return None
    try:
        credentials = Credentials(
            token=token['access_token'],
            refresh_token=token.get('refresh_token'), # Refresh token is crucial for long-term access
            token_uri='https://oauth2.googleapis.com/token', # Standard Google token URI
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            scopes=token.get('scope') # Scopes granted during OAuth flow
        )
        # google-auth library automatically handles token refresh if 'credentials.expired' and 'credentials.refresh_token' are set.
        service = build('drive', 'v3', credentials=credentials, static_discovery=False)
        logger.info("Google Drive API service client built successfully for web request context.")
        return service
    except Exception as e:
        logger.error(f"Failed to build Google Drive service for web request: {e}", exc_info=True)
        return None

# --- Functions designed for Celery tasks (accept an initialized service object) ---

def find_folder_id_on_service(drive_service, folder_name, parent_id=None):
    """
    Finds the ID of a folder by its name within a specified parent folder,
    using a pre-initialized Google Drive service object.

    Args:
        drive_service: An initialized Google Drive API service object.
        folder_name (str): The name of the folder to find.
        parent_id (str, optional): The ID of the parent folder. If None, searches
                                   in the user's root Drive folder or accessible shared drives.
    Returns:
        str or None: The folder ID if found, otherwise None.
    """
    if not drive_service:
        logger.error("Drive service object not provided to find_folder_id_on_service.")
        return None
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    # else: query could also be " 'root' in parents " if strictly searching root.
    # If parent_id is None, default API behavior searches all accessible locations if not further restricted.
    try:
        response = drive_service.files().list(
            q=query, spaces='drive', fields='files(id, name)', corpora='user' # corpora='user' for user's Drive
        ).execute()
        folders = response.get('files', [])
        if folders:
            logger.debug(f"Found folder '{folder_name}' (ID: {folders[0]['id']}) on service.")
            return folders[0]['id']
        logger.debug(f"Folder '{folder_name}' not found on service (parent: {parent_id}).")
        return None
    except HttpError as error:
        logger.error(f"API error in find_folder_id_on_service for '{folder_name}': {error}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in find_folder_id_on_service for '{folder_name}': {e}", exc_info=True)
        return None

def find_or_create_folder_on_service(drive_service, folder_name, parent_id=None):
    """
    Finds a folder by name or creates it if not found, using a pre-initialized service.

    Args:
        drive_service: An initialized Google Drive API service object.
        folder_name (str): The name of the folder.
        parent_id (str, optional): The ID of the parent folder. Root if None.

    Returns:
        str or None: The ID of the found or created folder, or None on error.
    """
    if not drive_service:
        logger.error("Drive service object not provided to find_or_create_folder_on_service.")
        return None
    folder_id = find_folder_id_on_service(drive_service, folder_name, parent_id)
    if folder_id:
        return folder_id
    # Not found, so create it
    logger.info(f"Folder '{folder_name}' not found, creating it (parent ID: {parent_id})...")
    file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        file_metadata['parents'] = [parent_id]
    try:
        folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        created_id = folder.get('id')
        logger.info(f"Created folder '{folder_name}' with ID: {created_id} using provided service.")
        return created_id
    except HttpError as error:
        logger.error(f"API error creating folder '{folder_name}' on service: {error}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error creating folder '{folder_name}' on service: {e}", exc_info=True)
        return None

def upload_file_to_drive_on_service(drive_service, file_source, file_name_on_drive, drive_folder_id=None, content_type=None):
    """
    Uploads a file to Google Drive using a pre-initialized service object.

    Args:
        drive_service: An initialized Google Drive API service object.
        file_source (str or io.BytesIO): Path to local file or a bytes stream.
        file_name_on_drive (str): Desired name of the file on Google Drive.
        drive_folder_id (str, optional): ID of the parent folder on Drive. Root if None.
        content_type (str, optional): MIME type. Auto-detected for paths if None. Required for streams.

    Returns:
        dict or None: File metadata (id, name, link, size) if upload is successful, else None.
    """
    if not drive_service:
        logger.error("Drive service object not provided to upload_file_to_drive_on_service.")
        return None
    file_metadata = {'name': file_name_on_drive}
    if drive_folder_id: file_metadata['parents'] = [drive_folder_id]
    media_body = None
    if isinstance(file_source, str): # File path
        if not os.path.exists(file_source):
            logger.error(f"Local file path not found: {file_source}")
            return None
        guessed_content_type, _ = mimetypes.guess_type(file_source)
        final_content_type = content_type or guessed_content_type or 'application/octet-stream'
        media_body = MediaFileUpload(file_source, mimetype=final_content_type, resumable=True)
        logger.debug(f"Preparing to upload file from path: {file_source} as {final_content_type}")
    elif hasattr(file_source, 'read'): # Stream object
        if not content_type:
            logger.error("Content type must be specified for stream uploads.")
            return None
        media_body = MediaIoBaseUpload(file_source, mimetype=content_type, resumable=True)
        logger.debug(f"Preparing to upload file from stream as {content_type}")
    else:
        logger.error(f"Invalid file_source type: {type(file_source)}. Must be path string or stream.")
        return None
    try:
        file_resource = drive_service.files().create(body=file_metadata, media_body=media_body, fields='id, name, webViewLink, size').execute()
        logger.info(f"File '{file_resource.get('name')}' uploaded (ID: {file_resource.get('id')}, Size: {file_resource.get('size')}). Link: {file_resource.get('webViewLink')}")
        return {"id": file_resource.get("id"), "name": file_resource.get("name"), "webViewLink": file_resource.get("webViewLink"), "size": file_resource.get("size")}
    except HttpError as error:
        logger.error(f"API error uploading '{file_name_on_drive}' on service: {error}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error uploading '{file_name_on_drive}' on service: {e}", exc_info=True)
        return None

# --- Functions using Flask-Dance context (for web requests, internally call _on_service versions) ---

def find_folder_id(folder_name, parent_folder_id=None):
    """Finds folder ID. Uses `get_drive_service()` for Flask context."""
    service = get_drive_service()
    return find_folder_id_on_service(service, folder_name, parent_folder_id) if service else None

def create_drive_folder(folder_name, parent_folder_id=None):
    """Finds or creates a folder. Uses `get_drive_service()` for Flask context."""
    service = get_drive_service()
    # Note: This directly calls find_or_create_folder_on_service now
    return find_or_create_folder_on_service(service, folder_name, parent_folder_id) if service else None

def upload_file_to_drive(file_source, file_name_on_drive, drive_folder_id=None, content_type=None):
    """Uploads a file. Uses `get_drive_service()` for Flask context."""
    service = get_drive_service()
    return upload_file_to_drive_on_service(service, file_source, file_name_on_drive, drive_folder_id, content_type) if service else None

def list_drive_items(folder_id=None, item_type=None, page_size=100):
    """
    Lists items in a Drive folder. Uses `get_drive_service()` for Flask context.

    Args:
        folder_id (str, optional): ID of the folder. Root if None.
        item_type (str, optional): 'files', 'folders', or None for all.
        page_size (int): Number of items per page.

    Returns:
        list or None: List of Drive item dicts, or None on error.
    """
    service = get_drive_service()
    if not service: return None
    query_parts = ["trashed=false"]
    if folder_id: query_parts.append(f"'{folder_id}' in parents")
    else: query_parts.append("'root' in parents") # Default to root if no folder_id
    if item_type == 'files': query_parts.append("mimeType != 'application/vnd.google-apps.folder'")
    elif item_type == 'folders': query_parts.append("mimeType = 'application/vnd.google-apps.folder'")
    query = " and ".join(query_parts)
    try:
        results = service.files().list(
            q=query, pageSize=min(page_size, 1000), # Max page size for Drive API is 1000
            fields="nextPageToken, files(id, name, mimeType, createdTime, modifiedTime, webViewLink, size, parents)",
            corpora="user" # Ensure searching user's personal Drive files
        ).execute()
        logger.info(f"Listed {len(results.get('files', []))} items from folder '{folder_id if folder_id else 'root'}' (type: {item_type if item_type else 'all'}).")
        return results.get('files', [])
    except HttpError as error:
        logger.error(f"API error listing items (Flask context) for folder '{folder_id}': {error}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error listing items (Flask context) for folder '{folder_id}': {e}", exc_info=True)
        return None

if __name__ == '__main__':
    # Basic setup for standalone testing (limited without Flask context or real tokens)
    logging.basicConfig(level=logging.DEBUG) # Use DEBUG for more verbose output if needed
    logger.info("Testing drive_client.py (OAuth aspects require running Flask app and valid OAuth tokens)...")
    from dotenv import load_dotenv
    # Assuming .env is in the parent directory of core_logic (i.e., twitter_google_drive_app/.env)
    dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        logger.info(f".env loaded from {dotenv_path}")
    else:
        logger.warning(f".env file not found at {dotenv_path}. Some configurations might be missing for standalone tests.")
    # Reload config to ensure .env variables are picked up if module was imported before load_dotenv in some context
    import importlib
    importlib.reload(config)
    logger.info("drive_client.py standalone checks completed. For full tests, use pytest and run the Flask application.")
