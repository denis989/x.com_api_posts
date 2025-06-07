import pytest
from unittest.mock import MagicMock, patch
# If tasks.py is in the root of twitter_google_drive_app, and tests are run from there too:
import tasks
from core_logic import config as core_config # For field lists, renamed to avoid conflict
from datetime import datetime, timezone
import io # For mocking stream

@pytest.fixture
def mock_celery_task_self(mocker): # Renamed from prompt's mock_celery_task_self to avoid conflict
    task_self = MagicMock()
    task_self.update_state = MagicMock()
    task_self.request = MagicMock() # Celery tasks have a request attribute
    task_self.request.id = "test_task_id_123" # Example task ID
    return task_self

# Patch the helper client reconstruction functions within tasks.py
@patch('tasks.get_twitter_client_for_task')
@patch('tasks.get_drive_service_for_task')
# Patch the direct client methods from core_logic that are used by the task
@patch('core_logic.twitter_client.fetch_tweets_for_task')
@patch('core_logic.drive_client.find_or_create_folder_on_service')
@patch('core_logic.drive_client.upload_file_to_drive_on_service')
@patch('core_logic.utils.get_fimi_slug') # Mock utility function
@patch('core_logic.utils.sanitize_filename') # Mock utility function
def test_download_tweets_task_success(
    mock_sanitize_filename, mock_get_fimi_slug,
    mock_upload_drive, mock_find_create_folder, mock_fetch_tweets,
    mock_get_drive_svc, mock_get_twitter_cli, # Patched helpers from tasks.py
    mock_celery_task_self_fixture, # Fixture for 'self' (renamed)
    mocker # Pytest-mock fixture
):
    # --- Setup Mocks ---
    mock_twitter_client_instance = MagicMock(spec=tweepy.Client) # Use spec
    mock_drive_service_instance = MagicMock() # spec=googleapiclient.discovery.Resource could be used

    mock_get_twitter_cli.return_value = mock_twitter_client_instance
    mock_get_drive_svc.return_value = mock_drive_service_instance

    # Mock return values for Drive folder creation
    # Order: event_folder, target_item_folder (account/query)
    mock_find_create_folder.side_effect = ['event_folder_id_1', 'target_item_folder_id_1']

    # Mock return value for sanitize_filename and get_fimi_slug
    mock_sanitize_filename.side_effect = lambda x: x # Simple pass-through for testing
    mock_get_fimi_slug.return_value = "FIMI_slug_example"


    mock_fetched_tweet_data = {
        "query": "from:testuser testquery", # Match one of the possible constructed queries
        "status": "success",
        "tweets_data": [{"id": "t1", "text": "Test Tweet", "created_at": "2023-01-01T12:00:00Z"}],
        "includes_media": [], "includes_users": [{"id":"u1", "name":"Test User"}],
        "includes_polls": [], "includes_places": [],
        "meta": {"total_collected": 1}
    }
    mock_fetch_tweets.return_value = mock_fetched_tweet_data

    mock_upload_drive.return_value = {"id": "drive_file_123", "name": "FIMI_slug_example.json"}

    # --- Task Parameters ---
    user_twitter_token = {"oauth_token": "test_tw_token", "oauth_token_secret": "test_tw_secret"}
    user_google_token = {"access_token": "test_gg_token", "refresh_token": "test_gg_refresh", "scope": ["drive.file"]}
    download_params = {
        "accounts": ["testuser"],
        "queries": ["testquery"], # Task logic might combine these
        "start_date": "2023-01-01T00:00:00", # ISO format as task expects
        "end_date": "2023-01-02T00:00:00",
        "FIMI_Event": "TestEventName",
        "download_limit_per_task": 10
    }

    # --- Call the task function directly ---
    # The first argument to a bound Celery task is 'self'
    result = tasks.download_tweets_task(
        mock_celery_task_self_fixture,
        user_twitter_token,
        user_google_token,
        download_params
    )

    # --- Assertions ---
    assert result['status'] == 'SUCCESS'
    assert result['tweets_downloaded'] == 1
    assert result['drive_file_id'] == 'drive_file_123'
    assert result['file_name'] == "FIMI_slug_example.json"

    mock_get_twitter_cli.assert_called_once_with(user_twitter_token)
    mock_get_drive_svc.assert_called_once_with(user_google_token)

    # Check Drive folder creation calls (Event folder, then Target Item folder)
    assert mock_find_create_folder.call_count == 2
    mock_find_create_folder.assert_any_call(mock_drive_service_instance, "TestEventName", parent_id=None)
    mock_find_create_folder.assert_any_call(mock_drive_service_instance, "testuser", parent_id='event_folder_id_1')

    # Check that fetch_tweets_for_task was called
    mock_fetch_tweets.assert_called_once()
    fetch_call_args = mock_fetch_tweets.call_args[1] # Get kwargs
    assert fetch_call_args['api_query'] == "from:testuser testquery" # Based on task's current logic
    assert fetch_call_args['max_tweets_to_fetch_for_this_task'] == 10

    # Check that upload_file_to_drive_on_service was called
    mock_upload_drive.assert_called_once()
    upload_call_args = mock_upload_drive.call_args[1]
    assert upload_call_args['drive_service'] == mock_drive_service_instance
    assert upload_call_args['file_name_on_drive'] == "FIMI_slug_example.json"
    assert upload_call_args['drive_folder_id'] == 'target_item_folder_id_1'
    assert isinstance(upload_call_args['file_source'], io.BytesIO) # Check it's a stream
    assert upload_call_args['content_type'] == 'application/json'

    # Check Celery state updates
    mock_celery_task_self_fixture.update_state.assert_any_call(state='STARTED', meta={'status': 'Initializing clients...', 'params': download_params})
    # Add more specific update_state checks if needed for PROGRESS states
    mock_celery_task_self_fixture.update_state.assert_any_call(state='PROGRESS', meta={'status': 'Fetched 1 tweets. Saving to Drive...'})


