from celery import Celery
# Assuming core_logic.config can be imported from the directory where celery worker is started.
# This might require adjusting PYTHONPATH if worker is started from project root.
# Or, ensure celery_app_setup.py is in a place where core_logic is directly importable.
# For now, assume it's run from a context where 'core_logic' is in sys.path.
# One common way is to have celery_app_setup.py in the same dir as app.py,
# and tasks.py also there or in a subdirectory.
# If celery worker is started from `twitter_google_drive_app/` directory:
from core_logic.config import CELERY_BROKER_URL, CELERY_RESULT_BACKEND
import os

# Detect if running inside a Celery worker
# RUNNING_IN_CELERY_WORKER = os.getenv('CELERY_WORKER_RUNNING') == 'true'

celery_app = Celery(
    'twitter_google_drive_app', # Can be same as Flask app name or a dedicated task app name
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=['tasks'] # List of modules where tasks are defined (e.g., 'tasks.py')
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],  # Ensure Celery can handle JSON task arguments
    result_serializer='json',
    timezone='UTC', # Recommended to use UTC for Celery
    enable_utc=True,
    # Optional: improve task state reporting
    task_track_started=True,
    # task_send_sent_event=True, # If using Flower or other event monitors
)

# If you need Flask app context in your tasks (e.g., for Flask-Dance session or config)
# This is a common pattern but can be complex.
# For the current design, we pass tokens directly, avoiding Flask context in task.
# class FlaskTask(celery_app.Task):
#     def __call__(self, *args, **kwargs):
#         from app import app as flask_app # Import your Flask app instance
#         with flask_app.app_context():
#             return super().__call__(*args, **kwargs)
# celery_app.Task = FlaskTask # Set this as the default Task class

if __name__ == '__main__':
    # This script can be used to start a worker directly (though `celery -A ...` is more common)
    # For worker: celery -A celery_app_setup.celery_app worker -l info
    # For beat (scheduler): celery -A celery_app_setup.celery_app beat -l info
    # Set environment variable for worker detection if needed for some specific logic:
    # os.environ['CELERY_WORKER_RUNNING'] = 'true'
    argv = [
        'worker',
        '--loglevel=INFO', # Standard Celery worker arguments
    ]
    celery_app.worker_main(argv)
