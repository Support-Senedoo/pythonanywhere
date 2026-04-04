"""Espace client : appli La Ripaille (MVP) + liens outils catalogue."""
from __future__ import annotations

from flask import Blueprint, current_app, render_template, session

from web_app.blueprints.public import login_required_client
from web_app.odoo_registry import load_clients_registry
from web_app.session_odoo import get_odoo_client_for_browser_client

bp = Blueprint("legacy", __name__)


@bp.route("/")
@login_required_client
def client_home():
    cid = session.get("client_id")
    reg = load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])
    cfg = reg.get(cid) if cid else None
    client_label = cfg.label if cfg else (cid or "—")
    registry_ok = bool(cfg)
    return render_template(
        "client/home.html",
        client_label=client_label,
        client_id=cid,
        registry_ok=registry_ok,
    )


@bp.route("/odoo-status")
@login_required_client
def client_odoo_status():
    cid = session.get("client_id")
    reg = load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])
    cfg = reg.get(cid) if cid else None
    client_label = cfg.label if cfg else (cid or "client")
    try:
        c = get_odoo_client_for_browser_client()
        ver = c.version()
        c.authenticate()
        n = c.execute("res.partner", "search_count", [[]])
        lines = [
            f"Client : {client_label}",
            f"Version serveur : {ver.get('server_version', ver)}",
            "Authentification Odoo : OK",
            f"Nombre de partenaires (indicatif) : {n}",
        ]
    except Exception as e:
        lines = [
            f"Client : {client_label}",
            f"Erreur : {e!s}",
        ]
    return render_template("client/odoo_status.html", lines=lines, client_label=client_label)
