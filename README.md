🤖 Local AI Coding Orchestrator
Your personal AI coding assistant that works completely offline. No API keys. No cloud dependencies. No data leaving your machine.

Stop copy-pasting code from ChatGPT and hoping it works. This orchestrator actually understands your codebase, verifies its own work, and learns from its mistakes—all running 100% locally on your machine.

Why This Exists
Traditional AI coding tools either:

Send your proprietary code to the cloud (privacy nightmare)

Generate code without understanding your project's context (integration hell)

Can't verify if their changes actually work (debugging nightmare)

This tool solves all three. It's like having a junior developer who:

Follows Instructions: Reads your Architecture.md before writing a single line of code.

** cleans Up:** Auto-formats code to prevent syntax errors.

Verifies: Actually runs the tests before saying "it's done".

Learns: Gets smarter every time they fix a bug.

Works Free: 24/7, on your hardware.

✨ New Features (v2.0)
📚 Documentation-First Intelligence
The agent doesn't just guess. It performs Semantic Documentation Search before every task:

Global Context: Scans for high-level patterns in Architecture.md before planning.

Just-In-Time Context: When writing a test, it pulls up TestingGuidelines.md automatically.

🔗 Smart Context (The "Family Finder")
If you ask the agent to edit UserService.cs, it automatically detects and reads:

IUserService.cs (The Interface/Contract)

UserServiceTests.cs (The usage patterns) No more hallucinating methods that don't exist.

🧹 "The Janitor" (Auto-Linting)
Generative AI often misses a semicolon or messes up indentation.

The Janitor runs immediately after every edit (e.g., dotnet format).

It silently fixes syntax errors before the compiler ever sees them, saving massive amounts of retry time.

🏗️ How It Works
┌─────────────────────────────────────────────────────────┐
│  1. INDEX: Scan & embed code + docs (Structure-Aware)   │
│     └─> Chunks code by class/method, docs by headers    │
├─────────────────────────────────────────────────────────┤
│  2. PLAN: Parse your feature request (Markdown)         │
│     └─> Extract actionable steps + Global Doc Search    │
├─────────────────────────────────────────────────────────┤
│  3. SMART SEARCH: Gather Context                        │
│     └─> Vector Search + "Family Finder" (Tests/Interfaces) │
├─────────────────────────────────────────────────────────┤
│  4. EXECUTE: Aider + LLM edits the actual files         │
│     └─> Applies changes -> RUNS "THE JANITOR" (Linting) │
├─────────────────────────────────────────────────────────┤
│  5. VERIFY: Run build/test commands you specified       │
│     └─> Did it actually work?                           │
├─────────────────────────────────────────────────────────┤
│  6. REFLECT & FIX: If verification failed...            │
│     └─> Root cause analysis + retry with fix            │
├─────────────────────────────────────────────────────────┤
│  7. LEARN: Success? Save solution to memory             │
│     └─> Next time this breaks, instant fix              │
└─────────────────────────────────────────────────────────┘
Tech Stack:

Orchestrator: Python (workflow engine)

Vector DB: PostgreSQL + pgvector (semantic search + memory)

Agent: Aider + Ollama (code editing with local LLMs)

🚀 Quick Start
Prerequisites
1. Docker Desktop (running)

2. Ollama (install here)

Pull the recommended models (Stable & Efficient):

Bash
ollama pull deepseek-coder-v2      # The coding brain
ollama pull nomic-embed-text       # The vector search (Low VRAM usage)
3. Configure Ollama for Docker

The orchestrator runs in Docker and needs to reach Ollama on your host machine:

Windows:

PowerShell
setx OLLAMA_HOST "0.0.0.0"
# Restart Ollama from taskbar
Mac/Linux:

Bash
launchctl setenv OLLAMA_HOST "0.0.0.0"
pkill ollama && ollama serve
Installation
Bash
# Clone the repo
git clone <your-repo-url>
cd local-ai-coding-orchestrator

# Build the container
docker-compose build

# Start the database
docker-compose up -d vectordb
💻 Usage
Step 1: Write a Plan
Create a Markdown file describing your feature (e.g., add_login.md). Tip: The agent now respects Verification commands strictly.

Markdown
# Goal: Implement user login endpoint

## Context
We're building a REST API. Follow `CodingStandards.md` patterns.

## Steps
1. Create `UserLoginRequest` DTO.
   - Verification: dotnet build

2. Create `AuthService` with JWT generation.
   - Verification: dotnet build

3. Add unit tests for invalid credentials.
   - Verification: dotnet test --filter "AuthServiceTests"
Step 2: Run the Orchestrator
Bash
# Basic run
docker-compose run --rm orchestrator python -m orchestrator.main add_login.md

# Force re-index (Use this if you added new .md documentation files!)
docker-compose run --rm orchestrator python -m orchestrator.main add_login.md --reindex
Step 3: Review Changes
The agent modifies your files directly. Use Git to review:

Bash
git diff
⚙️ Configuration
Stability Settings (Low VRAM)
By default, we recommend nomic-embed-text to prevent OOM crashes when running alongside large coding models.

Edit orchestrator/config.py:

Python
# orchestrator/config.py

OLLAMA_MODEL = "deepseek-coder-v2"
EMBEDDING_MODEL = "nomic-embed-text" # Small, fast, highly accurate
EMBEDDING_DIM = 768                # CRITICAL: Must match model dimensions
⚠️ Important: If you change EMBEDDING_DIM, reset the database:

Bash
docker-compose down -v
docker-compose up -d vectordb
🛡️ Troubleshooting
"HTTP Error 500" during indexing
Cause: Ollama ran out of VRAM while generating embeddings. Fix:

Ensure config.py is set to nomic-embed-text (768 dim).

The indexer now has a built-in "breather" (1s pause) between chunks to let VRAM flush.

"No documentation found"
Cause: The vector search was getting confused by mixed content types. Fix: The system now uses SQL-level filtering (WHERE file_path LIKE '%.md') to ensure documentation searches always return actual docs.

Build/test commands fail inside Docker
Cause: Missing dependencies. Fix: Mount your local caches in docker-compose.yml:

YAML
volumes:
  - .:/workspace
  - ~/.nuget:/root/.nuget  # Cache .NET packages
  - ~/.npm:/root/.npm      # Cache Node packages
📜 License
Copyright © 2026. All Rights Reserved. This is proprietary software made available for viewing and educational purposes only.

For licensing inquiries, please contact jason.usack@gmail.com.