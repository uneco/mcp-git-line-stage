# Base image for git-polite testing
# Contains: Python, git, git-polite installed
# Other scenarios should FROM this image

FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Configure git globally
RUN git config --global user.email "test@example.com" && \
    git config --global user.name "Test User" && \
    git config --global init.defaultBranch main

# Copy and install git-polite
COPY git_polite.py /app/
COPY pyproject.toml /app/
COPY README.md /app/
RUN pip install --no-cache-dir -e /app[dev]

# Set working directory for tests
WORKDIR /repo

# Note: Test files will be mounted at runtime via -v flag
# No CMD here - this is a base image for other scenarios
