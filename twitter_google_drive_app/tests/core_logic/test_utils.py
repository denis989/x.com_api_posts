import pytest
from core_logic import utils # Assuming utils.py is in core_logic
from datetime import datetime

def test_sanitize_filename():
    assert utils.sanitize_filename("Test File Name!@#$") == "Test_File_Name_" # Original ended with non-alphanum
    assert utils.sanitize_filename("  leading spaces ok ") == "leading_spaces_ok"
    assert utils.sanitize_filename("Test-With-Hyphens") == "Test_With_Hyphens" # Hyphens are valid
    assert utils.sanitize_filename("file/with/slashes") == "file_with_slashes"
    assert utils.sanitize_filename("test:file*name?") == "test_file_name_"
    assert utils.sanitize_filename("") == "untitled" # Default for empty
    # Tests for max_length (assuming sanitize_filename will be updated to support it)
    # For now, these might fail or need sanitize_filename to be updated.
    # assert utils.sanitize_filename("A very long filename that needs truncation", max_length=20) == "A_very_long_filename"
    # assert utils.sanitize_filename("Short", max_length=20) == "Short"
    # assert utils.sanitize_filename("", max_length=10) == "untitled" # current behavior for empty

def test_get_fimi_slug():
    # Using the compatible tests for the existing get_fimi_slug function
    actor = "testuser"
    search = "timeline"
    start_dt = datetime(2023, 1, 1, 12, 0, 0)
    end_dt = datetime(2023, 1, 2, 12, 0, 0)
    expected_slug = "FIMI_testuser_timeline_20230101120000_20230102120000"
    assert utils.get_fimi_slug(actor, search, start_dt, end_dt) == expected_slug

    actor2 = "another_user"
    search2 = "search"
    start_dt2 = datetime(2024, 3, 15, 9, 30, 15)
    end_dt2 = datetime(2024, 3, 15, 10, 30, 15)
    expected_slug2 = "FIMI_another_user_search_20240315093015_20240315103015"
    assert utils.get_fimi_slug(actor2, search2, start_dt2, end_dt2) == expected_slug2
