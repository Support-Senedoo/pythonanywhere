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
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024

    # Sans ceci, Jinja garde les gabarits compilés en mémoire : après un git pull sur PA, l’accueil
    # peut rester figé jusqu’à un Reload Web. On recharge les templates si les fichiers changent.
    _on_pa = any(k.startswith("PYTHONANYWHERE") for k in os.environ)
    _force_tpl = os.environ.get("TOOLBOX_TEMPLATE_AUTO_RELOAD", "").lower() in ("1", "true", "yes")
    app.config["TEMPLATES_AUTO_RELOAD"] = bool(app.config["DEBUG"] or _on_pa or _force_tpl)

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
