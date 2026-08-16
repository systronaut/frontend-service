# Author: Systronaut
# PXE engine API -- hardened replacement for the old dnsmasq-api.py.
#
# Security fixes vs. the original:
#   * NO os.system / shell string concatenation (was command-injectable).
#   * All inputs validated against strict regexes before they touch the FS.
#   * dnsmasq reservations written as discrete, atomically-replaced include
#     files (never appended to the global config).
#   * dnsmasq reloaded via subprocess with an argument list, not a shell.
#   * Bearer-token auth on every mutating endpoint.
#
# The engine serves the os_pxe_lab answer-file tree READ-ONLY as a content
# lookup (HTTP via nginx). It does NOT run ansible.

import hmac
import ipaddress
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)
log = logging.getLogger("pxe-engine")

# --- config (env) ------------------------------------------------------------
TOKEN = os.environ.get("PXE_ENGINE_TOKEN", "")
HOSTS_DIR = Path(os.environ.get("PXE_HOSTS_DIR", "/etc/dnsmasq.d/hosts"))
HTTP_ROOT = Path(os.environ.get("PXE_HTTP_ROOT", "/var/www/html"))
REGISTRY = Path(os.environ.get("PXE_REGISTRY", "/data/hosts.json"))
HOST_IP = os.environ.get("PXE_HOST_IP", "")
# Optional safety net for abandoned installs (Windows autounattend plaintext).
# Prefer deployment destroy → DELETE /hosts/{mac}. 0 = disabled.
try:
    HOST_FILE_TTL_SECONDS = int(os.environ.get("PXE_HOST_FILE_TTL_SECONDS", "0") or "0")
except ValueError:
    HOST_FILE_TTL_SECONDS = 0

_MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62})$")
_LEASE_RE = re.compile(r"^(infinite|\d+[smhd]?)$")
_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")   # answer_template / ipxe_chain lookups
_MECH_RE = re.compile(r"^[a-z_]+$")
_FNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")   # flat per-host filenames (no slashes)
_MAX_FILE_BYTES = 64 * 1024


def _err(msg, code=400):
    return jsonify({"error": msg}), code


def _authorized() -> bool:
    # Fail closed: with no token configured, every guarded endpoint denies.
    # (The process also refuses to start without a token -- see __main__.)
    if not TOKEN:
        return False
    header = request.headers.get("Authorization", "")
    return hmac.compare_digest(header.encode(), f"Bearer {TOKEN}".encode())


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _reload_dnsmasq() -> None:
    """SIGHUP dnsmasq to re-read include files. Arg list -> no shell."""
    try:
        out = subprocess.run(["pidof", "dnsmasq"], capture_output=True, text=True)
        for pid in out.stdout.split():
            os.kill(int(pid), signal.SIGHUP)
    except (ProcessLookupError, ValueError, FileNotFoundError):
        pass


def _load_registry() -> dict:
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_registry(reg: dict) -> None:
    _atomic_write(REGISTRY, json.dumps(reg, indent=2))


# --- validation --------------------------------------------------------------
def _validate(payload: dict) -> dict:
    mac = (payload.get("mac") or "").lower().replace("-", ":")
    if not _MAC_RE.match(mac):
        raise ValueError("invalid mac")
    hostname = (payload.get("hostname") or "").lower()
    if not _HOST_RE.match(hostname):
        raise ValueError("invalid hostname")
    lease = payload.get("lease") or "12h"
    if not _LEASE_RE.match(lease):
        raise ValueError("invalid lease")
    ip = payload.get("ip") or ""
    if ip:
        ipaddress.IPv4Address(ip)  # raises on bad input
    chain = payload.get("ipxe_chain") or ""
    answer = payload.get("answer_template") or ""
    for p in (chain, answer):
        if p and (not _PATH_RE.match(p) or ".." in p):
            raise ValueError("invalid lookup path")
    hardening = [m for m in (payload.get("hardening") or []) if _MECH_RE.match(str(m))]
    # Backend-rendered per-host files {flat_filename: content}. Validated strictly.
    raw_files = payload.get("files") or {}
    if not isinstance(raw_files, dict):
        raise ValueError("files must be an object")
    files = {}
    for name, content in raw_files.items():
        if not _FNAME_RE.match(str(name)) or ".." in str(name):
            raise ValueError(f"invalid filename: {name!r}")
        if not isinstance(content, str) or len(content.encode()) > _MAX_FILE_BYTES:
            raise ValueError(f"invalid/oversized content for {name!r}")
        files[name] = content
    return {"mac": mac, "hostname": hostname, "lease": lease, "ip": ip,
            "ipxe_chain": chain, "answer_template": answer, "hardening": hardening,
            "domain": (payload.get("domain") or ""), "files": files}


def _host_dir(slug: str) -> Path:
    return HTTP_ROOT / "host" / slug


def _purge_host_dir(slug: str) -> None:
    """Remove rendered per-host files (incl. Windows autounattend plaintext)."""
    path = _host_dir(slug)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        log.info("purged host files under %s", path)


