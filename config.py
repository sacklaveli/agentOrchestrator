import logging
import sys

# =========================
# CONFIGURATION
# =========================
OLLAMA_MODEL = "deepseek-coder-v2"
OLLAMA_URL = "http://127.0.0.1:11434"
MAX_RETRIES = 10
INITIAL_BACKOFF = 5
MAX_BACKOFF = 120

AIDER_TIMEOUT = 1000
OLLAMA_TIMEOUT = 120
BUILD_TIMEOUT = 90

MEMORY_FILE_NAME = "orchestrator_memory.json"

# =========================
# VECTOR DB CONFIG
# =========================
DB_HOST = "localhost"
DB_PORT = "5432"
DB_USER = "user"
DB_PASS = "password"
DB_NAME = "orchestrator_db"

# EMBEDDING SETTINGS
# Ensure this matches your model! 
# nomic-embed-text = 768
# mxbai-embed-large = 1024
# llama3 = 4096
EMBEDDING_MODEL = "qwen3-embedding" 
EMBEDDING_DIM = 4096

# =========================
# LANGUAGE PROFILES
# =========================
LANGUAGE_PROFILES = {
    "csharp": {
        "name": "C#",
        "default_build": "dotnet build services\FormFieldAnalysis\FormFieldAnalysis.csproj --no-restore --verbosity quiet /p:NoWarn=* 2>&1",
        "default_test": "dotnet test services\FormFieldAnalysis\FormFieldAnalysis.csproj --no-restore --verbosity quiet /p:NoWarn=* 2>&1",
        "error_patterns": [r"error CS\d+:.*", r"Failed:\s+[1-9]\d*", r"Exception:"],
        "critical_files": ["Program.cs", "Startup.cs", "*.csproj", "appsettings.json"],
        "ignore_dirs": ["bin", "obj", ".git", ".vs"]
    },
    # ... (Add other languages as needed)
}

def setup_logging():
    file_handler = logging.FileHandler("aider_orchestrator.log", encoding='utf-8')
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"))
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
    return logging.getLogger("orchestrator")

logger = setup_logging()