"""Espace client : appli La Ripaille (MVP) + liens outils catalogue."""
from __future__ import annotations

from flask import Blueprint, render_template

from web_app.blueprints.public import login_required_client
from web_app.session_odoo import get_odoo_client_for_browser_client

bp = Blueprint("legacy", __name__)


@bp.route("/")
@login_required_client
def client_home():
    return render_template("client/home.html")


@bp.route("/odoo-status")
@login_required_client
def client_odoo_status():
    try:
        c = get_odoo_client_for_browser_client()
        ver = c.version()
        c.authenticate()
        n = c.execute("res.partner", "search_count", [[]])
        lines = [
            f"Version serveur : {ver.get('server_version', ver)}",
            "Authentification Odoo : OK",
            f"Nombre de partenaires (indicatif) : {n}",
        ]
    except Exception as e:
        lines = [f"Erreur : {e!s}"]
    return render_template("client/odoo_status.html", lines=lines)
