from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import os

# Server defaults
DEFAULT_HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("BRIDGE_PORT", "8090"))

import json

# Local storage configuration
DATA_DIR = Path(os.environ.get("BRIDGE_DATA_DIR", Path.home() / ".antigravity-bridge"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNTS_FILE = DATA_DIR / "accounts.json"
CREDENTIALS_FILE = DATA_DIR / "credentials.json"


def _load_oauth_credentials() -> tuple[str, str]:
    """
    Load Google Antigravity OAuth client credentials.
    Priority:
    1. Environment variables (ANTIGRAVITY_CLIENT_ID, ANTIGRAVITY_CLIENT_SECRET)
    2. User credentials file (~/.antigravity-bridge/credentials.json)
    3. Project root .env file
    """
    client_id = os.environ.get("ANTIGRAVITY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("ANTIGRAVITY_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret

    # Check ~/.antigravity-bridge/credentials.json
    if CREDENTIALS_FILE.is_file():
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not client_id and data.get("client_id"):
                    client_id = str(data["client_id"]).strip()
                if not client_secret and data.get("client_secret"):
                    client_secret = str(data["client_secret"]).strip()
                if client_id and client_secret:
                    return client_id, client_secret
        except Exception:
            pass

    # Check project .env
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.is_file():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k == "ANTIGRAVITY_CLIENT_ID" and not client_id:
                        client_id = v
                    elif k == "ANTIGRAVITY_CLIENT_SECRET" and not client_secret:
                        client_secret = v
        except Exception:
            pass

    return client_id, client_secret


GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET = _load_oauth_credentials()

GOOGLE_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]
GOOGLE_OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Antigravity upstream endpoints
ANTIGRAVITY_BASE_URL = os.environ.get(
    "ANTIGRAVITY_BASE_URL",
    "https://daily-cloudcode-pa.googleapis.com/v1internal"
)
ANTIGRAVITY_FALLBACK_BASE_URL = "https://cloudcode-pa.googleapis.com/v1internal"
DEFAULT_PROJECT = "aicode-consumers"
USER_AGENT = "antigravity/2.13.0"

# Fallback to Gemini when 3P Claude quota is exhausted
AUTO_FALLBACK_TO_GEMINI = os.environ.get("BRIDGE_AUTO_FALLBACK", "true").lower() == "true"

# Supported Antigravity models
KNOWN_MODELS = [
    {
        "id": "gemini-3.8-flash-high",
        "name": "Gemini 3.8 Flash (High)",
        "group": "gemini",
        "context_window": 1048576,
    },
    {
        "id": "gemini-3.8-flash-medium",
        "name": "Gemini 3.8 Flash (Medium)",
        "group": "gemini",
        "context_window": 1048576,
    },
    {
        "id": "gemini-3.8-flash-low",
        "name": "Gemini 3.8 Flash (Low)",
        "group": "gemini",
        "context_window": 1048576,
    },
    {
        "id": "gemini-3.7-flash-high",
        "name": "Gemini 3.7 Flash (High)",
        "group": "gemini",
        "context_window": 1048576,
    },
    {
        "id": "gemini-3.7-flash-medium",
        "name": "Gemini 3.7 Flash (Medium)",
        "group": "gemini",
        "context_window": 1048576,
    },
    {
        "id": "gemini-3.7-flash-low",
        "name": "Gemini 3.7 Flash (Low)",
        "group": "gemini",
        "context_window": 1048576,
    },
    {
        "id": "gemini-3.6-flash-high",
        "name": "Gemini 3.6 Flash (High)",
        "group": "gemini",
        "context_window": 1048576,
    },
    {
        "id": "gemini-3.1-pro-low",
        "name": "Gemini 3.1 Pro (Low)",
        "group": "gemini",
        "context_window": 2097152,
    },
    {
        "id": "claude-sonnet-4-6",
        "name": "Claude Sonnet 4.6 (Thinking)",
        "group": "3p",
        "context_window": 200000,
    },
    {
        "id": "claude-opus-4-6-thinking",
        "name": "Claude Opus 4.6 (Thinking)",
        "group": "3p",
        "context_window": 200000,
    },
    {
        "id": "gpt-oss-120b-medium",
        "name": "GPT-OSS 120B (Medium)",
        "group": "3p",
        "context_window": 128000,
    },
]

# Model alias map for standard agent models to Antigravity native models
MODEL_ALIASES = {
    # Anthropic Claude aliases
    "claude-3-7-sonnet-latest": "claude-sonnet-4-6",
    "claude-3-7-sonnet-20250219": "claude-sonnet-4-6",
    "claude-3-5-sonnet-latest": "claude-sonnet-4-6",
    "claude-3-5-sonnet-20241022": "claude-sonnet-4-6",
    "claude-3-5-sonnet-20240620": "claude-sonnet-4-6",
    "claude-3-opus-latest": "claude-opus-4-6-thinking",
    "claude-3-opus-20240229": "claude-opus-4-6-thinking",
    "claude-haiku-4-5": "gemini-3.8-flash-high",
    "claude-haiku-4-5-20251001": "gemini-3.8-flash-high",
    "claude-3-5-haiku-latest": "gemini-3.8-flash-high",
    "claude-3-5-haiku-20241022": "gemini-3.8-flash-high",
    "claude-3-haiku-20240307": "gemini-3.8-flash-medium",
    
    # OpenAI GPT aliases
    "gpt-4o": "gemini-3.8-flash-high",
    "gpt-4o-mini": "gemini-3.7-flash-high",
    "gpt-4-turbo": "gemini-3.8-flash-high",
    "gpt-4": "gemini-3.8-flash-high",
    "o1": "claude-opus-4-6-thinking",
    "o3-mini": "gemini-3.8-flash-high",
    "chatgpt-4o-latest": "gemini-3.8-flash-high",
    
    # Gemini aliases
    "gemini-2.5-flash": "gemini-3.8-flash-high",
    "gemini-2.5-pro": "gemini-3.1-pro-low",
    "gemini-2.0-flash": "gemini-3.8-flash-high",
    "gemini-1.5-pro": "gemini-3.1-pro-low",
    "gemini-1.5-flash": "gemini-3.7-flash-high",
    
    # Quick /model command aliases for Claude Code & agents
    "haiku": "gemini-3.8-flash-high",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6-thinking",
    "claude-opus-4-6": "claude-opus-4-6-thinking",
    "gemini": "gemini-3.8-flash-high",
    "gemini-flash": "gemini-3.8-flash-high",
    "gemini-pro": "gemini-3.1-pro-low",
    "flash": "gemini-3.8-flash-high",
    "pro": "gemini-3.1-pro-low",
    "gemini-3.8": "gemini-3.8-flash-high",
    "gemini-3.7": "gemini-3.7-flash-high",
    "gemini-3.1": "gemini-3.1-pro-low",
    
    # Generic
    "default": "gemini-3.8-flash-high",
}


# Dynamic models discovered at runtime
_DYNAMIC_MODELS: Dict[str, Dict[str, Any]] = {}
_DYNAMIC_ALIASES: Dict[str, str] = {}


def register_discovered_models(models_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Register models dynamically discovered from Google Antigravity backend on startup / reload.
    Updates the active model catalog and creates convenient aliases.
    """
    global _DYNAMIC_MODELS, _DYNAMIC_ALIASES
    registered = []
    
    for model_id, info in models_dict.items():
        if not isinstance(info, dict):
            continue
            
        display_name = info.get("displayName") or model_id
        provider = info.get("modelProvider", "MODEL_PROVIDER_GOOGLE")
        is_3p = "anthropic" in provider.lower() or "openai" in provider.lower() or "claude" in model_id.lower() or "gpt" in model_id.lower()
        group = "3p" if is_3p else "gemini"
        
        entry = {
            "id": model_id,
            "name": display_name,
            "group": group,
            "context_window": info.get("maxTokens", 1048576),
            "max_output_tokens": info.get("maxOutputTokens", 65536),
            "supports_thinking": info.get("supportsThinking", False),
            "recommended": info.get("recommended", False),
            "provider": provider,
        }
        _DYNAMIC_MODELS[model_id] = entry
        registered.append(entry)
        
        # Register automatic aliases
        lower_id = model_id.lower()
        if "claude" in lower_id:
            _DYNAMIC_ALIASES[lower_id.replace("-thinking", "")] = model_id
        if "flash" in lower_id and "gemini" in lower_id:
            parts = lower_id.split("-")
            if len(parts) >= 2:
                _DYNAMIC_ALIASES[parts[0] + "-" + parts[1]] = model_id

    return registered


def get_all_known_models() -> List[Dict[str, Any]]:
    """Return all known models (combines dynamic discovered models and static fallbacks)."""
    seen = set()
    result = []
    # Dynamic first (fresh from backend)
    for m_id, m in _DYNAMIC_MODELS.items():
        seen.add(m_id.lower())
        result.append(m)
    # Static models next
    for m in KNOWN_MODELS:
        if m["id"].lower() not in seen:
            seen.add(m["id"].lower())
            result.append(m)
    return result


def resolve_model(model_name: str) -> str:
    """Resolve an incoming model name to an Antigravity supported model id."""
    if not model_name:
        return "gemini-3.8-flash-high"
    
    clean = model_name.strip().lower()
    
    # Exact match in dynamic models
    for m_id, m in _DYNAMIC_MODELS.items():
        if m_id.lower() == clean:
            return m_id

    # Exact match in static models
    for m in KNOWN_MODELS:
        if m["id"].lower() == clean:
            return m["id"]
            
    # Dynamic alias match
    if clean in _DYNAMIC_ALIASES:
        return _DYNAMIC_ALIASES[clean]

    # Static alias match
    if clean in MODEL_ALIASES:
        return MODEL_ALIASES[clean]
        
    # Heuristic matches
    if "opus" in clean:
        return "claude-opus-4-6-thinking"
    if "claude" in clean or "sonnet" in clean:
        return "claude-sonnet-4-6"
    if "oss" in clean:
        return "gpt-oss-120b-medium"
    if "pro" in clean:
        return "gemini-3.1-pro-low"
    if "flash" in clean or "gemini" in clean:
        return "gemini-3.8-flash-high"
        
    # Default fallback
    return "gemini-3.8-flash-high"


def get_model_group(model_id: str) -> str:
    """Returns 'gemini' or '3p' (Claude/GPT) for quota tracking."""
    resolved = resolve_model(model_id)
    if resolved in _DYNAMIC_MODELS:
        return _DYNAMIC_MODELS[resolved].get("group", "gemini")
    for m in KNOWN_MODELS:
        if m["id"] == resolved:
            return m.get("group", "gemini")
    if "claude" in resolved or "gpt-oss" in resolved:
        return "3p"
    return "gemini"
