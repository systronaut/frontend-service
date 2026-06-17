# Author: Systronaut
# Authentication & authorization.
#   - Web UI : Flask session login, two roles (admin, operator).
#   - API    : Bearer token mapped to a role.
# Roles:
#   operator -> may view + create deployments (end users)
#   admin    -> operator + destroy + audit log + settings
# Password checks are constant-time; werkzeug hashes preferred over plaintext.

import hmac
from functools import wraps

from flask import session, request, redirect, url_for, jsonify, current_app

try:  # werkzeug ships with Flask; guard anyway.
    from werkzeug.security import check_password_hash
except Exception:  # pragma: no cover
    check_password_hash = None

ROLE_OPERATOR = "operator"
ROLE_ADMIN = "admin"
_ROLE_RANK = {ROLE_OPERATOR: 1, ROLE_ADMIN: 2}


def _const_eq(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


def authenticate(username: str, password: str):
    """Return a role string if credentials are valid, else None."""
    cfg = current_app.config
    candidates = [
        (cfg["ADMIN_USER"], cfg["ADMIN_PASSWORD"], cfg["ADMIN_PASSWORD_HASH"], ROLE_ADMIN),
        (cfg["OPERATOR_USER"], cfg["OPERATOR_PASSWORD"], cfg["OPERATOR_PASSWORD_HASH"], ROLE_OPERATOR),
    ]
    for user, pw, pw_hash, role in candidates:
        if not _const_eq(username, user):
            continue
        if pw_hash and check_password_hash is not None:
            if check_password_hash(pw_hash, password or ""):
                return role
        elif pw and _const_eq(password, pw):
            return role
    return None


def token_role(token: str):
    """Map an API bearer token to a role, or None."""
    cfg = current_app.config
    if cfg["API_ADMIN_TOKEN"] and _const_eq(token, cfg["API_ADMIN_TOKEN"]):
        return ROLE_ADMIN
    if cfg["API_OPERATOR_TOKEN"] and _const_eq(token, cfg["API_OPERATOR_TOKEN"]):
        return ROLE_OPERATOR
    return None


def current_actor() -> str:
    """Identity string for audit logging (web session or API token role)."""
    if session.get("user"):
        return f"{session['user']}({session.get('role')})"
    if getattr(request, "_api_role", None):
        return f"api:{request._api_role}"
    return "anonymous"


def _has_role(role: str, required: str) -> bool:
    return _ROLE_RANK.get(role, 0) >= _ROLE_RANK.get(required, 99)


def login_required(required_role: str = ROLE_OPERATOR):
    """Web guard: redirects to login; enforces minimum role."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            role = session.get("role")
            if not role:
                return redirect(url_for("web.login", next=request.path))
            if not _has_role(role, required_role):
                return ("Forbidden: insufficient role.", 403)
            return fn(*a, **kw)
        return wrapper
    return deco


def api_auth(required_role: str = ROLE_OPERATOR):
    """API guard: Bearer token, enforces minimum role, JSON 401/403."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            header = request.headers.get("Authorization", "")
            token = header[7:] if header.startswith("Bearer ") else ""
            role = token_role(token)
            if not role:
                return jsonify({"error": "unauthorized"}), 401
            if not _has_role(role, required_role):
                return jsonify({"error": "forbidden"}), 403
            request._api_role = role
            return fn(*a, **kw)
        return wrapper
    return deco
