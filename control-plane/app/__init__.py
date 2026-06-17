# Author: Systronaut
# Application factory for the Systronaut control plane.
# Wires config, persistence, providers, security headers, and blueprints.

import logging

from flask import Flask

from .config import Config
from .store import Store
from .service import DeployService
from . import providers


def _security_headers(resp):
    """Baseline hardening headers (web/security.md). Self-hosted assets only,
    so a strict CSP needs no third-party allowances."""
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if Config.SESSION_COOKIE_SECURE:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


def create_app(config_object: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    logging.basicConfig(level=logging.INFO)
    for warning in config_object.warnings():
        app.logger.warning("config: %s", warning)

    # Persistence + services on the app object (single instance per process).
    app.store = Store(app.config["DB_PATH"])
    app.deploy_service = DeployService(app.store)
    providers.init_providers()

    from .web.routes import web_bp
    from .api.routes import api_bp
    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")

    app.after_request(_security_headers)

    from . import version

    @app.context_processor
    def inject_version():
        # Cached (1h TTL) and failure-safe -> cheap to call on every page.
        return {"version_info": version.check()}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    return app
