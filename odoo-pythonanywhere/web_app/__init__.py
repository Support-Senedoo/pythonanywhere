"""Application Flask toolbox (PythonAnywhere) : portails client / Senedoo."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask

_ROOT = Path(__file__).resolve().parent.parent


def create_app() -> Flask:
    _on_pa = any(k.startswith("PYTHONANYWHERE") for k in os.environ)
    _no_jinja_cache = os.environ.get("TOOLBOX_JINJA_NO_CACHE", "").lower() in ("1", "true", "yes")
    _fs_session_env = os.environ.get("TOOLBOX_FILESYSTEM_SESSION", "").lower() in (
        "1",
        "true",
        "yes",
    )
    # Sur PA, la session par défaut (cookie signé) embarque toute la charge utile ; après un utilitaire
    # (flash, préférences, gros messages) le Set-Cookie peut dépasser ce qu’accepte nginx/uWSGI → 502.
    # Sessions fichiers : seul l’id de session transite dans le cookie.
    _use_fs_session = _on_pa or _fs_session_env

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
    app.config["TOOLBOX_PORTFOLIO_CLIENTS_PATH"] = os.environ.get(
        "TOOLBOX_PORTFOLIO_CLIENTS_PATH", str(_ROOT / "toolbox_portfolio_clients.json")
    )
    # Fichier une ligne = client_id (base) choisi par le staff — lu par scripts/xmlrpc_toolbox_client.py
    app.config["TOOLBOX_STAFF_SELECTED_CLIENT_FILE"] = (
        (os.environ.get("TOOLBOX_STAFF_SELECTED_CLIENT_FILE") or "").strip()
        or str(_ROOT / ".toolbox_staff_selected_client")
    )
    app.config["DEBUG"] = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
    _users_p = Path(app.config["TOOLBOX_USERS_PATH"])
    app.config["TOOLBOX_PASSWORD_RESET_TOKENS_PATH"] = os.environ.get(
        "TOOLBOX_PASSWORD_RESET_TOKENS_PATH",
        str(_users_p.parent / "toolbox_password_reset_tokens.json"),
    )
    app.config["TOOLBOX_PUBLIC_BASE_URL"] = (os.environ.get("TOOLBOX_PUBLIC_BASE_URL") or "").rstrip("/")
    app.config["TOOLBOX_SMTP_HOST"] = (os.environ.get("TOOLBOX_SMTP_HOST") or "").strip()
    app.config["TOOLBOX_SMTP_PORT"] = int(os.environ.get("TOOLBOX_SMTP_PORT") or "587")
    app.config["TOOLBOX_SMTP_USER"] = (os.environ.get("TOOLBOX_SMTP_USER") or "").strip()
    app.config["TOOLBOX_SMTP_PASSWORD"] = os.environ.get("TOOLBOX_SMTP_PASSWORD") or ""
    app.config["TOOLBOX_MAIL_FROM"] = (os.environ.get("TOOLBOX_MAIL_FROM") or "").strip()

    if _use_fs_session:
        _sess_dir = _ROOT / ".flask_session"
        try:
            _sess_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        app.config["SESSION_TYPE"] = "filesystem"
        app.config["SESSION_FILE_DIR"] = str(_sess_dir)
        app.config["SESSION_USE_SIGNER"] = True
        app.config["SESSION_PERMANENT"] = False
        try:
            from flask_session import Session

            Session(app)
            app.config["TOOLBOX_SESSION_BACKEND"] = "filesystem"
        except ImportError:
            # Le worker WSGI utilise parfois un autre Python que `pip install --user` (ex. 3.11 vs 3.10) :
            # sans flask-session, l’app ne doit pas planter — retour session cookie (risque 502 si cookie énorme).
            print(
                "Toolbox: flask-session introuvable pour cet interpréteur Python — "
                "sessions cookie (réinstaller deps pour la même version que l’onglet Web).",
                file=sys.stderr,
            )
            app.config["TOOLBOX_SESSION_BACKEND"] = "cookie_fallback"

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
    from flask import request as _req, session as _sess

    @app.before_request
    def _clear_oversized_session() -> None:
        """Efface la session si le cookie entrant dépasse 4000 bytes (évite 502 uWSGI)."""
        raw = _req.cookies.get("session", "")
        if len(raw) > 4000:
            _sess.clear()

    @app.context_processor
    def _inject_toolbox_version() -> dict:
        return {
            "toolbox_version": app_version.TOOLBOX_APP_VERSION,
            "toolbox_version_date": app_version.TOOLBOX_APP_DATE,
            "toolbox_app_time": app_version.TOOLBOX_APP_TIME,
            "toolbox_app_label": app_version.TOOLBOX_APP_LABEL,
            "toolbox_git_revision": app_version.git_head_short(),
            "toolbox_senegal_datetime": app_version.toolbox_senegal_datetime_display(),
        }

    return app