# Add more tests for failure cases, different parameter combinations, etc.
# For example, test_download_tweets_task_no_tweets_found
# test_download_tweets_task_twitter_client_fails
# test_download_tweets_task_drive_service_fails
# test_download_tweets_task_fetch_tweets_error
# test_download_tweets_task_drive_upload_error
# test_download_tweets_task_folder_creation_error
# test_download_tweets_task_invalid_params (e.g. no account and no query)
# test_download_tweets_task_date_parse_error (though this might be better in endpoint test)

# Example of a failure case test (Twitter client init fails)
@patch('tasks.get_twitter_client_for_task', return_value=None) # Mock it to return None
@patch('tasks.get_drive_service_for_task') # This still needs to be patched
def test_download_tweets_task_twitter_fails(mock_get_drive, mock_get_twitter, mock_celery_task_self_fixture):
    user_twitter_token = {"oauth_token": "test", "oauth_token_secret": "test"}
    user_google_token = {"access_token": "test"}
    download_params = {
        "accounts": ["testuser"], "queries": ["testquery"],
        "start_date": "2023-01-01T00:00:00", "end_date": "2023-01-02T00:00:00",
        "FIMI_Event": "Test Event", "download_limit_per_task": 10
    }
    with pytest.raises(Exception, match="Twitter client initialization failed"):
        tasks.download_tweets_task(
            mock_celery_task_self_fixture,
            user_twitter_token, user_google_token, download_params
        )
    mock_get_twitter.assert_called_once_with(user_twitter_token)
    # Ensure drive service init is not called if twitter fails first (or is, depending on actual logic)
    # mock_get_drive.assert_not_called() # If sequential and twitter is first
    # Check that update_state was called for STARTED, but not for later stages
    mock_celery_task_self_fixture.update_state.assert_called_once_with(state='STARTED', meta={'status': 'Initializing clients...', 'params': download_params})
