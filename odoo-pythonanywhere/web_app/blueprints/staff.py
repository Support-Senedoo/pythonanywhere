"""Espace Senedoo : choix client / apps + utilitaires (personnalisation rapport)."""
from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from web_app.blueprints.public import login_required_staff
from web_app.client_apps import apps_for_template
from web_app.odoo_registry import client_has_app, load_clients_registry
from web_app.pointage_import_util import (
    ALLOWED_SUFFIX,
    parse_pointage_csv,
    safe_upload_filename,
)
from odoo_client import OdooClient
from personalize_syscohada_detail import personalize_fix_detail_complete

from web_app.session_odoo import get_config_by_id, get_xmlrpc_for_staff_client_id

bp = Blueprint("staff", __name__)


def _registry():
    return load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])


def _require_staff_client_selected():
    cid = session.get("staff_selected_client_id")
    if not cid:
        flash("Choisissez d’abord un client (mode applications).", "warning")
        return None
    try:
        get_config_by_id(cid)
    except ValueError:
        flash("Client invalide.", "danger")
        return None
    return cid


@bp.route("/")
@login_required_staff
def staff_home():
    reg = _registry()
    return render_template(
        "staff/home.html",
        clients=reg,
        selected=session.get("staff_selected_client_id"),
    )


@bp.route("/select-client", methods=["POST"])
@login_required_staff
def select_client():
    cid = (request.form.get("client_id") or "").strip().lower()
    if not cid or cid not in _registry():
        flash("Client inconnu.", "danger")
        return redirect(url_for("staff.staff_home"))
    session["staff_selected_client_id"] = cid
    flash(f"Base active pour les applications : {_registry()[cid].label}", "success")
    return redirect(url_for("staff.apps_home"))


@bp.route("/apps")
@login_required_staff
def apps_home():
    reg = _registry()
    cid = session.get("staff_selected_client_id")
    label = None
    staff_apps: list[dict] = []
    if cid and cid in reg:
        label = reg[cid].label
        for row in apps_for_template(reg[cid].apps):
            if row.get("staff_endpoint"):
                staff_apps.append(row)
    return render_template(
        "staff/apps.html",
        clients=reg,
        selected=cid,
        selected_label=label,
        staff_apps=staff_apps,
    )


@bp.route("/apps/odoo-status")
@login_required_staff
def staff_apps_odoo_status():
    cid = _require_staff_client_selected()
    if not cid:
        return redirect(url_for("staff.apps_home"))
    try:
        cfg = get_config_by_id(cid)
        if not client_has_app(cfg, "odoo_status"):
            from flask import abort

            abort(404)
        c = OdooClient(cfg.url, cfg.db, cfg.user, cfg.password)
        ver = c.version()
        c.authenticate()
        n = c.execute("res.partner", "search_count", [[]])
        lines = [
            f"Client : {cfg.label}",
            f"Version serveur : {ver.get('server_version', ver)}",
            "Authentification Odoo : OK",
            f"Nombre de partenaires (indicatif) : {n}",
        ]
    except Exception as e:
        lines = [f"Erreur : {e!s}"]
    return render_template("staff/odoo_status.html", lines=lines)


@bp.route("/apps/pointage-import", methods=["GET", "POST"])
@login_required_staff
def staff_apps_pointage_import():
    cid = _require_staff_client_selected()
    if not cid:
        return redirect(url_for("staff.apps_home"))
    reg = _registry()
    cfg = reg.get(cid)
    if not cfg or not client_has_app(cfg, "pointage_import"):
        abort(404)
    ctx = f"Mode équipe · client : {cfg.label} · base {cfg.db}"

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
        submit_action=url_for("staff.staff_apps_pointage_import"),
        columns=columns,
        preview_rows=preview_rows,
        parse_errors=parse_errors,
        total_rows=total_rows,
        last_filename=last_filename,
    )


@bp.route("/utilities")
@login_required_staff
def utilities_home():
    reg = _registry()
    return render_template("staff/utilities.html", clients=reg)


@bp.route("/utilities/personalize-report", methods=["GET", "POST"])
@login_required_staff
def personalize_report():
    reg = _registry()
    if request.method == "POST":
        cid = (request.form.get("client_id") or "").strip()
        try:
            rid = int(request.form.get("report_id") or "0")
        except ValueError:
            rid = 0
        confirm = (request.form.get("confirm") or "").strip()
        if cid not in reg:
            flash("Base / client inconnu.", "danger")
            return redirect(url_for("staff.personalize_report"))
        if rid <= 0:
            flash("Indiquez un identifiant de rapport (account.report) valide.", "danger")
            return redirect(url_for("staff.personalize_report"))
        if confirm != "OUI":
            flash("Tapez OUI en majuscules pour confirmer.", "warning")
            return redirect(url_for("staff.personalize_report"))
        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(cid)
            personalize_fix_detail_complete(models, db, uid, pwd, rid)
            flash(
                f"Personnalisation appliquée sur « {reg[cid].label} » pour le rapport id={rid}.",
                "success",
            )
        except Exception as e:
            flash(f"Échec : {e!s}", "danger")
        return redirect(url_for("staff.personalize_report"))

    return render_template("staff/personalize_report.html", clients=reg)
