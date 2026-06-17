# Author: Systronaut
# Persistence: deployments + an append-only audit log.
#
# SQLite keeps the platform single-binary and Compose-friendly. The audit log is
# a compliance control in its own right (ISO 27001 A.8.15 logging, NIS2 21(2)(g))
# -- every state-changing action is recorded with actor, action and detail.

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from .models import Deployment, DeploymentSpec, DeploymentStatus, NetworkSpec, Provider


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS deployments (
    id            TEXT PRIMARY KEY,
    hostname      TEXT NOT NULL,
    os_key        TEXT NOT NULL,
    provider      TEXT NOT NULL,
    status        TEXT NOT NULL,
    data          TEXT NOT NULL,      -- full Deployment.to_dict() as JSON
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,
    target        TEXT,
    detail        TEXT
);
"""


class Store:
    """Thread-safe SQLite store. One connection guarded by a lock (Flask dev/gunicorn-sync)."""

    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # -- audit ----------------------------------------------------------------
    def audit(self, actor: str, action: str, target: str = "", detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log (ts, actor, action, target, detail) VALUES (?,?,?,?,?)",
                (_now(), actor, action, target, detail),
            )
            self._conn.commit()

    def audit_entries(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, actor, action, target, detail FROM audit_log "
                "ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- deployments ----------------------------------------------------------
    def create_deployment(self, spec: DeploymentSpec) -> Deployment:
        dep = Deployment(id=uuid.uuid4().hex[:12], spec=spec)
        dep.compliance_evidence = spec.compliance().to_evidence()
        self._save(dep, insert=True)
        return dep

    def _save(self, dep: Deployment, *, insert: bool = False) -> None:
        data = json.dumps(dep.to_dict())
        with self._lock:
            if insert:
                self._conn.execute(
                    "INSERT INTO deployments "
                    "(id, hostname, os_key, provider, status, data, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (dep.id, dep.spec.hostname, dep.spec.os_key, dep.spec.provider.value,
                     dep.status.value, data, dep.created_at, dep.updated_at),
                )
            else:
                self._conn.execute(
                    "UPDATE deployments SET status=?, data=?, updated_at=? WHERE id=?",
                    (dep.status.value, data, dep.updated_at, dep.id),
                )
            self._conn.commit()

    def save(self, dep: Deployment) -> None:
        self._save(dep, insert=False)

    def get(self, dep_id: str) -> Optional[Deployment]:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM deployments WHERE id=?", (dep_id,)).fetchone()
        return _from_row(row) if row else None

    def list(self, limit: int = 200) -> list[Deployment]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM deployments ORDER BY created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [_from_row(r) for r in rows]


def _from_row(row) -> Deployment:
    """Rehydrate a Deployment from its stored JSON."""
    d = json.loads(row["data"])
    s = d["spec"]
    net = NetworkSpec(**s["network"])
    spec = DeploymentSpec(
        hostname=s["hostname"], os_key=s["os_key"],
        provider=Provider(s["provider"]), security_profile=s["security_profile"],
        network=net, cpu=s["cpu"], memory_mb=s["memory_mb"], disk_gb=s["disk_gb"],
        requested_by=s.get("requested_by", "unknown"),
    )
    return Deployment(
        id=d["id"], spec=spec, status=DeploymentStatus(d["status"]),
        message=d.get("message", ""), compliance_evidence=d.get("compliance_evidence", {}),
        provider_ref=d.get("provider_ref", ""),
        created_at=d["created_at"], updated_at=d["updated_at"],
    )
