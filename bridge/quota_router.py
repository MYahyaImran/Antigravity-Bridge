import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from bridge.account_manager import Account, AccountManager
from bridge.antigravity_client import AntigravityClient, QuotaExceededError
from bridge.config import get_model_group, resolve_model

logger = logging.getLogger("antigravity-bridge.quota_router")


def parse_rfc3339_timestamp(ts_str: Optional[str]) -> float:
    """Parse RFC3339 / ISO 8601 timestamp into unix epoch seconds."""
    if not ts_str:
        return 0.0
    try:
        # Handles 2026-09-23T11:39:15Z or with timezone offset
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return 0.0


class QuotaRouter:
    def __init__(self, account_manager: AccountManager, client: AntigravityClient):
        self.account_manager = account_manager
        self.client = client
        self._lock = asyncio.Lock()
        self._last_sync_time: float = 0

    async def reload_available_models(self) -> List[Dict[str, Any]]:
        """
        Detect and register all models dynamically from Google Antigravity backend.
        Uses the first healthy active account to query fetchAvailableModels.
        """
        accounts = self.account_manager.list_accounts()
        for acc in accounts:
            if not acc.enabled:
                continue
            try:
                token = await self.account_manager.get_valid_access_token(acc)
                resp = await self.client.fetch_models(token)
                models_dict = resp.get("models", {})
                if models_dict:
                    from bridge.config import register_discovered_models
                    registered = register_discovered_models(models_dict)
                    logger.info("Dynamically detected %d models from account %s on reload", len(registered), acc.email)
                    return registered
            except Exception as e:
                logger.debug("Could not fetch models using %s: %s", acc.email, e)
        return []

    async def sync_all_quotas(self, force: bool = False):
        """Sync quota information for all accounts and refresh available models."""
        now = time.time()
        # Rate-limit background quota syncs to at most once every 60 seconds unless forced
        if not force and (now - self._last_sync_time) < 60:
            return

        self._last_sync_time = now

        # Refresh dynamic model catalog on each reload / sync
        asyncio.create_task(self.reload_available_models())

        for account in self.account_manager.list_accounts():
            if not account.enabled:
                continue
            try:
                await self.sync_account_quota(account)
            except Exception as e:
                logger.warning("Failed to sync quota for %s: %s", account.email, e)

    async def sync_account_quota(self, account: Account):
        """Fetch real-time quota status and tier for a specific account."""
        token = await self.account_manager.get_valid_access_token(account)
        try:
            quota_data = await self.client.fetch_quota_summary(token)
            account.quota_summary = quota_data
            account.quota_updated_at = time.time()

            # Inspect tiers
            try:
                code_assist = await self.client.load_code_assist(token)
                curr_tier = code_assist.get("currentTier", {})
                account.tier = curr_tier.get("name") or curr_tier.get("id") or "Free Tier"
            except Exception:
                pass

            # Update status based on quota summary
            groups = quota_data.get("groups", [])
            has_any_quota = False
            earliest_reset = 0.0

            for grp in groups:
                buckets = grp.get("buckets", [])
                for b in buckets:
                    rem = b.get("remainingFraction", 1.0)
                    reset_time = parse_rfc3339_timestamp(b.get("resetTime"))
                    if rem > 0.001:
                        has_any_quota = True
                    else:
                        if reset_time > time.time():
                            if earliest_reset == 0.0 or reset_time < earliest_reset:
                                earliest_reset = reset_time

            if has_any_quota:
                if account.status == "exhausted":
                    account.status = "active"
                    account.exhausted_until = 0
            else:
                account.status = "exhausted"
                account.exhausted_until = earliest_reset or (time.time() + 1800)

            self.account_manager.save()
        except Exception as e:
            logger.error("Error updating quota for %s: %s", account.email, e)
            raise

    def get_account_quota_fraction(self, account: Account, model_group: str) -> Tuple[float, float]:
        """
        Returns (remaining_fraction, reset_time) for the requested model group.
        model_group: 'gemini' or '3p' (Claude/GPT)
        """
        summary = account.quota_summary
        if not summary or "groups" not in summary:
            return (1.0, 0.0)

        min_fraction = 1.0
        earliest_reset = 0.0

        for grp in summary.get("groups", []):
            display_name = grp.get("displayName", "").lower()
            desc = grp.get("description", "").lower()

            is_match = False
            if model_group == "gemini" and ("gemini" in display_name or "gemini" in desc):
                is_match = True
            elif model_group == "3p" and ("claude" in display_name or "gpt" in display_name or "claude" in desc):
                is_match = True

            if is_match:
                for b in grp.get("buckets", []):
                    # If bucket is disabled, ignore it
                    if b.get("disabled", False):
                        continue
                    rem = float(b.get("remainingFraction", 1.0))
                    reset_ts = parse_rfc3339_timestamp(b.get("resetTime"))
                    if rem < min_fraction:
                        min_fraction = rem
                    if rem <= 0.001 and reset_ts > time.time():
                        if earliest_reset == 0.0 or reset_ts < earliest_reset:
                            earliest_reset = reset_ts

        return (min_fraction, earliest_reset)

    def get_candidate_accounts(self, model: str) -> List[Tuple[Account, float]]:
        """
        Return candidate accounts for a given model, sorted by available quota fraction (descending)
        and least-recently used.
        """
        model_group = get_model_group(model)
        candidates: List[Tuple[Account, float]] = []

        all_accounts = [acc for acc in self.account_manager.list_accounts() if acc.enabled]
        if not all_accounts:
            return []

        now = time.time()
        for acc in all_accounts:
            if acc.status == "error":
                continue
            if acc.is_exhausted():
                continue

            fraction, _ = self.get_account_quota_fraction(acc, model_group)
            if fraction > 0.001:
                candidates.append((acc, fraction))

        # Sort: highest quota fraction first; if equal fraction, least recently used first
        candidates.sort(key=lambda item: (item[1], -item[0].last_used), reverse=True)
        return candidates

    async def stream_with_failover(
        self,
        model: str,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[Dict[str, Any]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream generate content with automatic quota failover.
        If an account hits quota exhaustion / 429, fail over to the next healthy account.
        """
        # Periodic background sync
        asyncio.create_task(self.sync_all_quotas())

        model_group = get_model_group(model)
        candidates = self.get_candidate_accounts(model)

        if not candidates and model_group == "3p":
            from bridge.config import AUTO_FALLBACK_TO_GEMINI
            if AUTO_FALLBACK_TO_GEMINI:
                fallback_model = "gemini-3.8-flash-high"
                gemini_candidates = self.get_candidate_accounts(fallback_model)
                if gemini_candidates:
                    logger.warning(
                        "All accounts depleted quota for 3P model '%s'. Gracefully falling back to %s.",
                        model,
                        fallback_model,
                    )
                    model = fallback_model
                    candidates = gemini_candidates
                    model_group = "gemini"

        if not candidates:
            # Check if all accounts are exhausted
            all_accs = [acc for acc in self.account_manager.list_accounts() if acc.enabled]
            if not all_accs:
                raise RuntimeError("No Google Antigravity accounts configured. Please add an account first.")

            # Find when the soonest reset occurs
            soonest_reset = 0.0
            for acc in all_accs:
                _, reset_ts = self.get_account_quota_fraction(acc, model_group)
                if reset_ts > time.time():
                    if soonest_reset == 0.0 or reset_ts < soonest_reset:
                        soonest_reset = reset_ts

            mins_remaining = max(1, int((soonest_reset - time.time()) / 60)) if soonest_reset else 30
            raise QuotaExceededError(
                f"All configured accounts have exhausted their quota for model '{model}' ({model_group} group). "
                f"Soonest quota reset in ~{mins_remaining} minutes. Please add another Google account to continue."
            )

        attempted_accounts: List[str] = []
        last_error: Optional[Exception] = None

        for account, initial_fraction in candidates:
            attempted_accounts.append(account.email)
            logger.info(
                "Routing request for model '%s' to account %s (quota: %.1f%%)",
                model,
                account.email,
                initial_fraction * 100,
            )

            try:
                token = await self.account_manager.get_valid_access_token(account)
                stream = self.client.stream_generate_content(
                    access_token=token,
                    model=model,
                    contents=contents,
                    system_instruction=system_instruction,
                    generation_config=generation_config,
                    tools=tools,
                )

                first_chunk = True
                async for chunk in stream:
                    if first_chunk:
                        # Once first chunk arrives successfully, mark account as used
                        account.last_used = time.time()
                        self.account_manager.save()
                        first_chunk = False
                    yield chunk

                # Successful execution complete!
                return

            except (QuotaExceededError, RuntimeError) as e:
                err_str = str(e)
                is_quota_err = (
                    isinstance(e, QuotaExceededError)
                    or "429" in err_str
                    or "RESOURCE_EXHAUSTED" in err_str
                    or "quota" in err_str.lower()
                )

                if is_quota_err:
                    logger.warning(
                        "Quota reached on account %s for model '%s': %s. Marking exhausted and failing over...",
                        account.email,
                        model,
                        err_str,
                    )
                    account.status = "exhausted"
                    # Try to parse reset_time or default cooldown to 30 mins
                    _, reset_ts = self.get_account_quota_fraction(account, model_group)
                    account.exhausted_until = reset_ts or (time.time() + 1800)
                    self.account_manager.save()
                    last_error = e
                    # Loop will proceed to next candidate account!
                    continue
                else:
                    # Non-quota unexpected error: raise immediately
                    logger.error("Error on account %s: %s", account.email, err_str)
                    raise

        # If we exhausted all candidates
        raise QuotaExceededError(
            f"All {len(attempted_accounts)} candidate accounts failed or reached quota limits for model '{model}'. "
            f"Last error: {last_error}"
        )
