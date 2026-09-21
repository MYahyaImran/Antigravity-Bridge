import unittest
from bridge.config import (
    register_discovered_models,
    get_all_known_models,
    resolve_model,
    get_model_group,
    _DYNAMIC_MODELS,
    _DYNAMIC_ALIASES,
)
from bridge.adapters.openai_adapter import get_openai_models_list


class TestDynamicModels(unittest.TestCase):
    def setUp(self):
        _DYNAMIC_MODELS.clear()
        _DYNAMIC_ALIASES.clear()

    def tearDown(self):
        _DYNAMIC_MODELS.clear()
        _DYNAMIC_ALIASES.clear()

    def test_register_discovered_models(self):
        sample_models = {
            "claude-sonnet-4-6": {
                "displayName": "Claude Sonnet 4.6 (Thinking)",
                "modelProvider": "MODEL_PROVIDER_ANTHROPIC",
                "maxTokens": 200000,
                "maxOutputTokens": 65536,
                "supportsThinking": True,
            },
            "gemini-3.9-ultra-preview": {
                "displayName": "Gemini 3.9 Ultra Preview",
                "modelProvider": "MODEL_PROVIDER_GOOGLE",
                "maxTokens": 2000000,
                "maxOutputTokens": 65536,
                "supportsThinking": True,
            },
        }

        registered = register_discovered_models(sample_models)
        self.assertEqual(len(registered), 2)

        # Check resolution
        self.assertEqual(resolve_model("gemini-3.9-ultra-preview"), "gemini-3.9-ultra-preview")
        self.assertEqual(resolve_model("claude-sonnet-4-6"), "claude-sonnet-4-6")

        # Check group
        self.assertEqual(get_model_group("claude-sonnet-4-6"), "3p")
        self.assertEqual(get_model_group("gemini-3.9-ultra-preview"), "gemini")

        # Check OpenAI format
        oai_list = get_openai_models_list()
        model_ids = [m["id"] for m in oai_list["data"]]
        self.assertIn("gemini-3.9-ultra-preview", model_ids)
        self.assertIn("claude-sonnet-4-6", model_ids)

    def test_alias_resolution(self):
        # Static aliases
        self.assertEqual(resolve_model("gpt-4o"), "gemini-3.8-flash-high")
        self.assertEqual(resolve_model("claude-3-7-sonnet-latest"), "claude-sonnet-4-6")
        self.assertEqual(resolve_model("claude-3-5-sonnet-latest"), "claude-sonnet-4-6")


if __name__ == "__main__":
    unittest.main()
