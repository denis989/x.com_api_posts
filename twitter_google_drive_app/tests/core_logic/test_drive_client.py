import pytest
from unittest.mock import MagicMock, patch
from core_logic import drive_client # Assuming drive_client.py is in core_logic
import io

@pytest.fixture
def mock_drive_service(mocker): # Added mocker
    service = MagicMock()
    # Mock the .files() resource, which then has methods like list(), create(), etc.
    # Each of these methods returns a request object, which then has an .execute() method.

    # Standard structure for files().<method>().execute()
    # We can make this more specific per test if needed.
    mock_files_resource = MagicMock()
    service.files.return_value = mock_files_resource

    # execute_result = MagicMock() # General execute result
    # mock_list_request = MagicMock()
    # mock_list_request.execute.return_value = execute_result
    # mock_files_resource.list.return_value = mock_list_request

    # mock_create_request = MagicMock()
    # mock_create_request.execute.return_value = execute_result
    # mock_files_resource.create.return_value = mock_create_request

    return service

def test_find_folder_id_on_service_found(mock_drive_service):
    # Specific mock setup for this test
    mock_list_execute_result = {'files': [{'id': 'folder123', 'name': 'Test Folder'}]}
    mock_drive_service.files().list().execute.return_value = mock_list_execute_result

    folder_id = drive_client.find_folder_id_on_service(mock_drive_service, "Test Folder", parent_id="parent999")

    # Check that files().list was called with the correct parameters
    mock_drive_service.files().list.assert_called_once_with(
        q="mimeType='application/vnd.google-apps.folder' and name='Test Folder' and trashed=false and 'parent999' in parents",
        spaces='drive',
        fields='files(id, name)',
        corpora='user' # Added corpora as it's used in implementation
        # pageToken=None is implicitly correct if not specified in the call within the function
    )
    assert folder_id == 'folder123'

def test_find_folder_id_on_service_not_found(mock_drive_service):
    mock_list_execute_result = {'files': []} # No files found
    mock_drive_service.files().list().execute.return_value = mock_list_execute_result

    folder_id = drive_client.find_folder_id_on_service(mock_drive_service, "NonExistent Folder")

    mock_drive_service.files().list.assert_called_once_with(
        q="mimeType='application/vnd.google-apps.folder' and name='NonExistent Folder' and trashed=false",
        spaces='drive',
        fields='files(id, name)',
        corpora='user'
    )
    assert folder_id is None

def test_create_drive_folder_on_service(mock_drive_service):
    # This function is find_or_create_folder_on_service in the latest drive_client.py
    # Test find_or_create_folder_on_service: case where folder does not exist

    # First call to find_folder_id_on_service (within find_or_create...) returns None
    mock_drive_service.files().list().execute.return_value = {'files': []}

    # Mock the create call
    mock_create_execute_result = {'id': 'newfolder456'}
    mock_drive_service.files().create().execute.return_value = mock_create_execute_result

    # Test find_or_create_folder_on_service
    folder_id = drive_client.find_or_create_folder_on_service(mock_drive_service, "New Folder", parent_id="parent123")

    expected_body_for_create = {
        'name': "New Folder",
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': ['parent123']
    }
    # Check the create call
    mock_drive_service.files().create.assert_called_once_with(body=expected_body_for_create, fields='id')
    assert folder_id == 'newfolder456'
    # find_folder_id_on_service (via list) was called once before create
    assert mock_drive_service.files().list.call_count == 1


def test_find_or_create_folder_on_service_existing(mock_drive_service):
    # Test find_or_create_folder_on_service: case where folder already exists
    mock_drive_service.files().list().execute.return_value = {'files': [{'id': 'existingfolder789', 'name': 'Existing Folder'}]}

    folder_id = drive_client.find_or_create_folder_on_service(mock_drive_service, "Existing Folder", parent_id="parentABC")

    # Check that list was called (for the find part)
    mock_drive_service.files().list.assert_called_once_with(
        q="mimeType='application/vnd.google-apps.folder' and name='Existing Folder' and trashed=false and 'parentABC' in parents",
        spaces='drive', fields='files(id, name)', corpora='user'
    )
    # Check that create was NOT called
    mock_drive_service.files().create.assert_not_called()
    assert folder_id == 'existingfolder789'


@patch('core_logic.drive_client.MediaIoBaseUpload', return_value=MagicMock()) # Mock the MediaIoBaseUpload class
@patch('os.path.exists', return_value=True) # Mock os.path.exists for file path checks
@patch('mimetypes.guess_type', return_value=('application/json', None)) # Mock mimetype guessing
def test_upload_file_to_drive_on_service_from_stream(mock_guess_type, mock_os_exists, mock_media_io_upload, mock_drive_service):
    mock_upload_result = {'id': 'fileABC', 'name': 'test_stream.json', 'webViewLink': 'http://example.com/fileABC', 'size': '1024'}
    mock_drive_service.files().create().execute.return_value = mock_upload_result

    dummy_content = b'{"key": "value"}'
    file_stream = io.BytesIO(dummy_content)

    result = drive_client.upload_file_to_drive_on_service(
        drive_service=mock_drive_service,
        file_source=file_stream,
        file_name_on_drive="test_stream.json",
        drive_folder_id="folderXYZ",
        content_type="application/json" # Explicitly provide for streams
    )

    expected_file_metadata = {'name': "test_stream.json", 'parents': ["folderXYZ"]}
    # Check that files().create was called
    # The media_body arg will be the instance of the mocked MediaIoBaseUpload
    mock_drive_service.files().create.assert_called_once()
    call_args = mock_drive_service.files().create.call_args
    assert call_args[1]['body'] == expected_file_metadata
    assert call_args[1]['fields'] == 'id, name, webViewLink, size'
    # Check that MediaIoBaseUpload was instantiated correctly
    mock_media_io_upload.assert_called_once_with(file_stream, mimetype="application/json", resumable=True)

    assert result is not None
    assert result['id'] == 'fileABC'
    assert result['name'] == 'test_stream.json'

# Similar test for upload_file_to_drive_on_service_from_path can be added
# It would patch MediaFileUpload instead of MediaIoBaseUpload
# from unittest.mock import mock_open - can be useful for path based uploads too
