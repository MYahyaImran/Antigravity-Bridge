# 🚀 Antigravity Multi-Account Bridge (`apx`)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

A high-performance, local AI proxy bridge that connects coding and chat agents (**Cursor**, **Claude Code**, **Hermes**, **Codex**, **Aider**, and **Continue**) to **Google Antigravity** subscription models. It pools **multiple Google accounts** into a unified endpoint with real-time quota tracking, dynamic model discovery, live log monitoring, and automatic zero-drop failover.

---

## 💡 Why Antigravity Bridge?

Google Antigravity provides access to cutting-edge models like **Gemini 3.8 Flash**, **Gemini 3.7 Flash**, **Claude Sonnet 4.6**, and **Claude Opus 4.6 Thinking**. However:
1. **Quota Bottlenecks**: Heavy coding sessions exhaust single-account quotas quickly.
2. **Agent Incompatibility**: Coding agents speak standard OpenAI or Anthropic protocols, while Google uses an internal CloudCode PA protocol.
3. **Complex Manual Setup**: Configuring multiple agents requires tedious environment variable exports and JSON/SQLite editing.

**Antigravity Bridge solves all three:**
- **Pool multiple accounts**: When Account A runs low or hits a rate limit (`429` / `RESOURCE_EXHAUSTED`), the bridge instantly and transparently rotates to Account B, C, or D.
- **Unified standard API**: Native `/v1/chat/completions` (OpenAI format) and `/v1/messages` (Anthropic format).
- **1-Click Agent Setup**: Automatically discovers and configures Cursor, Claude Code, Hermes, and Aider.
- **Real-Time Log Monitor**: Live SSE streaming terminal in the web dashboard and CLI.

---

## ⚡ Zero-Clone Remote Installation

You can run or install Antigravity Bridge **immediately without cloning the repository**:

### Option 1: Instant Isolated Run with `uvx` (Fastest, No Install)
```bash
uvx --from git+https://github.com/MYahyaImran/Antigravity-Bridge.git apx start -d
```

### Option 2: Instant Run with `pipx`
```bash
pipx run --spec git+https://github.com/MYahyaImran/Antigravity-Bridge.git apx start -d
```

### Option 3: One-Line Windows PowerShell Bootstrap
Installs `apx` into your User PATH without git:
```powershell
irm https://raw.githubusercontent.com/MYahyaImran/Antigravity-Bridge/main/install.ps1 | iex
```

### Option 4: One-Line Linux / macOS Bootstrap
```bash
curl -fsSL https://raw.githubusercontent.com/MYahyaImran/Antigravity-Bridge/main/install.sh | bash
```

### Option 5: Standard Git Clone & Local Run
```bash
git clone https://github.com/MYahyaImran/Antigravity-Bridge.git
cd Antigravity-Bridge
pip install -e .
apx start -d
```

---

## 🏗️ Architecture

```
                    ┌───────────────────────────────┐
                    │  AI Coding & Chat Agents      │
                    │  (Cursor, Claude, Hermes, etc)│
                    └───────────────┬───────────────┘
                                    │
                  OpenAI / Anthropic Protocol (HTTP / SSE)
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │             Antigravity Bridge (Port 8090)              │
       │                                                         │
       │  ┌───────────────────────┐   ┌───────────────────────┐  │
       │  │ OpenAI Adapter (/v1)  │   │ Anthropic Adapter     │  │
       │  └───────────┬───────────┘   └───────────┬───────────┘  │
       │              │                           │              │
       │              └─────────────┬─────────────┘              │
       │                            ▼                            │
       │              ┌───────────────────────────┐              │
       │              │    Quota Router & Pool    │              │
       │              └─────────────┬─────────────┘              │
       │                            │                            │
       │      ┌─────────────────────┼─────────────────────┐      │
       │      ▼                     ▼                     ▼      │
       │  Account 1             Account 2             Account 3  │
       │  (95% Quota)           (80% Quota)           (Exhausted)│
       └──────┬─────────────────────┬────────────────────────────┘
              │                     │
              ▼                     ▼
       ┌─────────────────────────────────────────────────────────┐
       │        Google Antigravity CloudCode PA Backend          │
       │      (daily-cloudcode-pa / cloudcode-pa.googleapis.com) │
       └─────────────────────────────────────────────────────────┘
```

---

## 🌟 Key Features

### 1. Multi-Account Quota Pooling & Seamless Failover
- Connect as many Google accounts as you want.
- Real-time quota polling tracks remaining percentages for both **Gemini models** and **3P models** (Claude & GPT).
- Requests are intelligently routed to the account with the highest available quota.
- If an account returns a `429`, `RESOURCE_EXHAUSTED`, or `503 CAPACITY_EXHAUSTED`, the bridge seamlessly fails over to the next healthy account without dropping your stream.

### 2. Dynamic Live Model Detection
- Automatically contacts Google's `v1internal:fetchAvailableModels` backend on server boot, reload, and sync.
- Dynamically discovers **60+ models and aliases** (e.g. `gemini-3.8-flash-high`, `gemini-3.7-flash-high`, `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`).
- Automatically resolves common aliases like `claude-3-7-sonnet`, `gpt-4o`, and `gemini-2.5-pro`.

### 3. 1-Click Agent Auto-Setup
Configure your development tools with a single click or CLI command:
- **Cursor AI Editor**: Automatically backs up and writes `settings.json` and updates SQLite `state.vscdb` (`openAIBaseUrl` + `useOpenAIKey: true`).
- **Claude Code CLI (`claude`)**: Sets up `~/.claude/settings.json` with `ANTHROPIC_BASE_URL`.
- **Hermes Agent**: Configures `%LOCALAPPDATA%\hermes\config.yaml` to route through the bridge with proper token bounds.
- **Aider**: Configures `~/.aider.conf.yml`.
- **System Environment**: Sets persistent Windows environment variables (`OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`).
- **Clean Rollback**: Run `apx setup --revert` anytime to restore original settings from timestamped `.bak` backups.

