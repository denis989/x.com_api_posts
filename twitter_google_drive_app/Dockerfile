# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set environment variables
# Ensures that Python output is sent straight to the terminal without buffering
ENV PYTHONUNBUFFERED 1
# Sets the port the app will run on within the container (Cloud Run provides PORT env var)
ENV PORT 8080
# Set the working directory in the container
WORKDIR /app

# Install system dependencies that might be needed by Python packages (if any)
# For example, if a library needed `libpq-dev` for PostgreSQL or `build-essential`
# RUN apt-get update && apt-get install -y some-package && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
COPY . .

# Command to run the application using Gunicorn
# Gunicorn will listen on 0.0.0.0:$PORT, where $PORT is provided by Cloud Run or defaults to 8080
# The number of workers can be adjusted. A common recommendation is (2 * number_of_cores) + 1
# `app:app` refers to the `app` Flask instance in `app.py`
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0 app:app
