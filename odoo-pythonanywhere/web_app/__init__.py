"""Application Flask toolbox (PythonAnywhere) : portails client / Senedoo."""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

_ROOT = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
        static_folder=str(Path(__file__).resolve().parent / "static"),
    )
    app.config["SECRET_KEY"] = os.environ.get("TOOLBOX_SECRET_KEY") or "CHANGE_ME_TOOLBOX_SECRET"
    app.config["TOOLBOX_USERS_PATH"] = os.environ.get(
        "TOOLBOX_USERS_PATH", str(_ROOT / "toolbox_users.json")
    )
    app.config["TOOLBOX_CLIENTS_PATH"] = os.environ.get(
        "TOOLBOX_CLIENTS_PATH", str(_ROOT / "toolbox_clients.json")
    )
    app.config["DEBUG"] = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")

    from web_app.blueprints.public import bp as public_bp
    from web_app.blueprints.legacy_client import bp as legacy_bp
    from web_app.blueprints.staff import bp as staff_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(legacy_bp, url_prefix="/client")
    app.register_blueprint(staff_bp, url_prefix="/staff")

    return app
