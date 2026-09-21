import asyncio
import json
import logging
import unittest
from starlette.testclient import TestClient

from bridge.log_manager import (
    LogBufferHandler,
    clear_logs,
    get_log_stats,
    get_recent_logs,
    setup_logging,
)
from bridge.server import app


class TestLogMonitoring(unittest.TestCase):
    def setUp(self):
        self.handler = setup_logging()
        self.logger = logging.getLogger("test.logger")

    def test_log_buffer_handler(self):
        self.logger.info("Test info message 123")
        self.logger.warning("Test warning message 456")
        self.logger.error("Test error message 789")

        logs = get_recent_logs(limit=20)
        self.assertTrue(len(logs) >= 3)
        messages = [e["message"] for e in logs]
        self.assertTrue(any("Test info message 123" in m for m in messages))
        self.assertTrue(any("Test warning message 456" in m for m in messages))
        self.assertTrue(any("Test error message 789" in m for m in messages))

    def test_log_filtering(self):
        self.logger.info("Alpha uniquely identifiable log entry")
        self.logger.error("Beta uniquely identifiable error entry")

        # Test search filter
        matched = get_recent_logs(search="uniquely identifiable")
        self.assertEqual(len(matched), 2)

        # Test level filter
        errors_only = get_recent_logs(level="ERROR", search="uniquely identifiable")
        self.assertEqual(len(errors_only), 1)
        self.assertIn("Beta", errors_only[0]["message"])

    def test_log_stats(self):
        stats = get_log_stats()
        self.assertIn("total", stats)
        self.assertIn("errors", stats)
        self.assertIn("warnings", stats)
        self.assertIn("failovers", stats)
        self.assertIn("requests", stats)
        self.assertIn("log_file", stats)
        self.assertTrue(isinstance(stats["total"], int))

    def test_api_logs_endpoints(self):
        client = TestClient(app)

        # GET /api/logs
        resp = client.get("/api/logs?limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("logs", data)
        self.assertIn("stats", data)
        self.assertTrue(isinstance(data["logs"], list))

        # GET /api/logs/stats
        stats_resp = client.get("/api/logs/stats")
        self.assertEqual(stats_resp.status_code, 200)
        self.assertIn("total", stats_resp.json())

        # GET /api/logs/download
        dl_resp = client.get("/api/logs/download")
        self.assertEqual(dl_resp.status_code, 200)
        self.assertIn("text/plain", dl_resp.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
