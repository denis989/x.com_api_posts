import pytest
from unittest.mock import MagicMock, patch
from core_logic import twitter_client, config # Assuming twitter_client.py is in core_logic
from datetime import datetime, timezone

@pytest.fixture
def mock_tweepy_client(mocker): # Added mocker for potential patching within fixture if needed
    client = MagicMock(spec=tweepy.Client) # Use spec for more accurate mocking
    # Mock specific methods as needed for tests, e.g., for get_me to test client validity
    mock_user_response = MagicMock()
    mock_user_data = MagicMock()
    mock_user_data.id = "12345"
    mock_user_data.username = "TestUser"
    mock_user_data.name = "Test User Name"
    mock_user_response.data = mock_user_data
    client.get_me.return_value = mock_user_response
    return client

# Test for the existing build_full_search_query_fn in twitter_client.py
def test_build_full_search_query_fn():
    # query_template, actor_screen_name, other_params=None
    assert twitter_client.build_full_search_query_fn("from:{} OR @{}", "user1", "keyword") == "from:user1 OR @user1 keyword"
    assert twitter_client.build_full_search_query_fn("from:{}", "user2", "another keyword") == "from:user2 another keyword"
    assert twitter_client.build_full_search_query_fn("{}", "user3", None) == "user3" # No other_params
    assert twitter_client.build_full_search_query_fn("{}", "user4") == "user4" # Default other_params is None

def test_get_single_task_estimate_recent(mock_tweepy_client):
    mock_response = MagicMock()
    mock_response.meta = {'total_tweet_count': 123}
    mock_response.data = [{'tweet_count': 50, 'start': '2023-01-01T00:00:00Z', 'end': '2023-01-01T23:59:59Z'}, {'tweet_count': 73, 'start': '...', 'end': '...'}]
    mock_response.errors = [] # Assuming no errors for success case
    mock_tweepy_client.get_recent_tweets_count.return_value = mock_response

    # Using timezone-aware datetimes as good practice, assuming API functions handle them
    start_dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2023, 1, 2, tzinfo=timezone.utc)

    result = twitter_client.get_single_task_estimate(mock_tweepy_client, "testquery", start_dt, end_dt, granularity="day")

    mock_tweepy_client.get_recent_tweets_count.assert_called_once()
    # Example of checking arguments (be specific with ISO format if that's what the function does)
    # call_args = mock_tweepy_client.get_recent_tweets_count.call_args
    # assert call_args[1]['query'] == "testquery"
    # assert call_args[1]['start_time'] == start_dt.isoformat() # Or with 'Z' if added by function

    assert result['status'] == "success"
    assert result['estimated_count'] == 123
    assert result['data_breakdown'][0]['tweet_count'] == 50
    assert result['query'] == "testquery"

def test_fetch_tweets_for_task_recent(mock_tweepy_client, mocker):
    mock_paginator_instance = MagicMock()

    # Page 1 data
    mock_tweet1_data = {"id": "1", "text": "tweet1", "author_id": "101", "created_at": "2023-01-01T10:00:00Z"}
    mock_user1_data = {"id": "101", "name": "User1", "username": "user1_username"}
    mock_media1_data = {"media_key": "3_1", "type": "photo"}

    mock_response_page1 = MagicMock()
    mock_response_page1.data = [MagicMock(data=mock_tweet1_data)] # Simulate Tweet object with .data
    mock_response_page1.includes = {"users": [MagicMock(data=mock_user1_data)], "media": [MagicMock(data=mock_media1_data)]}
    mock_response_page1.meta = {"result_count": 1, "next_token": "nexttoken123"}

    # Page 2 data (no more tweets)
    mock_response_page2 = MagicMock()
    mock_response_page2.data = None # No more tweets
    mock_response_page2.includes = {}
    mock_response_page2.meta = {"result_count": 0}

    # Configure the Paginator mock to return an iterable (list of response pages)
    mock_paginator_instance.__iter__.return_value = [mock_response_page1, mock_response_page2]

    # Patch tweepy.Paginator to return our mock_paginator_instance
    mocker.patch('tweepy.Paginator', return_value=mock_paginator_instance)

    start_dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2023, 1, 2, tzinfo=timezone.utc)

    result = twitter_client.fetch_tweets_for_task(
        mock_tweepy_client, "testquery", start_dt, end_dt,
        config.TWEET_FIELDS_COMPREHENSIVE, config.EXPANSIONS_COMPREHENSIVE,
        config.USER_FIELDS_COMPREHENSIVE, config.MEDIA_FIELDS_COMPREHENSIVE,
        config.POLL_FIELDS_COMPREHENSIVE, config.PLACE_FIELDS_COMPREHENSIVE,
        max_tweets_to_fetch_for_this_task=5
    )

    assert not result.get("error")
    assert result["status"] == "success"
    assert len(result["tweets_data"]) == 1
    assert result["tweets_data"][0]["text"] == "tweet1"
    assert "users" in result["includes_users"] # Corrected key based on fetch_tweets_for_task structure
    assert result["includes_users"][0]["name"] == "User1"
    assert "media" in result["includes_media"]
    assert result["includes_media"][0]["type"] == "photo"

    # Check that tweepy.Paginator was called correctly
    # This requires knowing the exact call signature used by fetch_tweets_for_task
    # For example:
    tweepy.Paginator.assert_called_once_with(
        mock_tweepy_client.search_recent_tweets, # or search_all_tweets based on logic in func
        query="testquery",
        start_time=start_dt.isoformat(), # Or with "Z" depending on internal formatting
        end_time=end_dt.isoformat(),
        tweet_fields=config.TWEET_FIELDS_COMPREHENSIVE,
        expansions=config.EXPANSIONS_COMPREHENSIVE,
        user_fields=config.USER_FIELDS_COMPREHENSIVE,
        media_fields=config.MEDIA_FIELDS_COMPREHENSIVE,
        poll_fields=config.POLL_FIELDS_COMPREHENSIVE,
        place_fields=config.PLACE_FIELDS_COMPREHENSIVE,
        max_results=5 # Or min(5, 100) as per function logic
    )
    # Check if the client's search method was called by the paginator (more complex to assert directly)
    # mock_tweepy_client.search_recent_tweets.assert_called() # Or search_all_tweets
