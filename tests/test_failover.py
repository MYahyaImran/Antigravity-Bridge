import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from bridge.account_manager import Account, AccountManager
from bridge.antigravity_client import AntigravityClient, QuotaExceededError
from bridge.quota_router import QuotaRouter


class TestFailover(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_failover_when_quota_exhausted(self):
        # Create mock account manager with two accounts
        acc1 = Account(
            email="acc1@gmail.com",
            refresh_token="ref1",
            access_token="tok1",
            token_expiry=time.time() + 3600,
            status="active",
            quota_summary={
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [{"remainingFraction": 0.95}],
                    }
                ]
            },
        )
        acc2 = Account(
            email="acc2@gmail.com",
            refresh_token="ref2",
            access_token="tok2",
            token_expiry=time.time() + 3600,
            status="active",
            quota_summary={
                "groups": [
                    {
                        "displayName": "Gemini Models",
                        "buckets": [{"remainingFraction": 0.80}],
                    }
                ]
            },
        )

        acc_mgr = MagicMock(spec=AccountManager)
        acc_mgr.list_accounts.return_value = [acc1, acc2]
        acc_mgr.get_valid_access_token = AsyncMock(side_effect=lambda a: f"token_{a.email}")
        acc_mgr.save = MagicMock()

        # Mock Antigravity client
        client = MagicMock(spec=AntigravityClient)
        client.fetch_quota_summary = AsyncMock(return_value={"groups": []})
        client.load_code_assist = AsyncMock(return_value={})
        client.fetch_models = AsyncMock(return_value={"models": {}})

        async def mock_stream_gen(access_token, model, contents, **kwargs):
            if "acc2" in access_token:
                # Account 2 succeeds!
                yield {"response": {"candidates": [{"content": {"parts": [{"text": "Success from Account 2!"}]}}]}}
            else:
                # Account 1 hits quota limit
                raise QuotaExceededError("429 Resource exhausted: Quota limit reached for acc1")

        client.stream_generate_content.side_effect = mock_stream_gen

        # Create router
        router = QuotaRouter(acc_mgr, client)

        # Collect response chunks
        chunks = []
        async for chunk in router.stream_with_failover(
            model="gemini-3.8-flash-high",
            contents=[{"role": "user", "parts": [{"text": "Hello"}]}],
        ):
            chunks.append(chunk)

        # Assertions:
        # 1. Output from account 2 arrived
        self.assertEqual(len(chunks), 1)
        text = chunks[0]["response"]["candidates"][0]["content"]["parts"][0]["text"]
        self.assertEqual(text, "Success from Account 2!")

        # 2. Account 1 was marked exhausted
        self.assertEqual(acc1.status, "exhausted")
        self.assertGreater(acc1.exhausted_until, time.time())

        # 3. Account 2 was kept active and updated last_used
        self.assertEqual(acc2.status, "active")
        self.assertGreater(acc2.last_used, 0)

    async def test_sorting_by_remaining_quota(self):
        acc_low = Account(
            email="low@gmail.com",
            refresh_token="r",
            access_token="t",
            quota_summary={"groups": [{"displayName": "Gemini Models", "buckets": [{"remainingFraction": 0.2}]}]},
        )
        acc_high = Account(
            email="high@gmail.com",
            refresh_token="r",
            access_token="t",
            quota_summary={"groups": [{"displayName": "Gemini Models", "buckets": [{"remainingFraction": 0.8}]}]},
        )

        acc_mgr = MagicMock(spec=AccountManager)
        acc_mgr.list_accounts.return_value = [acc_low, acc_high]

        client = MagicMock(spec=AntigravityClient)
        router = QuotaRouter(acc_mgr, client)

        candidates = router.get_candidate_accounts("gemini-3.8-flash-high")
        # Higher quota account must be selected first
        self.assertEqual(candidates[0][0].email, "high@gmail.com")
        self.assertEqual(candidates[1][0].email, "low@gmail.com")


if __name__ == "__main__":
    unittest.main()
