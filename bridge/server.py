import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from bridge.account_manager import AccountManager
from bridge.adapters.anthropic_adapter import (
    generate_anthropic_response,
    stream_anthropic_response,
)
from bridge.adapters.openai_adapter import (
    generate_openai_response,
    get_openai_models_list,
    stream_openai_response,
)
from bridge.antigravity_client import AntigravityClient, QuotaExceededError
from bridge.config import DEFAULT_PORT
from bridge.log_manager import (
    LOG_FILE,
    clear_logs,
    get_log_stats,
    get_recent_logs,
    setup_logging,
    subscribe_logs,
    unsubscribe_logs,
)
from bridge.quota_router import QuotaRouter

# Setup centralized logging
setup_logging()
logger = logging.getLogger("antigravity-bridge.server")

app = FastAPI(
    title="Antigravity Multi-Account Bridge",
    description="Bridge for Hermes, Claude Code, Codex, and coding agents to Google Antigravity models.",
    version="1.0.0",
)

# Enable CORS for web apps and agents
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global services
account_manager = AccountManager()
antigravity_client = AntigravityClient()
quota_router = QuotaRouter(account_manager, antigravity_client)


@app.middleware("http")
async def log_incoming_requests(request: Request, call_next):
    # Log incoming agent & API calls (skip static index.html and frequent polling)
    path = request.url.path
    if path.startswith(("/v1/", "/auth/")) or (path.startswith("/api/") and not path.endswith("/stream")):
        logger.info("Incoming %s %s from %s", request.method, path, request.client.host if request.client else "unknown")
    return await call_next(request)


@app.on_event("startup")
async def startup_event():
    setup_logging()
    logger.info("Initializing Antigravity Multi-Account Bridge...")
    # Trigger dynamic model discovery and quota sync on boot
    asyncio.create_task(quota_router.reload_available_models())
    asyncio.create_task(quota_router.sync_all_quotas(force=True))


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Antigravity Bridge is running.</h1>")


# ---------------------------------------------------------------------------
# OpenAI-compatible API Endpoints (/v1)
# ---------------------------------------------------------------------------

@app.get("/v1/models")
async def list_models():
    return JSONResponse(content=get_openai_models_list())


@app.post("/api/models/reload")
async def reload_models():
    """Explicitly trigger live model detection from Google Antigravity."""
    models = await quota_router.reload_available_models()
    return JSONResponse(content={"status": "ok", "count": len(models), "models": models})


