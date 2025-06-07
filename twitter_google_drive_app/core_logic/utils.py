import re
import logging
import json
import os
from datetime import datetime

# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def sanitize_filename(filename):
    """Sanitizes a string to be a valid filename."""
    # Remove invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing whitespace and dots
    filename = filename.strip(' .')
    # Replace consecutive underscores with a single underscore
    filename = re.sub(r'__+', '_', filename)
    # Limit length (optional, but good practice)
    # max_len = 200
    # if len(filename) > max_len:
    #     name, ext = os.path.splitext(filename)
    #     filename = name[:max_len - len(ext) - 1] + ext
    if not filename: # ensure filename is not empty after sanitization
        filename = "untitled"
    return filename

def get_fimi_slug(actor_screen_name, search_type, start_time_dt, end_time_dt):
    """Generates a FIMI-style slug for filenames or directories."""
    # Format datetime objects to strings
    start_str = start_time_dt.strftime('%Y%m%d%H%M%S')
    end_str = end_time_dt.strftime('%Y%m%d%H%M%S')
    return f"FIMI_{actor_screen_name}_{search_type}_{start_str}_{end_str}"

# Placeholder for log_operation_fn - will need significant adaptation
# The original function likely interacted with notebook UI and specific Drive paths.
# For a web app, logging will go to console/files, and Drive interaction
# will be through the drive_client module.
def log_operation_fn(log_entry,
                     log_type="GENERIC_LOG",
                     # config=None, # Original parameter, might be needed
                     # log_filename_prefix_override=None, # Original parameter
                     # target_dir_override=None, # Original parameter
                     # also_print=True # Original parameter
                    ):
    """
    Logs an operation. Adapted for generic Python logging.
    Actual file writing to Drive will be handled by drive_client.
    """
    logging.info(f"[{log_type}] {log_entry}")
    # In a full web app, this might also write to a database or a more structured log file.
    # The original function's complexity with JSON logs and Drive uploads
    # will be split: this part is just for general logging.
    # write_log_json will handle the JSON part, and drive_client the upload.
    pass


def write_log_json(data, filename, directory):
    """
    Writes data to a JSON file in the specified directory.
    In the web app context, 'directory' might be a temporary local path
    before uploading to Google Drive.
    """
    if not os.path.exists(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as e:
            logging.error(f"Error creating directory {directory}: {e}")
            return False

    filepath = os.path.join(directory, sanitize_filename(filename) + ".json")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.info(f"Successfully wrote JSON log to {filepath}")
        return True
    except IOError as e:
        logging.error(f"Error writing JSON log to {filepath}: {e}")
        return False
    except Exception as e:
        logging.error(f"An unexpected error occurred in write_log_json: {e}")
        return False

# Other utility functions from the notebook can be added here.
# For example, if there are functions for date manipulation,
# data cleaning (beyond sanitize_filename), etc.

if __name__ == '__main__':
    # Example Usage (for testing purposes)
    logging.info("Testing utility functions...")

    # Sanitize filename
    test_fn = "test:file/name\\with|bad*chars?.txt"
    sanitized = sanitize_filename(test_fn)
    logging.info(f"Original: '{test_fn}', Sanitized: '{sanitized}'")
    assert sanitized == "test_file_name_with_bad_chars_.txt"

    test_fn_empty = ":"
    sanitized_empty = sanitize_filename(test_fn_empty)
    logging.info(f"Original: '{test_fn_empty}', Sanitized: '{sanitized_empty}'")
    assert sanitized_empty == "_"


    # FIMI slug
    actor = "testuser"
    search = "timeline"
    start_dt = datetime(2023, 1, 1, 12, 0, 0)
    end_dt = datetime(2023, 1, 2, 12, 0, 0)
    slug = get_fimi_slug(actor, search, start_dt, end_dt)
    logging.info(f"FIMI Slug: {slug}")
    expected_slug = "FIMI_testuser_timeline_20230101120000_20230102120000"
    assert slug == expected_slug

    # Log operation
    log_operation_fn("This is a test log entry.", log_type="TEST_LOG")

    # Write JSON log (example)
    script_dir = os.path.dirname(__file__) # current dir of utils.py
    temp_log_dir = os.path.join(script_dir, "..", "..", "temp_logs") # e.g., twitter_google_drive_app/temp_logs

    # Ensure temp_log_dir is an absolute path if needed, or adjust relative path
    # For simplicity here, using it as is, assuming it's okay for testing.

    # Create a dummy temp_log_dir for testing if it doesn't exist
    # In a real app, this path would be more robustly defined.
    os.makedirs(temp_log_dir, exist_ok=True)

    log_data = {"user": "test_user", "action": "test_action", "timestamp": datetime.now().isoformat()}
    success = write_log_json(log_data, "test_log_file", temp_log_dir)
    logging.info(f"JSON log write successful: {success}")
    if success:
        assert os.path.exists(os.path.join(temp_log_dir, "test_log_file.json"))
        # Clean up dummy file
        # os.remove(os.path.join(temp_log_dir, "test_log_file.json")) # Commented out for inspection

    logging.info("Utility functions test complete.")
