# Author: Systronaut
# Configuration, sourced from environment. Secrets never live in code.
# Required secrets are validated at startup (fail fast) -- see warnings().

import os
import secrets


class Config:
    # Flask session signing key. A random one is generated if unset so dev works,
    # but production MUST set CONTROL_PLANE_SECRET (warned in warnings()).
    SECRET_KEY = os.environ.get("CONTROL_PLANE_SECRET") or secrets.token_hex(32)
    _SECRET_FROM_ENV = bool(os.environ.get("CONTROL_PLANE_SECRET"))

    # Persistence.
    DB_PATH = os.environ.get("CONTROL_PLANE_DB", "/data/control-plane.db")

    # PXE engine (real provider target).
    PXE_ENGINE_URL = os.environ.get("PXE_ENGINE_URL", "http://pxe-engine:8081")
    PXE_ENGINE_TOKEN = os.environ.get("PXE_ENGINE_TOKEN", "")

    # Web UI accounts (role-based). Format for *_PASSWORD is plaintext compared in
    # constant time; *_PASSWORD_HASH (werkzeug) takes precedence if set.
    ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
    ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
    OPERATOR_USER = os.environ.get("OPERATOR_USER", "operator")
    OPERATOR_PASSWORD = os.environ.get("OPERATOR_PASSWORD", "")
    OPERATOR_PASSWORD_HASH = os.environ.get("OPERATOR_PASSWORD_HASH", "")

    # API bearer tokens by role.
    API_ADMIN_TOKEN = os.environ.get("API_ADMIN_TOKEN", "")
    API_OPERATOR_TOKEN = os.environ.get("API_OPERATOR_TOKEN", "")

    # Cookie hardening.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    @classmethod
    def warnings(cls) -> list[str]:
        """Startup misconfiguration warnings (logged, non-fatal in dev)."""
        out = []
        if not cls._SECRET_FROM_ENV:
            out.append("CONTROL_PLANE_SECRET not set: using an ephemeral key "
                       "(sessions reset on restart).")
        if not (cls.ADMIN_PASSWORD or cls.ADMIN_PASSWORD_HASH):
            out.append("No admin password set (ADMIN_PASSWORD / ADMIN_PASSWORD_HASH): "
                       "the admin account is DISABLED until configured.")
        return out
