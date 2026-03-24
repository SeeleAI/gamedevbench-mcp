FROM python:3.12-slim

# Install required system dependencies (including Node.js)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install uv package manager
RUN pip install uv

# Copy required files
COPY config.py /app/
COPY server.py /app/
COPY server_deploy.py /app/
COPY server_logic.py /app/
COPY server_start_config.py /app/
COPY pyproject.toml /app/
COPY README.md /app/
COPY __init__.py /app/
COPY port_discovery.py /app/
COPY connection/ /app/connection/
COPY tools/ /app/tools/
COPY util/ /app/util/
COPY llm/ /app/llm/
COPY remote_config/ /app/remote_config/
COPY http_logic/ /app/http_logic/

# Install Python dependencies using uv
RUN uv pip install --system -e .

# Install Playwright browser drivers (required for threejs_runtime)
RUN playwright install chromium
RUN playwright install-deps

# Install Node.js dependencies for html-bundler
WORKDIR /app/util/html_bundler
COPY util/html_bundler/package*.json /app/util/html_bundler/
RUN npm install
WORKDIR /app


# Command to run the server without re-syncing dependencies on startup
CMD ["python", "server_deploy.py"]