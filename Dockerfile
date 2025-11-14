FROM python:3.12-slim

# Install git (required for the tool to work)
RUN apt-get update && \
    apt-get install -y git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy application files
COPY git_line_stage.py /app/
COPY pyproject.toml /app/

# Install uv
RUN pip install --no-cache-dir uv

# Install dependencies
RUN uv pip install --system mcp

# Make script executable
RUN chmod +x /app/git_line_stage.py

# Set default working directory for git operations
WORKDIR /workspace

# Default command
ENTRYPOINT ["python", "/app/git_line_stage.py"]
