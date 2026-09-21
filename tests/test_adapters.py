import unittest

from bridge.adapters.openai_adapter import (
    convert_openai_to_antigravity,
    get_openai_models_list,
)
from bridge.adapters.anthropic_adapter import convert_anthropic_to_antigravity
from bridge.config import resolve_model, get_model_group


class TestAdapters(unittest.TestCase):
    def test_model_resolution(self):
        self.assertEqual(resolve_model("gpt-4o"), "gemini-3.8-flash-high")
        self.assertEqual(resolve_model("claude-3-5-sonnet-latest"), "claude-sonnet-4-6")
        self.assertEqual(resolve_model("claude-3-7-sonnet-20250219"), "claude-sonnet-4-6")
        self.assertEqual(resolve_model("claude-3-opus-latest"), "claude-opus-4-6-thinking")
        self.assertEqual(resolve_model("gemini-2.5-flash"), "gemini-3.8-flash-high")
        self.assertEqual(resolve_model("gemini-2.5-pro"), "gemini-3.1-pro-low")
        self.assertEqual(resolve_model("gemini-3.8-flash-high"), "gemini-3.8-flash-high")

    def test_model_group(self):
        self.assertEqual(get_model_group("gemini-3.8-flash-high"), "gemini")
        self.assertEqual(get_model_group("claude-sonnet-4-6"), "3p")
        self.assertEqual(get_model_group("claude-opus-4-6-thinking"), "3p")
        self.assertEqual(get_model_group("gpt-oss-120b-medium"), "3p")

    def test_convert_openai_to_antigravity(self):
        req = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "What is Python?"},
                {"role": "assistant", "content": "A programming language."},
                {"role": "user", "content": "Who created it?"},
            ],
            "temperature": 0.5,
            "max_tokens": 1000,
        }

        model, contents, sys_inst, gen_config = convert_openai_to_antigravity(req)

        self.assertEqual(model, "gemini-3.8-flash-high")
        self.assertIsNotNone(sys_inst)
        self.assertEqual(sys_inst["parts"][0]["text"], "Be concise.")
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[0]["parts"][0]["text"], "What is Python?")
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[2]["role"], "user")
        self.assertEqual(gen_config["temperature"], 0.5)
        self.assertEqual(gen_config["maxOutputTokens"], 2048)

    def test_convert_anthropic_to_antigravity(self):
        req = {
            "model": "claude-3-5-sonnet-latest",
            "system": "You are Claude Code.",
            "messages": [
                {"role": "user", "content": "Help me refactor this code."},
                {"role": "assistant", "content": [{"type": "text", "text": "Sure, show me the code."}]},
                {"role": "user", "content": [{"type": "text", "text": "Here it is."}]},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }

        model, contents, sys_inst, gen_config, tools = convert_anthropic_to_antigravity(req)

        self.assertEqual(model, "claude-sonnet-4-6")
        self.assertIsNotNone(sys_inst)
        self.assertEqual(sys_inst["parts"][0]["text"], "You are Claude Code.")
        self.assertEqual(len(contents), 3)
        self.assertEqual(contents[0]["role"], "user")
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"][0]["text"], "Sure, show me the code.")
        self.assertEqual(gen_config["maxOutputTokens"], 2048)
        self.assertIsNone(tools)

    def test_anthropic_tools_and_multiturn(self):
        from bridge.adapters.anthropic_adapter import clean_schema_for_gemini
        
        # Test schema cleaning
        raw_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "anyOf": [
                        {"type": "string", "enum": ["read", "write"]},
                        {"type": "string", "const": "execute"}
                    ]
                },
                "limit": {
                    "type": "integer",
                    "exclusiveMinimum": 1
                },
                "extra": {
                    "type": "object",
                    "propertyNames": {"type": "string"}
                }
            }
        }
        cleaned = clean_schema_for_gemini(raw_schema)
        self.assertNotIn("$schema", cleaned)
        self.assertNotIn("propertyNames", cleaned["properties"]["extra"])
        self.assertEqual(cleaned["properties"]["limit"]["minimum"], 1)
        self.assertEqual(cleaned["properties"]["action"]["enum"], ["read", "write", "execute"])

        # Test request conversion with tools and tool use/result history
        req = {
            "model": "claude-sonnet-4-6",
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": raw_schema
                }
            ],
            "messages": [
                {"role": "user", "content": "Please read test.py"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Reading the file now."},
                        {"type": "tool_use", "id": "toolu_001", "name": "read_file", "input": {"path": "test.py"}}
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_001", "content": "print('hello')"},
                        {"type": "text", "text": "What do you think?"}
                    ]
                }
            ]
        }
        model, contents, _, _, tools_param = convert_anthropic_to_antigravity(req)
        self.assertEqual(model, "claude-sonnet-4-6")
        self.assertIsNotNone(tools_param)
        self.assertEqual(len(tools_param[0]["functionDeclarations"]), 1)
        self.assertEqual(tools_param[0]["functionDeclarations"][0]["name"], "read_file")

        # Check multi-turn contents
        self.assertEqual(len(contents), 3)
        # Assistant turn: text parts MUST be first, functionCall last
        self.assertEqual(contents[1]["role"], "model")
        self.assertEqual(contents[1]["parts"][0]["text"], "Reading the file now.")
        fc_part = contents[1]["parts"][1]
        self.assertIn("functionCall", fc_part)
        self.assertIn("thoughtSignature", fc_part)
        self.assertEqual(fc_part["functionCall"]["name"], "read_file")
        self.assertEqual(fc_part["functionCall"]["id"], "toolu_001")
        self.assertEqual(fc_part["functionCall"]["args"]["path"], "test.py")

        # User turn with tool result: functionResponse MUST be first
        self.assertEqual(contents[2]["role"], "user")
        fr_part = contents[2]["parts"][0]
        self.assertIn("functionResponse", fr_part)
        self.assertEqual(fr_part["functionResponse"]["name"], "read_file")
        self.assertEqual(fr_part["functionResponse"]["id"], "toolu_001")
        self.assertEqual(fr_part["functionResponse"]["response"]["result"], "print('hello')")
        # Text part comes second
        self.assertEqual(contents[2]["parts"][1]["text"], "What do you think?")

    def test_hermes_max_tokens_clamp(self):
        # Hermes sends max_tokens=128000 which Google Antigravity rejects if not clamped
        req_flash = {
            "model": "gemini-3.7-flash-high",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 128000,
        }
        _, _, _, gen_config_flash, _ = convert_anthropic_to_antigravity(req_flash)
        self.assertEqual(gen_config_flash["maxOutputTokens"], 65536)

        req_pro = {
            "model": "gemini-2.5-pro",
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 128000,
        }
        _, _, _, gen_config_pro, _ = convert_anthropic_to_antigravity(req_pro)
        self.assertEqual(gen_config_pro["maxOutputTokens"], 32768)

    def test_openai_models_list(self):
        models = get_openai_models_list()
        self.assertEqual(models["object"], "list")
        ids = [m["id"] for m in models["data"]]
        self.assertIn("gemini-3.8-flash-high", ids)
        self.assertIn("claude-sonnet-4-6", ids)
        self.assertIn("claude-opus-4-6-thinking", ids)

    def test_anthropic_thinking_blocks_conversion(self):
        # Claude Code sends thinking blocks in multi-turn conversation history
        req = {
            "model": "claude-sonnet-4-6",
            "messages": [
                {"role": "user", "content": "What is 2+2?"},
                {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "The user is asking a basic arithmetic question."},
                        {"type": "text", "text": "2 + 2 = 4"},
                    ],
                },
                {"role": "user", "content": "Are you sure?"},
            ],
        }
        _, contents, _, _, _ = convert_anthropic_to_antigravity(req)
        self.assertEqual(len(contents), 3)

        # Assistant turn should have thinking converted to Part with text=thought and thought=True (boolean TYPE_BOOL)
        model_parts = contents[1]["parts"]
        self.assertEqual(len(model_parts), 2)
        self.assertEqual(model_parts[0]["text"], "The user is asking a basic arithmetic question.")
        self.assertIs(model_parts[0]["thought"], True)
        self.assertEqual(model_parts[1]["text"], "2 + 2 = 4")

        # Verify normalize_antigravity_contents correctly sanitizes and preserves thought: True
        from bridge.antigravity_client import normalize_antigravity_contents
        cleaned = normalize_antigravity_contents(contents)
        cleaned_model_parts = cleaned[1]["parts"]
        self.assertEqual(cleaned_model_parts[0]["text"], "The user is asking a basic arithmetic question.")
        self.assertIs(cleaned_model_parts[0]["thought"], True)

    def test_clean_schema_for_gemini_nested_arrays_and_edge_cases(self):
        from bridge.antigravity_client import clean_schema_for_gemini, normalize_antigravity_tools

        # 1. Exact issue user encountered: query.where has items={type: "array"} without items
        schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "object",
                    "properties": {
                        "where": {
                            "type": "array",
                            "items": {
                                "type": "array"
                                # Note: no items field here!
                            }
                        }
                    }
                },
                "flat_array": {
                    "type": "array"
                    # Note: missing items field entirely!
                },
                "tuple_array": {
                    "type": "array",
                    "items": [{"type": "integer"}]
                },
                "union_type": {
                    "type": ["string", "null"]
                },
                "nested_empty_obj": {
                    "type": "object"
                }
            },
            "required": ["query", "non_existent_key"]
        }

        cleaned = clean_schema_for_gemini(schema, is_root=True)

        # where.items.items must exist and have type string
        where_prop = cleaned["properties"]["query"]["properties"]["where"]
        self.assertEqual(where_prop["type"], "array")
        self.assertEqual(where_prop["items"]["type"], "array")
        self.assertIn("items", where_prop["items"])
        self.assertEqual(where_prop["items"]["items"]["type"], "string")

        # flat_array must have items injected
        self.assertIn("items", cleaned["properties"]["flat_array"])
        self.assertEqual(cleaned["properties"]["flat_array"]["items"]["type"], "string")

        # tuple_array items unwrap list
        self.assertIsInstance(cleaned["properties"]["tuple_array"]["items"], dict)
        self.assertEqual(cleaned["properties"]["tuple_array"]["items"]["type"], "integer")

        # union_type converted to single string + nullable
        self.assertEqual(cleaned["properties"]["union_type"]["type"], "string")
        self.assertTrue(cleaned["properties"]["union_type"]["nullable"])

        # nested empty object gets non-empty properties placeholder
        self.assertIn("properties", cleaned["properties"]["nested_empty_obj"])
        self.assertTrue(len(cleaned["properties"]["nested_empty_obj"]["properties"]) > 0)

        # required list pruned to only valid properties
        self.assertEqual(cleaned["required"], ["query"])

        # Test normalize_antigravity_tools
        raw_tools = [
            {
                "functionDeclarations": [
                    {
                        "name": "search_db",
                        "description": "Search database",
                        "parameters": schema
                    }
                ]
            }
        ]
        norm_tools = normalize_antigravity_tools(raw_tools)
        self.assertIsNotNone(norm_tools)
        norm_decl = norm_tools[0]["functionDeclarations"][0]
        self.assertEqual(norm_decl["name"], "search_db")
        self.assertIn("items", norm_decl["parameters"]["properties"]["query"]["properties"]["where"]["items"])


if __name__ == "__main__":
    unittest.main()

