"""Espace client : appli La Ripaille (MVP) + liens outils catalogue."""
from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for

from web_app.blueprints.public import login_required_client
from web_app.client_apps import apps_for_template
from web_app.odoo_registry import (
    client_has_app,
    configs_for_same_host,
    load_clients_registry,
    registry_netloc,
)
from web_app.pointage_import_util import (
    ALLOWED_SUFFIX,
    parse_pointage_csv,
    safe_upload_filename,
)
from web_app.session_odoo import get_odoo_client_for_browser_client

bp = Blueprint("legacy", __name__)


@bp.route("/select-base", methods=["POST"])
@login_required_client
def select_client_base():
    reg = load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])
    cur = (session.get("client_id") or "").strip().lower()
    picked = (request.form.get("client_id") or "").strip().lower()
    if cur not in reg or picked not in reg:
        flash("Choix de base invalide.", "danger")
        return redirect(url_for("legacy.client_home"))
    if registry_netloc(reg[picked]).lower() != registry_netloc(reg[cur]).lower():
        flash("Cette base n’est pas autorisée pour votre compte.", "danger")
        return redirect(url_for("legacy.client_home"))
    session["client_id"] = picked
    flash("Base active mise à jour.", "success")
    nxt = (request.form.get("next") or "").strip()
    if nxt.startswith("/client/") and not nxt.startswith("//"):
        return redirect(nxt)
    return redirect(url_for("legacy.client_home"))


@bp.route("/")
@login_required_client
def client_home():
    cid = (session.get("client_id") or "").strip().lower() or None
    reg = load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])
    cfg = reg.get(cid) if cid else None
    client_label = cfg.db if cfg else (cid or "—")
    registry_ok = bool(cfg)
    client_apps = apps_for_template(cfg.apps) if cfg else []
    base_choices: list[dict] = []
    if cfg:
        sibs = configs_for_same_host(reg, registry_netloc(cfg))
        if len(sibs) > 1:
            for sid, scfg in sorted(
                sibs,
                key=lambda x: (
                    0 if x[1].environment == "production" else 1,
                    x[0].lower(),
                ),
            ):
                base_choices.append(
                    {
                        "id": sid,
                        "environment": scfg.environment,
                        "db": scfg.db,
                        "current": sid == cid,
                    }
                )
    return render_template(
        "client/home.html",
        client_label=client_label,
        client_id=cid,
        registry_ok=registry_ok,
        client_apps=client_apps,
        base_choices=base_choices,
    )


@bp.route("/odoo-status")
@login_required_client
def client_odoo_status():
    cid = (session.get("client_id") or "").strip().lower() or None
    reg = load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])
    cfg = reg.get(cid) if cid else None
    if not cfg or not client_has_app(cfg, "odoo_status"):
        abort(404)
    client_label = cfg.db if cfg else (cid or "client")
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


@bp.route("/import-pointage", methods=["GET", "POST"])
@login_required_client
def client_pointage_import():
    cid = (session.get("client_id") or "").strip().lower() or None
    reg = load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])
    cfg = reg.get(cid) if cid else None
    if not cfg or not client_has_app(cfg, "pointage_import"):
        abort(404)
    client_label = cfg.db
    ctx = f"Base : {client_label}"

    columns: list[str] = []
    preview_rows: list[dict[str, str]] = []
    parse_errors: list[str] = []
    total_rows: int | None = None
    last_filename = ""

    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choisissez un fichier CSV.", "warning")
        else:
            name = safe_upload_filename(f.filename)
            low = name.lower()
            if not low.endswith(ALLOWED_SUFFIX):
                flash("Extension acceptée : .csv ou .txt.", "warning")
            else:
                raw = f.read()
                columns, preview_rows, parse_errors, total_rows = parse_pointage_csv(raw)
                last_filename = name
                if total_rows > 0 and not parse_errors:
                    flash(f"Fichier analysé : {total_rows} ligne(s) de données.", "success")
                elif total_rows > 0:
                    flash(f"Fichier lu : {total_rows} ligne(s), avec avertissements.", "warning")

    return render_template(
        "pointage_import.html",
        context_label=ctx,
        submit_action=url_for("legacy.client_pointage_import"),
        columns=columns,
        preview_rows=preview_rows,
        parse_errors=parse_errors,
        total_rows=total_rows,
        last_filename=last_filename,
    )
