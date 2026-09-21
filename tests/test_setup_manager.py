import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.setup_manager import SetupManager


class TestSetupManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.claude_path = Path(self.temp_dir) / ".claude" / "settings.json"
        self.hermes_path = Path(self.temp_dir) / "hermes" / "config.yaml"
        self.aider_path = Path(self.temp_dir) / ".aider.conf.yml"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_configure_claude(self):
        mgr = SetupManager(port=8090)
        with patch.object(SetupManager, "claude_settings_path", new_callable=lambda: property(lambda self: self._claude_path)):
            mgr._claude_path = self.claude_path
            res = mgr.configure_claude()

            self.assertEqual(res["status"], "success")
            self.assertTrue(self.claude_path.exists())

            data = json.loads(self.claude_path.read_text(encoding="utf-8"))
            self.assertEqual(data["env"]["ANTHROPIC_BASE_URL"], "http://localhost:8090")
            self.assertEqual(data["env"]["ANTHROPIC_AUTH_TOKEN"], "antigravity")
            self.assertNotIn("ANTHROPIC_MODEL", data["env"])  # Crucial: Unlocks /model command in Claude CLI
            self.assertEqual(data["model"], "gemini-3.8-flash-high")

    def test_configure_claude_model_selection(self):
        mgr = SetupManager(port=8090)
        with patch.object(SetupManager, "claude_settings_path", new_callable=lambda: property(lambda self: self._claude_path)):
            mgr._claude_path = self.claude_path
            # Configure specifically with Claude Sonnet
            res = mgr.configure_claude(model="claude-sonnet-4-6")
            self.assertEqual(res["model"], "claude-sonnet-4-6")
            data = json.loads(self.claude_path.read_text(encoding="utf-8"))
            self.assertEqual(data["model"], "claude-sonnet-4-6")
            self.assertEqual(data["env"]["ANTHROPIC_DEFAULT_MODEL"], "claude-sonnet-4-6")
            self.assertEqual(data["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"], "claude-sonnet-4-6")
            self.assertEqual(data["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"], "claude-opus-4-6-thinking")
            self.assertEqual(data["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "claude-haiku-4-5")
            self.assertNotIn("ANTHROPIC_MODEL", data["env"])

            # Switch specifically to Gemini
            res_gem = mgr.configure_claude(model="gemini")
            self.assertEqual(res_gem["model"], "gemini-3.8-flash-high")
            data_gem = json.loads(self.claude_path.read_text(encoding="utf-8"))
            self.assertEqual(data_gem["model"], "gemini-3.8-flash-high")
            self.assertEqual(data_gem["env"]["ANTHROPIC_DEFAULT_MODEL"], "gemini-3.8-flash-high")
            self.assertNotIn("ANTHROPIC_MODEL", data_gem["env"])

    def test_configure_hermes(self):
        mgr = SetupManager(port=8090)
        self.hermes_path.parent.mkdir(parents=True, exist_ok=True)
        self.hermes_path.write_text("model:\n  provider: custom\n  base_url: http://127.0.0.1:8080\n", encoding="utf-8")

        with patch.object(SetupManager, "hermes_config_paths", new_callable=lambda: property(lambda self: [self._hermes_path])):
            mgr._hermes_path = self.hermes_path
            res = mgr.configure_hermes()

            self.assertEqual(res["status"], "success")
            content = self.hermes_path.read_text(encoding="utf-8")
            self.assertIn("http://127.0.0.1:8090", content)

    def test_configure_aider(self):
        mgr = SetupManager(port=8090)
        with patch.object(SetupManager, "aider_config_path", new_callable=lambda: property(lambda self: self._aider_path)):
            mgr._aider_path = self.aider_path
            res = mgr.configure_aider()

            self.assertEqual(res["status"], "success")
            self.assertTrue(self.aider_path.exists())
            content = self.aider_path.read_text(encoding="utf-8")
            self.assertIn("openai-api-base: http://localhost:8090/v1", content)
            self.assertIn("openai-api-key: antigravity", content)

    def test_configure_cursor(self):
        cursor_settings = Path(self.temp_dir) / "Cursor" / "settings.json"
        cursor_settings.parent.mkdir(parents=True, exist_ok=True)
        cursor_settings.write_text(json.dumps({"window.zoomLevel": 1}), encoding="utf-8")

        db_path = Path(self.temp_dir) / "nonexistent.db"
        mgr = SetupManager(port=8090)
        with patch.object(SetupManager, "cursor_settings_path", new_callable=lambda: property(lambda s: cursor_settings)), \
             patch.object(SetupManager, "cursor_db_path", new_callable=lambda: property(lambda s: db_path)):
            res = mgr.configure_cursor()
            self.assertEqual(res["status"], "success")
            self.assertTrue(cursor_settings.exists())

            data = json.loads(cursor_settings.read_text(encoding="utf-8"))
            self.assertEqual(data["cursor.openaiBaseUrl"], "http://localhost:8090/v1")
            self.assertEqual(data["cursor.openaiApiKey"], "antigravity")
            self.assertEqual(data["openai.baseUrl"], "http://localhost:8090/v1")
            self.assertEqual(data["window.zoomLevel"], 1)

            # Test revert
            revert_res = mgr.revert_cursor()
            self.assertEqual(revert_res["status"], "restored")
            reverted_data = json.loads(cursor_settings.read_text(encoding="utf-8"))
            self.assertNotIn("cursor.openaiBaseUrl", reverted_data)
            self.assertEqual(reverted_data["window.zoomLevel"], 1)


if __name__ == "__main__":
    unittest.main()
