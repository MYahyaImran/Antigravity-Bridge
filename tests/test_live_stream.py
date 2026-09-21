import asyncio
import unittest
import httpx

from bridge.server import app


class TestEndpoints(unittest.IsolatedAsyncioTestCase):
    async def test_get_models(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/v1/models")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("object"), "list")
            ids = [m["id"] for m in data.get("data", [])]
            self.assertIn("gemini-3.8-flash-high", ids)
            self.assertIn("claude-sonnet-4-6", ids)

    async def test_get_dashboard(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("Antigravity Multi-Account Bridge", resp.text)

    async def test_accounts_api(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/accounts")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("accounts", data)


if __name__ == "__main__":
    unittest.main()
