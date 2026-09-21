import asyncio
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import urllib.parse
import httpx

from bridge.config import (
    ACCOUNTS_FILE,
    GOOGLE_OAUTH_AUTH_URL,
    GOOGLE_OAUTH_CLIENT_ID,
    GOOGLE_OAUTH_CLIENT_SECRET,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_OAUTH_TOKEN_URL,
)

logger = logging.getLogger("antigravity-bridge.account_manager")


class Account:
    def __init__(
        self,
        email: str,
        refresh_token: str,
        access_token: str = "",
        token_expiry: float = 0,
        name: str = "",
        tier: str = "unknown",
        enabled: bool = True,
        created_at: float = 0,
        last_used: float = 0,
        quota_summary: Optional[Dict[str, Any]] = None,
        quota_updated_at: float = 0,
        status: str = "active",
        exhausted_until: float = 0,
    ):
        self.email = email
        self.refresh_token = refresh_token
        self.access_token = access_token
        self.token_expiry = token_expiry
        self.name = name or email
        self.tier = tier
        self.enabled = enabled
        self.created_at = created_at or time.time()
        self.last_used = last_used or time.time()
        self.quota_summary = quota_summary or {}
        self.quota_updated_at = quota_updated_at
        self.status = status
        self.exhausted_until = exhausted_until

    def to_dict(self) -> Dict[str, Any]:
        return {
            "email": self.email,
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
            "token_expiry": self.token_expiry,
            "name": self.name,
            "tier": self.tier,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "quota_summary": self.quota_summary,
            "quota_updated_at": self.quota_updated_at,
            "status": self.status,
            "exhausted_until": self.exhausted_until,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Account":
        return cls(
            email=data.get("email", ""),
            refresh_token=data.get("refresh_token", ""),
            access_token=data.get("access_token", ""),
            token_expiry=data.get("token_expiry", 0),
            name=data.get("name", ""),
            tier=data.get("tier", "unknown"),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", 0),
            last_used=data.get("last_used", 0),
            quota_summary=data.get("quota_summary", {}),
            quota_updated_at=data.get("quota_updated_at", 0),
            status=data.get("status", "active"),
            exhausted_until=data.get("exhausted_until", 0),
        )

    def is_token_expired(self) -> bool:
        # Buffer of 120 seconds
        return time.time() >= (self.token_expiry - 120)

    def is_exhausted(self) -> bool:
        if self.exhausted_until > time.time():
            return True
        if self.status == "exhausted" and self.exhausted_until <= time.time():
            self.status = "active"
            self.exhausted_until = 0
            return False
        return self.status == "exhausted"


class AccountManager:
    def __init__(self, accounts_file: Path = ACCOUNTS_FILE):
        self.accounts_file = accounts_file
        self.accounts: Dict[str, Account] = {}
        self._lock = asyncio.Lock()
        self.load()
        self.auto_import_local_account()

    def load(self):
        if self.accounts_file.exists():
            try:
                with open(self.accounts_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("accounts", []):
                        acc = Account.from_dict(item)
                        if acc.email:
                            self.accounts[acc.email] = acc
                logger.info("Loaded %d account(s) from %s", len(self.accounts), self.accounts_file)
            except Exception as e:
                logger.error("Failed to load accounts file: %s", e)

    def save(self):
        try:
            self.accounts_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.accounts_file.with_suffix(".tmp")
            data = {"accounts": [acc.to_dict() for acc in self.accounts.values()]}
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(self.accounts_file)
        except Exception as e:
            logger.error("Failed to save accounts: %s", e)

    def auto_import_local_account(self) -> Optional[Account]:
        """Automatically import the existing Antigravity account from Windows Credential Manager."""
        if os.name != "nt":
            return None

        try:
            class CREDENTIAL(ctypes.Structure):
                _fields_ = [
                    ('Flags', wintypes.DWORD),
                    ('Type', wintypes.DWORD),
                    ('TargetName', wintypes.LPWSTR),
                    ('Comment', wintypes.LPWSTR),
                    ('LastWritten', wintypes.FILETIME),
                    ('CredentialBlobSize', wintypes.DWORD),
                    ('CredentialBlob', ctypes.POINTER(ctypes.c_char)),
                    ('Persist', wintypes.DWORD),
                    ('AttributeCount', wintypes.DWORD),
                    ('Attributes', ctypes.c_void_p),
                    ('TargetAlias', wintypes.LPWSTR),
                    ('UserName', wintypes.LPWSTR),
                ]

            PCREDENTIAL = ctypes.POINTER(CREDENTIAL)
            pcred = PCREDENTIAL()
            if ctypes.windll.advapi32.CredReadW('gemini:antigravity', 1, 0, ctypes.byref(pcred)):
                blob = ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
                ctypes.windll.advapi32.CredFree(pcred)
                data = json.loads(blob.decode('utf-8'))
                
                # Extract claims
                email = ""
                id_token = data.get("id_token")
                if id_token:
                    parts = id_token.split(".")
                    if len(parts) >= 2:
                        payload = parts[1] + "=" * (-len(parts[1]) % 4)
                        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
                        email = claims.get("email", "")

                tok = data.get("token", {})
                refresh_token = tok.get("refresh_token")
                access_token = tok.get("access_token", "")

                if email and refresh_token:
                    if email not in self.accounts:
                        acc = Account(
                            email=email,
                            refresh_token=refresh_token,
                            access_token=access_token,
                            token_expiry=time.time() + 3600,
                            name=email.split("@")[0],
                            status="active"
                        )
                        self.accounts[email] = acc
                        self.save()
                        logger.info("Successfully auto-imported Antigravity account: %s", email)
                        return acc
                    else:
                        # Update refresh token if needed
                        acc = self.accounts[email]
                        if refresh_token and acc.refresh_token != refresh_token:
                            acc.refresh_token = refresh_token
                            acc.access_token = access_token
                            acc.token_expiry = time.time() + 3600
                            self.save()
                        return acc
        except Exception as e:
            logger.debug("Could not auto-import Windows Credential Manager: %s", e)
        return None

    def get_authorization_url(self, redirect_uri: str, state: str = "") -> str:
        """Generate Google OAuth 2.0 authorization URL."""
        if not GOOGLE_OAUTH_CLIENT_ID:
            raise ValueError(
                "Google OAuth Client ID is not configured. Please set ANTIGRAVITY_CLIENT_ID "
                "in your environment, .env, or ~/.antigravity-bridge/credentials.json"
            )
        params = {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if state:
            params["state"] = state
        return f"{GOOGLE_OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Account:
        """Exchange authorization code for tokens and save new account."""
        if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
            raise ValueError(
                "Google OAuth credentials are not configured. Please set ANTIGRAVITY_CLIENT_ID "
                "and ANTIGRAVITY_CLIENT_SECRET in your environment, .env, or ~/.antigravity-bridge/credentials.json"
            )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_OAUTH_TOKEN_URL,
                data={
                    "client_id": GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15.0,
            )
            if resp.status_code != 200:
                raise ValueError(f"Failed to exchange OAuth code: {resp.text}")

            tokens = resp.json()
            access_token = tokens["access_token"]
            refresh_token = tokens.get("refresh_token")
            expires_in = tokens.get("expires_in", 3600)
            id_token = tokens.get("id_token")

            email = ""
            name = ""
            if id_token:
                parts = id_token.split(".")
                if len(parts) >= 2:
                    payload = parts[1] + "=" * (-len(parts[1]) % 4)
                    claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
                    email = claims.get("email", "")
                    name = claims.get("name", "")

            # If email was not in id_token, fetch from userinfo
            if not email:
                u_resp = await client.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10.0,
                )
                if u_resp.status_code == 200:
                    u_data = u_resp.json()
                    email = u_data.get("email", "")
                    name = u_data.get("name", "")

            if not email:
                raise ValueError("Could not determine account email from Google OAuth response")

            if not refresh_token:
                # If Google didn't return a new refresh token, check if we already had one
                existing = self.accounts.get(email)
                if existing and existing.refresh_token:
                    refresh_token = existing.refresh_token
                else:
                    raise ValueError(
                        "Google did not return a refresh token. Please re-authorize with prompt=consent."
                    )

            account = Account(
                email=email,
                refresh_token=refresh_token,
                access_token=access_token,
                token_expiry=time.time() + expires_in,
                name=name or email.split("@")[0],
                status="active",
            )

            async with self._lock:
                self.accounts[email] = account
                self.save()

            logger.info("Account %s added successfully via OAuth", email)
            return account

    async def get_valid_access_token(self, account: Account) -> str:
        """Return a valid access token, refreshing if expired."""
        if not account.is_token_expired() and account.access_token:
            return account.access_token

        async with self._lock:
            # Double check after acquiring lock
            if not account.is_token_expired() and account.access_token:
                return account.access_token

            logger.info("Refreshing access token for %s", account.email)
            if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
                err_msg = (
                    f"Cannot refresh token for {account.email}: Google OAuth client credentials "
                    "not configured. Please set ANTIGRAVITY_CLIENT_ID / ANTIGRAVITY_CLIENT_SECRET "
                    "or save credentials to ~/.antigravity-bridge/credentials.json"
                )
                logger.error(err_msg)
                account.status = "error"
                self.save()
                raise RuntimeError(err_msg)

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    GOOGLE_OAUTH_TOKEN_URL,
                    data={
                        "client_id": GOOGLE_OAUTH_CLIENT_ID,
                        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                        "refresh_token": account.refresh_token,
                        "grant_type": "refresh_token",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=15.0,
                )

                if resp.status_code != 200:
                    err_msg = f"Failed to refresh token for {account.email}: {resp.status_code} {resp.text}"
                    logger.error(err_msg)
                    account.status = "error"
                    self.save()
                    raise RuntimeError(err_msg)

                data = resp.json()
                account.access_token = data["access_token"]
                account.token_expiry = time.time() + data.get("expires_in", 3600)
                account.status = "active"
                self.save()
                return account.access_token

    def list_accounts(self) -> List[Account]:
        return list(self.accounts.values())

    def get_account(self, email: str) -> Optional[Account]:
        return self.accounts.get(email)

    def remove_account(self, email: str) -> bool:
        if email in self.accounts:
            del self.accounts[email]
            self.save()
            logger.info("Removed account: %s", email)
            return True
        return False

    def toggle_account(self, email: str, enabled: bool) -> bool:
        if email in self.accounts:
            self.accounts[email].enabled = enabled
            self.save()
            logger.info("Account %s enabled=%s", email, enabled)
            return True
        return False
