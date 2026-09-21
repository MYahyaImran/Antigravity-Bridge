# Contributing to Antigravity Multi-Account Bridge

First off, thank you for considering contributing to the Antigravity Multi-Account Bridge! Projects like this improve through community feedback, bug reports, adapter contributions, and documentation improvements.

---

## 🛠️ Development Setup

### 1. Prerequisites
- **Python 3.10+**
- Git

### 2. Clone the Repository
```bash
git clone https://github.com/MYahyaImran/Antigravity-Bridge.git
cd Antigravity-Bridge
```

### 3. Create a Virtual Environment
```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On Linux / macOS:
source .venv/bin/activate
```

### 4. Install in Editable Mode with Dependencies
```bash
pip install -e .
```

---

## 🧪 Running Tests

The test suite covers model adapters, failover rotation, setup managers, dynamic model detection, log monitoring, and live API endpoints:

```bash
# Run all unit and integration tests:
python -m unittest discover tests

# Run specific test modules:
python -m unittest tests.test_adapters
python -m unittest tests.test_failover
python -m unittest tests.test_dynamic_models
python -m unittest tests.test_setup_manager
python -m unittest tests.test_log_monitoring
```

---

## 📂 Project Architecture

```
Bridge/
├── bin/                       # Cross-platform CLI wrapper scripts (apx, bridge)
├── bridge/                    # Core Python package
│   ├── adapters/              # Protocol converters (OpenAI <-> Antigravity, Anthropic <-> Antigravity)
│   ├── static/                # Web Dashboard UI (Single-Page App with live SSE logs)
│   ├── account_manager.py     # Multi-account token storage, encryption, and automatic refresh
│   ├── antigravity_client.py  # Direct HTTP client for Google CloudCode PA backend
│   ├── config.py              # Known models, dynamic model catalog, defaults
│   ├── log_manager.py         # Ring buffer, rotating file handler, SSE log broadcaster
│   ├── quota_router.py        # Real-time quota tracking, scoring, failover router
│   ├── server.py              # FastAPI server implementing /v1 and /api routes
│   └── setup_manager.py       # 1-Click configuration for Hermes, Claude Code, Cursor, Aider
├── tests/                     # Comprehensive test suite
├── bridge.py                  # CLI entry point (apx command line interface)
├── install.ps1                # Zero-clone Windows installer script
├── install.sh                 # Zero-clone Linux/macOS installer script
├── pyproject.toml             # Standard PEP 621 packaging
└── setup.py                   # Setuptools fallback packaging
```

---

## 🤝 Submitting Changes

1. **Fork the repo** and create a feature branch:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. **Make your changes** cleanly with appropriate documentation.
3. **Run tests** to ensure no regressions:
   ```bash
   python -m unittest discover tests
   ```
4. **Commit your changes**:
   ```bash
   git commit -m "Add feature: support new agent setup"
   ```
5. **Push to your fork** and open a Pull Request!

---

## 📋 Code Style & Standards
- Follow standard PEP 8 conventions.
- Maintain documentation integrity and preserve type hints where possible.
- Never commit private OAuth tokens, `accounts.json`, or `.env` files.
