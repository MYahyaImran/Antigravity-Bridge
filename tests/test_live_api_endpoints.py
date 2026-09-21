import asyncio
import json
import unittest
import httpx

from bridge.server import app


class TestLiveApiEndpoints(unittest.IsolatedAsyncioTestCase):
    async def test_live_openai_chat_completions_streaming(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
            req_body = {
                "model": "gemini-3.8-flash-high",
                "messages": [
                    {"role": "user", "content": "Reply with 'OpenAI streaming works' only."}
                ],
                "stream": True,
            }
            received_deltas = []
            async with client.stream("POST", "/v1/chat/completions", json=req_body) as resp:
                self.assertEqual(resp.status_code, 200)
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line.strip() != "data: [DONE]":
                        payload = json.loads(line[6:])
                        choices = payload.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                received_deltas.append(content)

            full_text = "".join(received_deltas)
            print("\n[OpenAI Stream Output]:", full_text)
            self.assertTrue(len(full_text) > 0)

    async def test_live_openai_chat_completions_non_streaming(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
            req_body = {
                "model": "gemini-3.8-flash-high",
                "messages": [
                    {"role": "user", "content": "Reply with 'OpenAI JSON works' only."}
                ],
                "stream": False,
            }
            resp = await client.post("/v1/chat/completions", json=req_body)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("object"), "chat.completion")
            message = data["choices"][0]["message"]
            self.assertEqual(message["role"], "assistant")
            print("\n[OpenAI Non-Stream Output]:", message["content"])
            self.assertTrue(len(message["content"]) > 0)

    async def test_live_anthropic_messages_streaming(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as client:
            req_body = {
                "model": "gemini-3.8-flash-high",
                "messages": [
                    {"role": "user", "content": "Reply with 'Anthropic SSE works' only."}
                ],
                "max_tokens": 100,
                "stream": True,
            }
            received_events = []
            received_text = []
            async with client.stream("POST", "/v1/messages", json=req_body) as resp:
                self.assertEqual(resp.status_code, 200)
                curr_event = None
                async for line in resp.aiter_lines():
                    if line.startswith("event: "):
                        curr_event = line[7:].strip()
                        received_events.append(curr_event)
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        if curr_event == "content_block_delta":
                            delta = data.get("delta", {})
                            if delta.get("type") == "text_delta":
                                received_text.append(delta.get("text", ""))

            full_text = "".join(received_text)
            print("\n[Anthropic Stream Output]:", full_text)
            self.assertIn("message_start", received_events)
            self.assertIn("content_block_start", received_events)
            self.assertIn("content_block_delta", received_events)
            self.assertIn("content_block_stop", received_events)
            self.assertIn("message_stop", received_events)
            self.assertTrue(len(full_text) > 0)


if __name__ == "__main__":
    unittest.main()
