import asyncio
from collections import deque
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from bridge.config import DATA_DIR

LOG_FILE = DATA_DIR / "bridge.log"


class LogBufferHandler(logging.Handler):
    """
    Custom logging handler that buffers recent log entries in memory
    and broadcasts new records to active asyncio subscriber queues (for SSE).
    """
    def __init__(self, capacity: int = 2000):
        super().__init__()
        self.capacity = capacity
        self.buffer: deque = deque(maxlen=capacity)
        self.listeners: Set[asyncio.Queue] = set()
        self._next_id = 1

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            entry = {
                "id": self._next_id,
                "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "created": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "formatted": msg,
            }
            self._next_id += 1
            self.buffer.append(entry)

            # Broadcast to any active SSE subscribers
            if self.listeners:
                for queue in list(self.listeners):
                    try:
                        queue.put_nowait(entry)
                    except (asyncio.QueueFull, Exception):
                        pass
        except Exception:
            self.handleError(record)


# Global singleton instance
_log_buffer_handler = LogBufferHandler(capacity=2000)
_logging_configured = False


def setup_logging(level: int = logging.INFO) -> LogBufferHandler:
    """
    Configure global logging:
    - Console StreamHandler
    - RotatingFileHandler to bridge.log
    - LogBufferHandler for live in-memory web streaming
    """
    global _logging_configured, _log_buffer_handler
    if _logging_configured:
        return _log_buffer_handler

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _log_buffer_handler.setFormatter(formatter)
    _log_buffer_handler.setLevel(level)

    # Ensure log directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Rotating file handler (10 MB per file, 3 backups)
    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    # Attach to root logger and specific libraries
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers to prevent duplicates
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(_log_buffer_handler)

    # Capture uvicorn and httpx logs as well
    for lib in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "antigravity-bridge"):
        sub_logger = logging.getLogger(lib)
        sub_logger.setLevel(level)
        if _log_buffer_handler not in sub_logger.handlers:
            sub_logger.addHandler(_log_buffer_handler)
        if file_handler not in sub_logger.handlers:
            sub_logger.addHandler(file_handler)

    _logging_configured = True
    return _log_buffer_handler


def get_log_buffer_handler() -> LogBufferHandler:
    global _log_buffer_handler
    if not _logging_configured:
        setup_logging()
    return _log_buffer_handler


def get_recent_logs(
    limit: int = 200,
    level: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve filtered recent logs from in-memory buffer or disk."""
    handler = get_log_buffer_handler()
    items = list(handler.buffer)

    # If buffer is empty (e.g. server just restarted), read tail of LOG_FILE
    if not items and LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-limit:]
            for idx, line in enumerate(lines, 1):
                clean = line.strip()
                lvl = "INFO"
                for cand in ("ERROR", "WARNING", "DEBUG", "CRITICAL"):
                    if f"[{cand}]" in clean:
                        lvl = cand
                        break
                items.append({
                    "id": idx,
                    "timestamp": clean[:19] if len(clean) >= 19 else "",
                    "created": 0,
                    "level": lvl,
                    "logger": "bridge.disk",
                    "message": clean[20:] if len(clean) > 20 else clean,
                    "formatted": clean,
                })
        except Exception:
            pass

    if level and level.upper() != "ALL":
        items = [e for e in items if e.get("level", "").upper() == level.upper()]

    if search:
        search_lower = search.lower()
        items = [
            e for e in items
            if search_lower in e.get("message", "").lower()
            or search_lower in e.get("logger", "").lower()
            or search_lower in e.get("formatted", "").lower()
        ]

    return items[-limit:]


def clear_logs() -> bool:
    """Clear memory buffer and truncate the log file on disk."""
    handler = get_log_buffer_handler()
    handler.buffer.clear()
    try:
        if LOG_FILE.exists():
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] bridge.log: Logs cleared by user\n")
        return True
    except Exception:
        return False


def get_log_stats() -> Dict[str, Any]:
    """Calculate summary metrics for log monitor badges."""
    handler = get_log_buffer_handler()
    items = list(handler.buffer)

    total = len(items)
    errors = sum(1 for e in items if e.get("level") in ("ERROR", "CRITICAL"))
    warnings = sum(1 for e in items if e.get("level") == "WARNING")
    
    # Count failover / rotation events
    failovers = sum(
        1 for e in items
        if "failing over" in e.get("message", "").lower()
        or "failover" in e.get("message", "").lower()
        or "quota reached" in e.get("message", "").lower()
        or "rotated" in e.get("message", "").lower()
    )

    # Count agent requests
    requests = sum(
        1 for e in items
        if "HTTP Request" in e.get("message", "")
        or "Routing request" in e.get("message", "")
        or "/v1/chat/completions" in e.get("message", "")
        or "/v1/messages" in e.get("message", "")
    )

    return {
        "total": total,
        "errors": errors,
        "warnings": warnings,
        "failovers": failovers,
        "requests": requests,
        "log_file": str(LOG_FILE),
        "log_size_bytes": LOG_FILE.stat().st_size if LOG_FILE.exists() else 0,
    }


async def subscribe_logs() -> asyncio.Queue:
    """Register a new asyncio Queue to receive real-time log entries."""
    handler = get_log_buffer_handler()
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    handler.listeners.add(queue)
    return queue


def unsubscribe_logs(queue: asyncio.Queue):
    """Unregister a subscriber queue."""
    handler = get_log_buffer_handler()
    handler.listeners.discard(queue)