### 4. Real-Time Log Monitoring
- **Web Dashboard Terminal**: Glassmorphism dark terminal with live Server-Sent Events (SSE) streaming.
- **Search & Level Filtering**: Instantly filter logs by level (`INFO`, `WARNING`, `ERROR`) or keyword (e.g. `quota`, `failover`, `hermes`).
- **Metrics Bar**: Live counts of Total Events, Agent Requests, Quota Failovers, Warnings, and Errors.
- **Terminal CLI**: Run `apx logs -f` to tail logs live right inside your command line.

---

## 🖥️ Web Dashboard (`http://localhost:8090/`)

Once the bridge is running, open **`http://localhost:8090/`** in your browser:

- **📊 Overview & Accounts**: Real-time quota progress bars for Gemini and Claude/GPT buckets, account pause/resume toggles, and live activity preview.
- **📜 Live Log Monitoring**: Full-screen real-time terminal streaming server logs, request tracing, and failover notifications.
- **⚡ 1-Click Setup**: Auto-detect installed agents and configure them with one click.
- **🧪 Test Playground**: Interactive prompt playground with live SSE response streaming.

---

## 💻 Complete CLI Reference (`apx` / `bridge`)

```bash
# Start bridge server in background (default port: 8090)
apx start -d

# Start bridge on a custom port
apx start -d --port 8095

# Restart the running bridge server
apx restart -d

# Check running status, process PID, and account count
apx status

# List all connected accounts and real-time quota levels
apx accounts

# Authenticate another Google account via OAuth
apx add-account

# Re-import account from Windows Credential Manager
apx import-local

# Live Log Monitoring
apx logs                # View last 50 log lines
apx logs -n 100         # View last 100 log lines
apx logs -f             # Tail logs in real time (stream live)
apx logs --clear        # Clear logs

# 1-Click Agent Auto-Configuration
apx setup cursor        # Configure Cursor AI Editor
apx setup claude        # Configure Claude Code CLI
apx setup hermes        # Configure Hermes Agent
apx setup aider         # Configure Aider
apx setup all           # Configure all detected agents
apx setup --revert      # Rollback all agent configurations from backup

# Test prompt with live streaming
apx test --model gemini-3.8-flash-high --prompt "Explain quantum computing in 10 words."

# Stop background server
apx stop
```

---

## 🛠️ Manual Agent Configuration (Optional)

If you prefer to configure your agents manually:

### Cursor AI Editor
In **Cursor Settings** (`Ctrl + Shift + J` or `Cmd + Shift + J`) -> **Models**:
1. Enable **OpenAI API Key** and enter: `antigravity`
2. Enable **Override OpenAI Base URL** and enter: `http://localhost:8090/v1`
3. Add custom models: `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gemini-3.8-flash-high`

### Claude Code CLI (`claude`)
```bash
export ANTHROPIC_BASE_URL="http://localhost:8090"
export ANTHROPIC_API_KEY="antigravity"
claude
```

### Hermes Agent
In `config.yaml` or terminal:
```bash
export OPENAI_BASE_URL="http://localhost:8090/v1"
export OPENAI_API_KEY="antigravity"
hermes chat --model gemini-3.8-flash-high
```

### Aider
```bash
export OPENAI_BASE_URL="http://localhost:8090/v1"
export OPENAI_API_KEY="antigravity"
aider --model openai/gemini-3.8-flash-high
```

---

## 📋 Common Models & Aliases

| Model Name | Upstream Model ID | Group | Context Window |
|---|---|---|---|
| `gemini-3.8-flash-high` | `gemini-3.8-flash-high` | Gemini | 1,048,576 |
| `gemini-3.7-flash-high` | `gemini-3.7-flash-high` | Gemini | 1,048,576 |
| `gemini-3.1-pro-low` | `gemini-3.1-pro-low` | Gemini | 1,048,576 |
| `claude-sonnet-4-6` | `claude-sonnet-4-6` | 3P | 200,000 |
| `claude-opus-4-6-thinking` | `claude-opus-4-6-thinking` | 3P | 200,000 |
| `gpt-oss-120b-medium` | `gpt-oss-120b-medium` | 3P | 131,072 |
| `gpt-4o` *(alias)* | `gemini-3.8-flash-high` | Gemini | 1,048,576 |
| `claude-3-5-sonnet` *(alias)* | `claude-sonnet-4-6` | 3P | 200,000 |
| `claude-3-7-sonnet` *(alias)* | `claude-sonnet-4-6` | 3P | 200,000 |

---

## 🔒 Security & Privacy

- **Local Storage Only**: All account tokens and session metadata are stored strictly on your local machine (`~/.antigravity-bridge/accounts.json`).
- **Zero Telemetry**: No third-party servers, analytics, or tracking.
- **Direct HTTPS**: All API calls communicate directly with Google's official endpoints.
- See [SECURITY.md](SECURITY.md) for full details.

---

## 🧪 Testing

Run the automated test suite:
```bash
python -m unittest discover tests
```
Includes adapter transformations, multi-account failover simulator, dynamic model registration, live SSE log streaming, and agent setup tests.

---

## 🤝 Contributing

Contributions are welcome! Please check out [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, development guidelines, and PR procedures.

---

## 📄 License

Released under the [MIT License](LICENSE).