def _delete_host_artifacts(mac: str) -> None:
    """Drop dnsmasq include + HTTP host/<slug>/ for one MAC."""
    slug = mac.replace(":", "-")
    (HOSTS_DIR / f"{slug}.conf").unlink(missing_ok=True)
    _purge_host_dir(slug)


def _purge_stale_host_dirs() -> int:
    """TTL safety net for abandoned installs. Returns number of dirs removed."""
    if HOST_FILE_TTL_SECONDS <= 0:
        return 0
    root = HTTP_ROOT / "host"
    if not root.is_dir():
        return 0
    cutoff = time.time() - HOST_FILE_TTL_SECONDS
    removed = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
            log.warning("TTL purged stale host dir %s (age > %ss)",
                        child.name, HOST_FILE_TTL_SECONDS)
    return removed


def _render_host_files(v: dict) -> None:
    mac = v["mac"]
    slug = mac.replace(":", "-")

    # 1) dnsmasq reservation as its own include file (validated, atomic).
    parts = [mac]
    if v["ip"]:
        parts.append(v["ip"])
    parts.append(v["hostname"])
    parts.append(v["lease"])
    parts.append(f"set:{slug}")
    reservation = f"dhcp-host={','.join(parts)}\n"
    _atomic_write(HOSTS_DIR / f"{slug}.conf", reservation)

    # 2) per-host files. The control plane renders these with Jinja2 and sends
    #    them here; the engine only persists/serves them (validated upstream).
    host_dir = _host_dir(slug)
    if v["files"]:
        for name, content in v["files"].items():
            _atomic_write(host_dir / name, content)
    else:
        # Fallback render (e.g. a client that does not send files): minimal chain.
        base = f"http://{HOST_IP}" if HOST_IP else "http://${next-server}"
        _atomic_write(host_dir / "boot.ipxe",
                      f"#!ipxe\n# host {v['hostname']} ({mac})\n"
                      f"chain {base}/lookup/{v['ipxe_chain']}\n")
        flags = "".join(f"HARDEN_{m.upper()}=1\n" for m in v["hardening"])
        _atomic_write(host_dir / "hardening.env",
                      f"# Security controls for {v['hostname']}\n"
                      f"CIS_LINUX_URL={base}/hardening/cis-linux.sh\n"
                      f"CIS_WINDOWS_URL={base}/hardening/cis-windows.ps1\n{flags}")


# --- routes ------------------------------------------------------------------
@app.get("/api/v1/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/v1/hosts")
def add_host():
    if not _authorized():
        return _err("unauthorized", 401)
    try:
        v = _validate(request.get_json(force=True, silent=True) or {})
    except (ValueError, ipaddress.AddressValueError) as exc:
        return _err(f"validation: {exc}")
    _purge_stale_host_dirs()
    _render_host_files(v)
    reg = _load_registry()
    reg[v["mac"]] = {"hostname": v["hostname"], "os": v.get("ipxe_chain", ""),
                     "status": "scheduled"}
    _save_registry(reg)
    _reload_dnsmasq()
    return jsonify({"mac": v["mac"], "status": "scheduled"}), 201


@app.get("/api/v1/hosts/<mac>")
def get_host(mac):
    if not _authorized():
        return _err("unauthorized", 401)
    mac = mac.lower().replace("-", ":")
    reg = _load_registry()
    if mac not in reg:
        return _err("not found", 404)
    return jsonify(reg[mac])


@app.delete("/api/v1/hosts")
def delete_hosts_by_hostname():
    """DELETE /api/v1/hosts?hostname=foo — scrub by hostname when MAC unknown.

    Used by HV destroy paths (e.g. vSphere-generated MAC) so Windows
    autounattend.xml and other rendered answers do not linger on the engine.
    """
    if not _authorized():
        return _err("unauthorized", 401)
    hostname = (request.args.get("hostname") or "").lower()
    if not hostname or not _HOST_RE.match(hostname):
        return _err("hostname query required")
    reg = _load_registry()
    removed = []
    for mac, info in list(reg.items()):
        if (info.get("hostname") or "").lower() == hostname:
            _delete_host_artifacts(mac)
            reg.pop(mac, None)
            removed.append(mac)
    if removed:
        _save_registry(reg)
        _reload_dnsmasq()
    return jsonify({"removed": removed}), 200


@app.delete("/api/v1/hosts/<mac>")
def delete_host(mac):
    if not _authorized():
        return _err("unauthorized", 401)
    mac = mac.lower().replace("-", ":")
    if not _MAC_RE.match(mac):
        return _err("invalid mac")
    _delete_host_artifacts(mac)
    reg = _load_registry()
    reg.pop(mac, None)
    _save_registry(reg)
    _reload_dnsmasq()
    return ("", 204)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("PXE_ENGINE_TOKEN is required (refusing to start unauthenticated).")
    app.run(host="0.0.0.0", port=8081)
