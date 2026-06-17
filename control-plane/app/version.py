# Author: Systronaut
# Version + update availability.
#
# The running version is read from APP_VERSION (baked into the image at build,
# from the repo VERSION file). The latest version is fetched from a configurable
# URL (UPDATE_CHECK_URL -> a plain-text VERSION endpoint, e.g. the raw VERSION on
# your git host). The result is cached so the UI check is cheap. All failures are
# swallowed: an update check must never break the console.

import os
import threading
import time
from datetime import datetime, timezone

import requests

CURRENT = os.environ.get("APP_VERSION", "0.0.0").strip()
UPDATE_CHECK_URL = os.environ.get("UPDATE_CHECK_URL", "").strip()
_CACHE_TTL = 3600  # seconds

_lock = threading.Lock()
_cache = {"latest": None, "checked_at": 0.0}


def _parse(v: str) -> tuple:
    """Best-effort semver tuple for comparison ('1.2.3' -> (1,2,3))."""
    parts = []
    for chunk in (v or "").lstrip("vV").split("."):
        num = "".join(c for c in chunk if c.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts[:3] or [0])


def _fetch_latest() -> str | None:
    if not UPDATE_CHECK_URL:
        return None
    try:
        resp = requests.get(UPDATE_CHECK_URL, timeout=4)
        if resp.status_code == 200:
            return resp.text.strip().splitlines()[0].strip()
    except requests.RequestException:
        return None
    return None


def check(force: bool = False) -> dict:
    """Return {current, latest, update_available, checked_at, configured}."""
    now = time.time()
    with _lock:
        stale = force or (now - _cache["checked_at"] > _CACHE_TTL)
        if stale:
            _cache["latest"] = _fetch_latest()
            _cache["checked_at"] = now
        latest = _cache["latest"]
        checked = _cache["checked_at"]
    available = bool(latest) and _parse(latest) > _parse(CURRENT)
    return {
        "current": CURRENT,
        "latest": latest,
        "update_available": available,
        "configured": bool(UPDATE_CHECK_URL),
        "checked_at": datetime.fromtimestamp(
            checked, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if checked else None,
    }
