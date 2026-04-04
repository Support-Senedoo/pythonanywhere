"""Application Flask toolbox (PythonAnywhere) : portails client / Senedoo."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

_ROOT = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    _on_pa = any(k.startswith("PYTHONANYWHERE") for k in os.environ)
    _no_jinja_cache = os.environ.get("TOOLBOX_JINJA_NO_CACHE", "").lower() in ("1", "true", "yes")

    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    # Sur PA : cache_size=0 évite les gabarits Jinja « figés » après git pull (plus fiable que seul TEMPLATES_AUTO_RELOAD).
    if _no_jinja_cache or _on_pa:
        app.jinja_options = {**dict(app.jinja_options), "cache_size": 0}

    app.config["SECRET_KEY"] = os.environ.get("TOOLBOX_SECRET_KEY") or "CHANGE_ME_TOOLBOX_SECRET"
    app.config["TOOLBOX_USERS_PATH"] = os.environ.get(
        "TOOLBOX_USERS_PATH", str(_ROOT / "toolbox_users.json")
    )
    app.config["TOOLBOX_CLIENTS_PATH"] = os.environ.get(
        "TOOLBOX_CLIENTS_PATH", str(_ROOT / "toolbox_clients.json")
    )
    app.config["DEBUG"] = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024

    # Relecture des .html si le fichier change (complément au cache_size=0 ci-dessus sur PA).
    _force_tpl = os.environ.get("TOOLBOX_TEMPLATE_AUTO_RELOAD", "").lower() in ("1", "true", "yes")
    app.config["TEMPLATES_AUTO_RELOAD"] = bool(app.config["DEBUG"] or _on_pa or _force_tpl or _no_jinja_cache)

    from web_app.blueprints.public import bp as public_bp
    from web_app.blueprints.legacy_client import bp as legacy_bp
    from web_app.blueprints.staff import bp as staff_bp
    from web_app.blueprints.staff_admin import bp as staff_admin_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(legacy_bp, url_prefix="/client")
    app.register_blueprint(staff_bp, url_prefix="/staff")
    app.register_blueprint(staff_admin_bp, url_prefix="/staff")

    from web_app import app_version

    @app.context_processor
    def _inject_toolbox_version() -> dict:
        return {
            "toolbox_version": app_version.TOOLBOX_APP_VERSION,
            "toolbox_version_date": app_version.TOOLBOX_APP_DATE,
            "toolbox_app_label": app_version.TOOLBOX_APP_LABEL,
            "toolbox_git_revision": app_version.git_head_short(),
        }

    return app
