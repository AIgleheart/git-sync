FROM python:3.12-slim

# Install git (used by git-sync.sh at runtime)
# Credentials, identity, and repo initialization are handled on the host
# before deploying this container — see README Part 1.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Install Flask
RUN pip install --no-cache-dir flask

# Create app directory
WORKDIR /app

# Copy application files
COPY server.py       /app/server.py
COPY static/         /app/static/
COPY git-sync.sh     /usr/local/bin/git-sync.sh
RUN chmod +x         /usr/local/bin/git-sync.sh

EXPOSE 8585

CMD ["python3", "/app/server.py"]
