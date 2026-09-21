import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from bridge.config import DEFAULT_PORT

logger = logging.getLogger("antigravity-bridge.setup")


class SetupManager:
    """Manages automatic detection, configuration, and restoration of coding agents."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port

    # ------------------------------------------------------------------
    # Agent Paths
    # ------------------------------------------------------------------

    @property
    def claude_settings_path(self) -> Path:
        return Path.home() / ".claude" / "settings.json"

    @property
    def hermes_config_paths(self) -> List[Path]:
        paths = []
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            paths.append(Path(local_app) / "hermes" / "config.yaml")
        paths.append(Path.home() / ".hermes" / "config.yaml")
        return [p for p in paths if p.exists() or p.parent.exists()]

    @property
    def aider_config_path(self) -> Path:
        return Path.home() / ".aider.conf.yml"

    @property
    def cursor_settings_path(self) -> Path:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "Cursor" / "User" / "settings.json"
            return Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "settings.json"
        elif sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "settings.json"
        else:
            return Path.home() / ".config" / "Cursor" / "User" / "settings.json"

    @property
    def cursor_db_path(self) -> Path:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
            return Path.home() / "AppData" / "Roaming" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        elif sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        else:
            return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"

    # ------------------------------------------------------------------
    # Detection & Status
    # ------------------------------------------------------------------

    def detect_agents(self) -> Dict[str, Dict[str, Any]]:
        """Detect available agents and their current configuration status."""
        results = {}

        # 1. Claude Code
        claude_detected = self.claude_settings_path.exists() or shutil.which("claude") is not None
        claude_configured = False
        claude_url = ""
        claude_model = ""
        if self.claude_settings_path.exists():
            try:
                data = json.loads(self.claude_settings_path.read_text(encoding="utf-8"))
                claude_url = data.get("env", {}).get("ANTHROPIC_BASE_URL", "")
                claude_model = data.get("model") or data.get("env", {}).get("ANTHROPIC_DEFAULT_MODEL") or data.get("env", {}).get("ANTHROPIC_MODEL", "")
                if f":{self.port}" in claude_url:
                    claude_configured = True
            except Exception as e:
                logger.debug("Error reading claude settings: %s", e)

        results["claude"] = {
            "name": "Claude Code CLI",
            "detected": claude_detected,
            "configured": claude_configured,
            "path": str(self.claude_settings_path),
            "current_url": claude_url,
            "current_model": claude_model or "gemini-3.8-flash-high",
            "description": "Anthropic Claude Code CLI (`claude`)",
        }

        # 2. Hermes
        hermes_detected = False
        hermes_configured = False
        hermes_path = ""
        hermes_url = ""
        hermes_model = ""
        for hp in self.hermes_config_paths:
            if hp.exists():
                hermes_detected = True
                hermes_path = str(hp)
                try:
                    content = hp.read_text(encoding="utf-8")
                    match = re.search(r"base_url:\s*['\"]?([^\r\n'\"]+)", content)
                    if match:
                        hermes_url = match.group(1).strip()
                        if f":{self.port}" in hermes_url:
                            hermes_configured = True
                    match_model = re.search(r"default:\s*['\"]?([^\r\n'\"]+)", content)
                    if match_model:
                        hermes_model = match_model.group(1).strip()
                except Exception as e:
                    logger.debug("Error reading hermes config: %s", e)
                break
        if not hermes_detected and shutil.which("hermes") is not None:
            hermes_detected = True

        results["hermes"] = {
            "name": "Hermes Agent",
            "detected": hermes_detected,
            "configured": hermes_configured,
            "path": hermes_path,
            "current_url": hermes_url,
            "current_model": hermes_model or "gemini-3.8-flash-high",
            "description": "Hermes AI Agent (`hermes`)",
        }

        # 3. Aider
        aider_detected = self.aider_config_path.exists() or shutil.which("aider") is not None
        aider_configured = False
        aider_url = ""
        aider_model = ""
        if self.aider_config_path.exists():
            try:
                content = self.aider_config_path.read_text(encoding="utf-8")
                match = re.search(r"openai-api-base:\s*['\"]?([^\r\n'\"]+)", content)
                if match:
                    aider_url = match.group(1).strip()
                    if f":{self.port}" in aider_url:
                        aider_configured = True
                match_m = re.search(r"model:\s*['\"]?([^\r\n'\"]+)", content)
                if match_m:
                    aider_model = match_m.group(1).strip()
            except Exception:
                pass

        results["aider"] = {
            "name": "Aider",
            "detected": aider_detected,
            "configured": aider_configured,
            "path": str(self.aider_config_path),
            "current_url": aider_url,
            "current_model": aider_model or "gemini-3.8-flash-high",
            "description": "Aider AI Pair Programmer (`aider`)",
        }

        # 4. Cursor AI Editor
        cursor_detected = (
            self.cursor_settings_path.exists()
            or self.cursor_db_path.exists()
            or shutil.which("cursor") is not None
        )
        if not cursor_detected and sys.platform == "win32":
            local_app = os.environ.get("LOCALAPPDATA")
            if local_app and (Path(local_app) / "Programs" / "cursor" / "Cursor.exe").exists():
                cursor_detected = True

        cursor_configured = False
        cursor_url = ""
        cursor_model = ""
        # Check settings.json
        if self.cursor_settings_path.exists():
            try:
                data = json.loads(self.cursor_settings_path.read_text(encoding="utf-8"))
                cursor_url = data.get("cursor.openaiBaseUrl") or data.get("openai.baseUrl") or ""
                cursor_model = data.get("cursor.model") or data.get("openai.model") or ""
                if f":{self.port}" in cursor_url:
                    cursor_configured = True
            except Exception as e:
                logger.debug("Error reading cursor settings: %s", e)

        # Check state.vscdb if not already marked configured
        if not cursor_configured and self.cursor_db_path.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(self.cursor_db_path)
                c = conn.cursor()
                key = "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser"
                c.execute("SELECT value FROM ItemTable WHERE key = ?", (key,))
                row = c.fetchone()
                if row and row[0]:
                    val = json.loads(row[0])
                    db_url = val.get("openAIBaseUrl", "")
                    if f":{self.port}" in db_url:
                        cursor_configured = True
                        cursor_url = db_url
                conn.close()
            except Exception as e:
                logger.debug("Error checking cursor state.vscdb: %s", e)

        results["cursor"] = {
            "name": "Cursor AI Editor",
            "detected": cursor_detected,
            "configured": cursor_configured,
            "path": str(self.cursor_settings_path) if self.cursor_settings_path.exists() else str(self.cursor_db_path),
            "current_url": cursor_url,
            "current_model": cursor_model or "claude-sonnet-4-6",
            "description": "Cursor AI Code Editor (Custom OpenAI endpoint & models)",
        }

        # 5. System / User Environment Variables (Windows)
        env_configured = False
        if sys.platform == "win32":
            import winreg
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ)
                try:
                    val, _ = winreg.QueryValueEx(key, "OPENAI_BASE_URL")
                    if f":{self.port}" in val:
                        env_configured = True
                except FileNotFoundError:
                    pass
                finally:
                    winreg.CloseKey(key)
            except Exception:
                pass

        results["env"] = {
            "name": "System User Environment",
            "detected": True,
            "configured": env_configured,
            "path": "HKCU\\Environment",
            "current_url": f"http://localhost:{self.port}" if env_configured else "",
            "description": "Global Windows User environment variables (`OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`)",
        }

        return results

    # ------------------------------------------------------------------
    # Configuration Actions
    # ------------------------------------------------------------------

    def configure_claude(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Configure Claude Code CLI settings.json to point to Antigravity Bridge."""
        target = self.claude_settings_path
        target.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                # Backup existing
                bak_path = target.with_suffix(".json.bak_antigravity")
                if not bak_path.exists():
                    shutil.copy2(target, bak_path)
            except Exception as e:
                logger.warning("Could not parse existing claude settings: %s", e)

        from bridge.config import resolve_model
        requested = model or data.get("model") or "gemini-3.8-flash-high"
        resolved_model = resolve_model(requested)

        env_block = data.setdefault("env", {})
        env_block["ANTHROPIC_BASE_URL"] = f"http://localhost:{self.port}"
        env_block["ANTHROPIC_AUTH_TOKEN"] = env_block.get("ANTHROPIC_AUTH_TOKEN") or "antigravity"

        # IMPORTANT FIX: Delete hardcoded ANTHROPIC_MODEL from env!
        # If ANTHROPIC_MODEL is in env, Claude Code locks the model and ignores "/model" changes.
        # Removing ANTHROPIC_MODEL allows the user to switch models seamlessly via the "/model" command!
        env_block.pop("ANTHROPIC_MODEL", None)

        # Set default startup model (Claude Code 2.1+)
        env_block["ANTHROPIC_DEFAULT_MODEL"] = resolved_model
        data["model"] = resolved_model

        # Tiers for Claude Code's interactive "/model" menu:
        # Sonnet: Claude Sonnet 4.6 (or Gemini Flash if in pure Gemini mode)
        # Opus: Claude Opus 4.6 Thinking (or Gemini Pro if in pure Gemini mode)
        # Haiku: Gemini 3.8 Flash High (alias claude-haiku-4-5)
        if "gemini" in resolved_model.lower():
            env_block["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "gemini-3.8-flash-high"
            env_block["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "gemini-3.1-pro-low"
            env_block["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = "gemini-3.8-flash-high"
            env_block["CLAUDE_CODE_SUBAGENT_MODEL"] = "gemini-3.8-flash-high"
        else:
            env_block["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "claude-sonnet-4-6"
            env_block["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "claude-opus-4-6-thinking"
            env_block["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = "claude-haiku-4-5"
            env_block["CLAUDE_CODE_SUBAGENT_MODEL"] = "claude-haiku-4-5"

        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Configured Claude Code CLI in %s with model %s", target, resolved_model)
        return {
            "agent": "claude",
            "status": "success",
            "path": str(target),
            "base_url": f"http://localhost:{self.port}",
            "model": resolved_model,
        }

    def configure_hermes(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Configure Hermes config.yaml to use Antigravity models on this port."""
        from bridge.config import resolve_model
        target_model = resolve_model(model) if model else "gemini-3.8-flash-high"
        configured_paths = []
        for target in self.hermes_config_paths:
            if not target.parent.exists():
                continue

            content = ""
            if target.exists():
                try:
                    content = target.read_text(encoding="utf-8")
                    bak_path = target.with_suffix(".yaml.bak_antigravity")
                    if not bak_path.exists():
                        shutil.copy2(target, bak_path)
                except Exception as e:
                    logger.warning("Could not read hermes config: %s", e)

            # Update base_url in model block
            bridge_url = f"http://127.0.0.1:{self.port}"
            if "model:" in content:
                content = re.sub(
                    r"(model:.*?base_url:\s*)[^\r\n]+",
                    r"\g<1>" + bridge_url,
                    content,
                    flags=re.DOTALL,
                )
                content = re.sub(
                    r"(model:.*?default:\s*)[^\r\n]+",
                    r"\g<1>" + target_model,
                    content,
                    flags=re.DOTALL,
                )
                content = re.sub(
                    r"(custom_providers:.*?base_url:\s*)[^\r\n]+",
                    r"\g<1>" + bridge_url,
                    content,
                    flags=re.DOTALL,
                )
            else:
                prefix = f"""model:
  provider: custom
  base_url: {bridge_url}
  api_key: antigravity
  api_mode: anthropic_messages
  default: {target_model}
"""
                content = prefix + "\n" + content

            target.write_text(content, encoding="utf-8")
            configured_paths.append(str(target))

        if not configured_paths:
            # Create in LocalAppData if exists, or Home
            default_p = self.hermes_config_paths[0] if self.hermes_config_paths else Path.home() / ".hermes" / "config.yaml"
            default_p.parent.mkdir(parents=True, exist_ok=True)
            default_p.write_text(f"""model:
  provider: custom
  base_url: http://127.0.0.1:{self.port}
  api_key: antigravity
  api_mode: anthropic_messages
  default: {target_model}
""", encoding="utf-8")
            configured_paths.append(str(default_p))

        logger.info("Configured Hermes in %s with model %s", configured_paths, target_model)
        return {
            "agent": "hermes",
            "status": "success",
            "paths": configured_paths,
            "base_url": f"http://127.0.0.1:{self.port}",
            "model": target_model,
        }

    def configure_aider(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Configure Aider config file ~/.aider.conf.yml."""
        from bridge.config import resolve_model
        target_model = resolve_model(model) if model else "gemini-3.8-flash-high"
        target = self.aider_config_path
        target.parent.mkdir(parents=True, exist_ok=True)

        content = ""
        if target.exists():
            content = target.read_text(encoding="utf-8")
            bak_path = target.with_suffix(".yml.bak_antigravity")
            if not bak_path.exists():
                shutil.copy2(target, bak_path)

        # Replace or append
        bridge_url = f"http://localhost:{self.port}/v1"
        if "openai-api-base:" in content:
            content = re.sub(r"openai-api-base:\s*[^\r\n]+", f"openai-api-base: {bridge_url}", content)
        else:
            content += f"\nopenai-api-base: {bridge_url}\n"

        if "openai-api-key:" in content:
            content = re.sub(r"openai-api-key:\s*[^\r\n]+", "openai-api-key: antigravity", content)
        else:
            content += "openai-api-key: antigravity\n"

        if "model:" in content:
            content = re.sub(r"model:\s*[^\r\n]+", f"model: openai/{target_model}", content)
        else:
            content += f"model: openai/{target_model}\n"

        target.write_text(content.strip() + "\n", encoding="utf-8")
        logger.info("Configured Aider in %s with model %s", target, target_model)
        return {
            "agent": "aider",
            "status": "success",
            "path": str(target),
            "base_url": bridge_url,
            "model": target_model,
        }

    def configure_cursor(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Configure Cursor AI editor to use Antigravity Bridge."""
        from bridge.config import resolve_model
        target_model = resolve_model(model) if model else "claude-sonnet-4-6"
        bridge_url = f"http://localhost:{self.port}/v1"
        configured_targets = []

        # 1. settings.json
        target_settings = self.cursor_settings_path
        try:
            target_settings.parent.mkdir(parents=True, exist_ok=True)
            settings_data = {}
            if target_settings.exists():
                try:
                    settings_data = json.loads(target_settings.read_text(encoding="utf-8"))
                    bak = target_settings.with_suffix(".json.bak_antigravity")
                    if not bak.exists():
                        shutil.copy2(target_settings, bak)
                except Exception as e:
                    logger.warning("Error reading existing cursor settings: %s", e)

            settings_data["cursor.openaiBaseUrl"] = bridge_url
            settings_data["cursor.openaiApiKey"] = "antigravity"
            settings_data["openai.baseUrl"] = bridge_url
            settings_data["openai.apiKey"] = "antigravity"
            settings_data["cursor.model"] = target_model
            settings_data["openai.model"] = target_model

            target_settings.write_text(json.dumps(settings_data, indent=2), encoding="utf-8")
            configured_targets.append(str(target_settings))
            logger.info("Configured Cursor settings in %s with model %s", target_settings, target_model)
        except Exception as e:
            logger.warning("Failed to configure Cursor settings.json: %s", e)

        # 2. state.vscdb (persistent applicationUser)
        target_db = self.cursor_db_path
        if target_db.exists():
            try:
                import sqlite3
                bak_db = target_db.with_suffix(".vscdb.bak_antigravity")
                if not bak_db.exists():
                    shutil.copy2(target_db, bak_db)

                conn = sqlite3.connect(target_db)
                c = conn.cursor()
                key = "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl.persistentStorage.applicationUser"
                c.execute("SELECT value FROM ItemTable WHERE key = ?", (key,))
                row = c.fetchone()
                if row and row[0]:
                    app_user = json.loads(row[0])
                    app_user["openAIBaseUrl"] = bridge_url
                    app_user["useOpenAIKey"] = True
                    c.execute("UPDATE ItemTable SET value = ? WHERE key = ?", (json.dumps(app_user), key))
                    conn.commit()
                    configured_targets.append(str(target_db))
                    logger.info("Configured Cursor state.vscdb at %s", target_db)
                conn.close()
            except Exception as e:
                logger.warning("Could not configure Cursor state.vscdb: %s", e)

        return {
            "agent": "cursor",
            "status": "success",
            "targets": configured_targets,
            "base_url": bridge_url,
            "model": target_model,
            "instructions": f"In Cursor Settings -> Models: OpenAI API Key is enabled and Base URL is set to {bridge_url}",
        }

    def configure_env(self) -> Dict[str, Any]:
        """Configure Windows user-level persistent environment variables."""
        vars_to_set = {
            "OPENAI_BASE_URL": f"http://localhost:{self.port}/v1",
            "OPENAI_API_KEY": "antigravity",
            "ANTHROPIC_BASE_URL": f"http://localhost:{self.port}",
            "ANTHROPIC_API_KEY": "antigravity",
        }

        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE)
            try:
                for k, v in vars_to_set.items():
                    winreg.SetValueEx(key, k, 0, winreg.REG_SZ, v)
            finally:
                winreg.CloseKey(key)

            # Broadcast WM_SETTINGCHANGE so processes update
            try:
                import ctypes
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x001A
                SMTO_ABORTIFHUNG = 0x0002
                result = ctypes.c_ulong()
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST,
                    WM_SETTINGCHANGE,
                    0,
                    "Environment",
                    SMTO_ABORTIFHUNG,
                    1000,
                    ctypes.byref(result),
                )
            except Exception:
                pass
        else:
            # On Linux/macOS, append to ~/.bashrc or ~/.zshrc
            sh_rc = Path.home() / ".bashrc"
            export_block = "\n".join([f'export {k}="{v}"' for k, v in vars_to_set.items()])
            with open(sh_rc, "a", encoding="utf-8") as f:
                f.write(f"\n# Antigravity Bridge\n{export_block}\n")

        # Also set in current process environment
        for k, v in vars_to_set.items():
            os.environ[k] = v

        logger.info("Set user environment variables for Antigravity Bridge")
        return {
            "agent": "env",
            "status": "success",
            "variables": vars_to_set,
        }

    def configure_all(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Configure all detected agents on the system."""
        results = {}
        agents = self.detect_agents()

        if agents.get("claude", {}).get("detected"):
            results["claude"] = self.configure_claude(model=model)
        if agents.get("hermes", {}).get("detected"):
            results["hermes"] = self.configure_hermes(model=model)
        if agents.get("aider", {}).get("detected"):
            results["aider"] = self.configure_aider(model=model)
        if agents.get("cursor", {}).get("detected"):
            results["cursor"] = self.configure_cursor(model=model)

        results["env"] = self.configure_env()
        return results

    # ------------------------------------------------------------------
    # Restoration / Revert
    # ------------------------------------------------------------------

    def revert_claude(self) -> Dict[str, Any]:
        target = self.claude_settings_path
        bak_path = target.with_suffix(".json.bak_antigravity")
        if bak_path.exists():
            shutil.copy2(bak_path, target)
            return {"agent": "claude", "status": "restored"}
        return {"agent": "claude", "status": "no_backup_found"}

    def revert_hermes(self) -> Dict[str, Any]:
        restored = []
        for target in self.hermes_config_paths:
            bak_path = target.with_suffix(".yaml.bak_antigravity")
            if bak_path.exists():
                shutil.copy2(bak_path, target)
                restored.append(str(target))
        return {"agent": "hermes", "status": "restored" if restored else "no_backup_found"}

    def revert_aider(self) -> Dict[str, Any]:
        target = self.aider_config_path
        bak_path = target.with_suffix(".yml.bak_antigravity")
        if bak_path.exists():
            shutil.copy2(bak_path, target)
            return {"agent": "aider", "status": "restored"}
        return {"agent": "aider", "status": "no_backup_found"}

    def revert_env(self) -> Dict[str, Any]:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE)
            try:
                for k in ["OPENAI_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"]:
                    try:
                        winreg.DeleteValue(key, k)
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
        return {"agent": "env", "status": "removed"}

    def revert_cursor(self) -> Dict[str, Any]:
        """Revert Cursor configuration from backup."""
        restored = []
        target_settings = self.cursor_settings_path
        bak_settings = target_settings.with_suffix(".json.bak_antigravity")
        if bak_settings.exists():
            shutil.copy2(bak_settings, target_settings)
            restored.append(str(target_settings))

        target_db = self.cursor_db_path
        bak_db = target_db.with_suffix(".vscdb.bak_antigravity")
        if bak_db.exists():
            shutil.copy2(bak_db, target_db)
            restored.append(str(target_db))

        return {"agent": "cursor", "status": "restored" if restored else "no_backup_found"}

    def revert_all(self) -> Dict[str, Any]:
        return {
            "claude": self.revert_claude(),
            "hermes": self.revert_hermes(),
            "aider": self.revert_aider(),
            "cursor": self.revert_cursor(),
            "env": self.revert_env(),
        }
