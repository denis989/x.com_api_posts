# Twitter Data Downloader to Google Drive

This web application allows users to authenticate with their Twitter and Google Drive accounts to download tweets based on specified criteria and save them directly to their Google Drive. It features asynchronous task processing for downloads.

## Features

*   OAuth 2.0 Authentication with Twitter (v1.1a for user context, app can be configured for v2 bearer) and Google.
*   Estimate tweet counts before downloading.
*   Asynchronous downloading of tweets using Celery and Redis.
*   Save tweet data (including metadata and expansions) as JSON files to Google Drive.
*   Dynamic folder creation on Google Drive based on event, account, and query.
*   Basic UI for inputting parameters and monitoring task status (UI part is conceptual for backend focused tasks).
*   Configuration via environment variables (`.env` file).
*   Unit tests using pytest.

## Prerequisites

*   Python 3.8+
*   Pip (Python package installer)
*   Redis Server (running locally or accessible via URL for Celery)
*   Docker (for containerized deployment and local testing)
*   A Twitter Developer Account:
    *   Create an app on the [Twitter Developer Portal](https://developer.twitter.com/).
    *   Obtain your API Key (Client ID) and API Key Secret (Client Secret).
    *   Ensure your app has the necessary permissions (e.g., to read tweets, user profiles).
    *   Configure the Callback URI / Redirect URL for your Twitter app (e.g., `http://localhost:5000/auth/twitter/authorized` for local development).
*   A Google Cloud Platform Project:
    *   Enable the Google Drive API.
    *   Create OAuth 2.0 credentials (Client ID and Client Secret) from the [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
    *   Ensure the Authorized redirect URIs for your Google OAuth client include `http://localhost:5000/auth/google/authorized` (for local development).

## Setup Instructions

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd twitter_google_drive_app
    # Note: If the repo was cloned with a different name, cd into that name.
    # The 'twitter_google_drive_app' used here assumes it's the root of the application code.
    ```

2.  **Create a Python Virtual Environment (Recommended for local development without Docker):**
    (From within the `twitter_google_drive_app` directory or your project's root)
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies (if not using Docker for local dev):**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set Up Environment Variables:**
    *   Copy the example environment file:
        ```bash
        cp .env.example .env
        ```
    *   Edit the `.env` file and fill in your actual API keys and secrets obtained from Twitter and Google Cloud, your Flask secret key, and Redis URLs if different from default.
        *   `FLASK_SECRET_KEY`: A long, random string for Flask session security.
        *   `TWITTER_CLIENT_ID`, `TWITTER_CLIENT_SECRET`: Your Twitter app's API Key and Secret.
        *   `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: Your Google OAuth 2.0 Client ID and Secret.
        *   `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`: URLs for your Redis server.

5.  **Run the Flask Web Application (without Docker):**
    (Ensure your virtual environment is activated and Redis is running)
    ```bash
    # From the 'twitter_google_drive_app' directory (or wherever app.py is)
    flask run
    # Or: python app.py
    ```
    The application should be accessible at `http://localhost:5000`.

6.  **Run the Celery Worker (without Docker):**
    *   Open a new terminal window.
    *   Navigate to the `twitter_google_drive_app` directory.
    *   Activate the virtual environment: `source venv/bin/activate`.
    *   Start the Celery worker:
        ```bash
        celery -A celery_app_setup.celery_app worker -l info
        ```
    *   Ensure your Redis server is running before starting the Celery worker.

## Usage

1.  **Access the Application:** Open your web browser and go to `http://localhost:5000` (if running locally/via Docker locally).
2.  **Authentication:**
    *   Click "Login with Twitter" and authorize the application.
    *   Click "Login with Google" and authorize the application (ensure you grant Google Drive permissions).
3.  **Estimate Tweets:**
    *   Use a tool like Postman or curl to send a POST request to `http://localhost:5000/twitter/estimate`.
    *   JSON Body Example:
        ```json
        {
            "accounts": ["twitterdev"],
            "queries": ["#apitesting"],
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD"
        }
        ```
    *   The estimated counts will be returned as JSON.
4.  **Download Tweets:**
    *   Send a POST request to `http://localhost:5000/twitter/download`.
    *   JSON Body Example:
        ```json
        {
            "accounts": ["twitterdev"],
            "queries": ["#Python"],
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
            "FIMI_Event": "MyPythonDownloads",
            "download_limit_per_task": 50
        }
        ```
    *   A task ID will be returned.
5.  **Check Download Status:**
    *   Send a GET request to `http://localhost:5000/task_status/<your_task_id>`.
    *   The response will show the task's current status and any results or errors.
6.  **View Files on Google Drive:** Once a download task is complete (status: SUCCESS), check your Google Drive. Files will be organized under a folder named after your `FIMI_Event`, then by account/query.

## Running Tests

To run the unit tests (ensure pytest is installed from `requirements.txt`):
```bash
# From the 'twitter_google_drive_app' directory
pytest
```

## Project Structure (Overview)

- `app.py`: Main Flask application file (routes, OAuth setup).
- `celery_app_setup.py`: Celery application initialization.
- `tasks.py`: Celery task definitions (e.g., `download_tweets_task`).
- `Dockerfile`: For building the application container image.
- `run.sh`: Optional script for local Gunicorn execution.
- `.env`: Environment variables (secret keys, API credentials - **DO NOT COMMIT**).
- `.env.example`: Template for environment variables.
- `.gitignore`: Specifies intentionally untracked files that Git should ignore.
- `requirements.txt`: Python dependencies.
- `core_logic/`: Contains the core business logic.
  - `config.py`: Application configuration, loads from `.env`.
  - `twitter_client.py`: Functions for interacting with the Twitter API.
  - `drive_client.py`: Functions for interacting with the Google Drive API.
  - `utils.py`: Utility functions.
- `static/`: Static files (CSS, JavaScript - if any frontend is added).
- `templates/`: HTML templates (currently minimal, for Flask-Dance redirects).
- `tests/`: Unit tests.

## Deployment

### Containerization (Docker)

A `Dockerfile` is provided to build a container image for the application. This is suitable for deployment to container platforms like Google Cloud Run, Kubernetes, or Docker Hub.

**Building the Docker Image (Example):**
(Ensure you are in the `twitter_google_drive_app` directory where the Dockerfile is located)
```bash
docker build -t twitter-google-drive-app .
```

**Running the Docker Container Locally (Example):**
*   Make sure your `.env` file is prepared with your credentials in the `twitter_google_drive_app` directory.
*   You can pass the environment variables from your `.env` file to the container:
    ```bash
    # Ensure your Redis server is accessible from Docker (e.g., not just on localhost if Docker uses a different network)
    # For Linux, `host.docker.internal` might not work; use your machine's actual IP for Redis if it's running on host.
    # Or, run Redis in a Docker container and connect them via a Docker network.
    docker run -p 8080:8080 --env-file .env twitter-google-drive-app
    ```
The application will be accessible at `http://localhost:8080`. The `PORT` environment variable inside the container will be set to `8080` by the Dockerfile, and Gunicorn will bind to this port.

**Deploying to Google Cloud Run:**
1.  **Build and Push Image:**
    *   Ensure you have `gcloud` CLI installed and configured.
    *   Enable Artifact Registry API in your Google Cloud project.
    *   Create an Artifact Registry repository (e.g., `my-app-repo`).
    *   Authenticate Docker to push to Artifact Registry:
        ```bash
        gcloud auth configure-docker YOUR_REGION-docker.pkg.dev
        # Example: gcloud auth configure-docker us-central1-docker.pkg.dev
        ```
    *   Build and tag your image:
        ```bash
        # Replace YOUR_GOOGLE_CLOUD_PROJECT_ID, YOUR_REGION, and my-app-repo accordingly
        docker build -t YOUR_REGION-docker.pkg.dev/YOUR_GOOGLE_CLOUD_PROJECT_ID/my-app-repo/twitter-app:latest .
        ```
    *   Push the image:
        ```bash
        docker push YOUR_REGION-docker.pkg.dev/YOUR_GOOGLE_CLOUD_PROJECT_ID/my-app-repo/twitter-app:latest
        ```

2.  **Deploy to Cloud Run (Flask App):**
    *   Deploy the image to Cloud Run using the Google Cloud Console or `gcloud` CLI.
    *   Example using `gcloud`:
        ```bash
        gcloud run deploy twitter-flask-app \
            --image YOUR_REGION-docker.pkg.dev/YOUR_GOOGLE_CLOUD_PROJECT_ID/my-app-repo/twitter-app:latest \
            --platform managed \
            --region YOUR_CLOUD_RUN_REGION \
            --allow-unauthenticated \ # Or configure authentication
            --set-env-vars "FLASK_SECRET_KEY=your_secret_key_from_secret_manager_or_direct" \
            --set-env-vars "TWITTER_CLIENT_ID=your_twitter_id" \
            --set-env-vars "TWITTER_CLIENT_SECRET=your_twitter_secret" \
            --set-env-vars "GOOGLE_CLIENT_ID=your_google_id" \
            --set-env-vars "GOOGLE_CLIENT_SECRET=your_google_secret" \
            --set-env-vars "CELERY_BROKER_URL=your_redis_instance_url" \
            --set-env-vars "CELERY_RESULT_BACKEND=your_redis_instance_url"
            # Consider using Google Secret Manager for sensitive environment variables.
        ```
    *   Ensure the Cloud Run service has appropriate network access to your Redis instance (e.g., via VPC Connector if Redis is in a VPC).

3.  **Deploy Celery Worker:**
    *   The Celery worker needs to run as a separate process. Options include:
        *   **Another Cloud Run Service:** If your tasks are short-lived or can be triggered by events (e.g., Pub/Sub). For continuous polling or long tasks, this might not be ideal or cost-effective. The `CMD` in the Dockerfile would need to be changed to start the Celery worker.
        *   **Google Compute Engine (GCE) VM:** More traditional, provides full control.
        *   **Google Kubernetes Engine (GKE):** For more complex, scalable deployments.
    *   The Celery worker deployment will also need all the necessary environment variables (API keys, Redis URL) and network access to Redis.
    *   If using the same Docker image for the worker, override the `CMD` to start Celery:
        `celery -A celery_app_setup.celery_app worker -l info`

This application can be deployed to various platforms like Google Cloud Run, Heroku, or any server that can host a Flask application and Celery workers.
Deployment typically involves:
- Containerizing the application (e.g., using Docker with a `Dockerfile`).
- Setting up a managed Redis instance.
- Configuring environment variables on the deployment platform securely.
- Running the Flask application server (e.g., Gunicorn) and Celery worker processes.

```