@app.get("/api/models")
async def get_dashboard_models():
    """Return all known and discovered models."""
    from bridge.config import get_all_known_models
    return JSONResponse(content={"models": get_all_known_models()})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception as e:
        logger.error("Failed to parse JSON in /v1/chat/completions: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    stream = body.get("stream", False)

    try:
        if stream:
            generator = stream_openai_response(quota_router, body)
            return StreamingResponse(
                generator,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            resp = await generate_openai_response(quota_router, body)
            return JSONResponse(content=resp)
    except QuotaExceededError as e:
        logger.warning("Quota error in chat_completions: %s", e)
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error("Error in chat_completions: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Anthropic Claude-compatible API Endpoints (/v1/messages)
# ---------------------------------------------------------------------------

@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    try:
        body = await request.json()
        try:
            (Path.home() / ".antigravity-bridge" / "hermes_debug.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
        except Exception:
            pass
    except Exception as e:
        logger.error("Failed to parse JSON in /v1/messages: %s", e)
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    stream = body.get("stream", False)

    try:
        if stream:
            generator = stream_anthropic_response(quota_router, body)
            return StreamingResponse(
                generator,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            resp = await generate_anthropic_response(quota_router, body)
            return JSONResponse(content=resp)
    except QuotaExceededError as e:
        logger.warning("Quota error in anthropic_messages: %s", e)
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error("Error in anthropic_messages: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# OAuth Onboarding Endpoints
# ---------------------------------------------------------------------------

@app.get("/auth/login")
async def auth_login(request: Request):
    # Determine base redirect URL
    host = request.headers.get("host", f"127.0.0.1:{DEFAULT_PORT}")
    scheme = request.url.scheme or "http"
    redirect_uri = f"{scheme}://{host}/auth/callback"
    auth_url = account_manager.get_authorization_url(redirect_uri)
    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def auth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return HTMLResponse(
            content=f"<h2>Google OAuth Authorization Failed</h2><p>{error}</p><a href='/'>Back to Dashboard</a>",
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            content="<h2>Missing code parameter</h2><a href='/'>Back to Dashboard</a>",
            status_code=400,
        )

    host = request.headers.get("host", f"127.0.0.1:{DEFAULT_PORT}")
    scheme = request.url.scheme or "http"
    redirect_uri = f"{scheme}://{host}/auth/callback"

    try:
        account = await account_manager.exchange_code(code, redirect_uri)
        # Fetch initial quota for new account
        asyncio.create_task(quota_router.sync_account_quota(account))
        return RedirectResponse(url="/?added=" + account.email)
    except Exception as e:
        logger.error("Failed to process OAuth callback: %s", e)
        return HTMLResponse(
            content=f"<h2>Error Adding Account</h2><p>{str(e)}</p><a href='/'>Back to Dashboard</a>",
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Management & Dashboard APIs
# ---------------------------------------------------------------------------

@app.get("/api/accounts")
async def get_accounts():
    accs = account_manager.list_accounts()
    return JSONResponse(content={"accounts": [acc.to_dict() for acc in accs]})


class ToggleRequest(BaseModel):
    enabled: bool


@app.post("/api/accounts/{email}/toggle")
async def toggle_account(email: str, body: ToggleRequest):
    success = account_manager.toggle_account(email, body.enabled)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok", "email": email, "enabled": body.enabled}


@app.delete("/api/accounts/{email}")
async def delete_account(email: str):
    success = account_manager.remove_account(email)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"status": "ok", "removed": email}


@app.post("/api/quotas/sync")
async def sync_quotas():
    await quota_router.sync_all_quotas(force=True)
    return {"status": "ok", "synced_at": asyncio.get_event_loop().time()}


# ---------------------------------------------------------------------------
# 1-Click Agent Setup APIs
# ---------------------------------------------------------------------------

class SetupRequest(BaseModel):
    target: str = "all"
    model: Optional[str] = None


@app.get("/api/setup/agents")
async def get_setup_agents(request: Request):
    from bridge.setup_manager import SetupManager
    port = request.url.port or DEFAULT_PORT
    setup_mgr = SetupManager(port=port)
    return JSONResponse(content={"agents": setup_mgr.detect_agents()})


@app.post("/api/setup/configure")
async def configure_agents(request: Request, body: SetupRequest):
    from bridge.setup_manager import SetupManager
    port = request.url.port or DEFAULT_PORT
    setup_mgr = SetupManager(port=port)
    target = body.target.lower()
    model = body.model

    if target in ("all", "*"):
        res = setup_mgr.configure_all(model=model)
    elif target == "claude":
        res = setup_mgr.configure_claude(model=model)
    elif target == "hermes":
        res = setup_mgr.configure_hermes(model=model)
    elif target == "aider":
        res = setup_mgr.configure_aider(model=model)
    elif target == "cursor":
        res = setup_mgr.configure_cursor(model=model)
    elif target in ("env", "system"):
        res = setup_mgr.configure_env()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown setup target: {target}")

    return JSONResponse(content={"status": "ok", "target": target, "result": res})


@app.post("/api/setup/revert")
async def revert_agents(request: Request, body: SetupRequest):
    from bridge.setup_manager import SetupManager
    port = request.url.port or DEFAULT_PORT
    setup_mgr = SetupManager(port=port)
    target = body.target.lower()

    if target in ("all", "*"):
        res = setup_mgr.revert_all()
    elif target == "claude":
        res = setup_mgr.revert_claude()
    elif target == "hermes":
        res = setup_mgr.revert_hermes()
    elif target == "aider":
        res = setup_mgr.revert_aider()
    elif target == "cursor":
        res = setup_mgr.revert_cursor()
    elif target in ("env", "system"):
        res = setup_mgr.revert_env()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown revert target: {target}")

    return JSONResponse(content={"status": "ok", "target": target, "result": res})


# ---------------------------------------------------------------------------
# Log Monitoring APIs
# ---------------------------------------------------------------------------

@app.get("/api/logs")
async def get_logs_endpoint(
    limit: int = 200,
    level: Optional[str] = None,
    search: Optional[str] = None,
):
    """Retrieve recent log events with optional level and keyword filtering."""
    logs = get_recent_logs(limit=limit, level=level, search=search)
    stats = get_log_stats()
    return JSONResponse(content={"logs": logs, "stats": stats})


@app.get("/api/logs/stats")
async def get_log_stats_endpoint():
    """Get log summary counts (total, errors, warnings, failovers, requests)."""
    return JSONResponse(content=get_log_stats())


@app.get("/api/logs/stream")
async def stream_logs_endpoint(request: Request):
    """Server-Sent Events (SSE) endpoint for real-time live log streaming."""
    queue = await subscribe_logs()

    async def event_generator():
        try:
            yield f": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    yield f": ping\n\n"
        finally:
            unsubscribe_logs(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/logs/download")
async def download_logs_endpoint():
    """Download the full bridge.log file."""
    from fastapi.responses import FileResponse
    if not LOG_FILE.exists():
        LOG_FILE.write_text("No logs recorded yet.\n", encoding="utf-8")
    return FileResponse(
        str(LOG_FILE),
        filename="antigravity-bridge.log",
        media_type="text/plain",
    )


@app.delete("/api/logs")
async def clear_logs_endpoint():
    """Clear memory log buffer and truncate bridge.log file."""
    success = clear_logs()
    return JSONResponse(content={"status": "ok" if success else "error"})


