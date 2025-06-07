#!/bin/bash
# This script is an example for running the application locally with Gunicorn,
# similar to how it might run in a container.
# For Google Cloud Run, the CMD instruction in the Dockerfile is typically used directly.

# Default port if not set
PORT=${PORT:-8080}

echo "Starting Gunicorn on port $PORT"
# Ensure app.py is in the current directory or adjust path to app:app
# Make sure your virtual environment is NOT active if you are building/running inside Docker.
# This script assumes it's run in an environment where dependencies are installed globally
# or in a specified Python path (e.g., after `pip install -r requirements.txt` system-wide or in a base Docker image).
# For local dev with venv, you'd typically activate venv then run gunicorn.
gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 app:app
