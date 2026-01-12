# Use an official Python runtime as a parent image
FROM python:3.12-slim-bullseye

# Set the working directory in the container
WORKDIR /app

# Install system utilities and tools for the agent
# Added networking tools, database clients, and file utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    openssh-client \
    default-mysql-client \
    postgresql-client \
    redis-tools \
    ftp \
    rsync \
    jq \
    vim \
    nano \
    tree \
    zip \
    unzip \
    make \
    iputils-ping \
    dnsutils \
    netcat \
    procps \
    iproute2 \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22+ and npx to test mcp tools
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Run the application
# Use ASYNC_MODE environment variable to switch between sync and async modes
# Default: sync mode (run.py)
# Async mode: set ASYNC_MODE=true
CMD if [ "$ASYNC_MODE" = "true" ]; then \
      echo "🚀 Starting in ASYNC mode..."; \
      python run.py; \
    else \
      echo "🚀 Starting in SYNC mode..."; \
      python run.py; \
    fi