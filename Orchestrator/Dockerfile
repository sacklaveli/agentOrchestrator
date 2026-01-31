# Use Python 3.12 as the base
FROM python:3.12-slim-bookworm

# 1. Install System Dependencies & Git
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 2. Install .NET 8 SDK (Required for compilation)
RUN wget https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -O packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && apt-get install -y dotnet-sdk-8.0

# 3. Install Python Dependencies (Aider, PGVector)
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Configure Git (Required for Aider to work)
# We set dummy values; Aider uses these for its internal commits
RUN git config --global user.email "ai-orchestrator@bot.com" \
    && git config --global user.name "AI Orchestrator"

# 5. Set Environment Variables
ENV PYTHONUNBUFFERED=1
ENV OLLAMA_URL="http://host.docker.internal:11434"

# The entrypoint will be overridden by docker-compose, but this is a safe default
CMD ["python", "-m", "orchestrator.main", "--help"]