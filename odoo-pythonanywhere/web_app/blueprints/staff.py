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
from web_app import app_version
from web_app.client_apps import apps_for_template
from web_app.odoo_registry import client_has_app, load_clients_registry, upsert_client, validate_client_id
from web_app.odoo_account_probe import MAX_DATABASES_TO_PROBE, probe_account_databases
from web_app.pointage_import_util import (
    ALLOWED_SUFFIX,
    parse_pointage_csv,
    safe_upload_filename,
)
from odoo_client import OdooClient, normalize_odoo_base_url
from personalize_syscohada_detail import personalize_fix_detail_complete

from web_app.odoo_account_reports import (
    UTILITY_AUTHOR,
    UTILITY_DATE,
    UTILITY_TITLE,
    UTILITY_VERSION,
    duplicate_account_report,
    probe_odoo_reports_access,
    read_account_report_label,
    search_account_reports,
    unlink_account_report,
)
from web_app.session_odoo import get_config_by_id, get_xmlrpc_for_staff_client_id

bp = Blueprint("staff", __name__)


@bp.after_request
def _staff_disable_html_cache(response):
    """Évite qu’un vieux HTML staff (ancien formulaire, ancienne version) reste en cache navigateur après déploiement."""
    ct = response.headers.get("Content-Type", "")
    if "text/html" in ct:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


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


@bp.route("/utilities/odoo-compte-bases", methods=["GET", "POST"])
@login_required_staff
def odoo_account_databases_probe():
    result = None
    if request.method == "POST":
        url = (request.form.get("odoo_url") or "").strip()
        login = (request.form.get("odoo_login") or "").strip()
        password = (request.form.get("odoo_password") or "").strip()
        portal_cookie = (request.form.get("odoo_portal_session_cookie") or "").strip()
        if not login:
            flash("Login requis.", "warning")
        elif not url and not portal_cookie and not password:
            flash(
                "Pour le portail sans cookie de session, le mot de passe est requis. "
                "Ou collez le cookie après connexion manuelle sur odoo.com (voir aide).",
                "warning",
            )
        else:
            result = probe_account_databases(
                url,
                login,
                password,
                portal_session_cookie=portal_cookie or None,
            )
    return render_template(
        "staff/odoo_account_probe.html",
        result=result,
        max_probe=MAX_DATABASES_TO_PROBE,
        util_version=app_version.TOOLBOX_APP_VERSION,
        util_date=app_version.TOOLBOX_APP_DATE,
    )


@bp.route("/utilities/personalize-report", methods=["GET", "POST"])
@bp.route("/utilities/rapports-comptables", methods=["GET", "POST"])
@login_required_staff
def rapports_comptables():
    reg = _registry()

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        filter_q = (request.form.get("filter_q") or "").strip()

        if action == "add_client":
            clients_path = current_app.config["TOOLBOX_CLIENTS_PATH"]
            try:
                new_cid = validate_client_id(request.form.get("new_client_id") or "")
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(url_for("staff.rapports_comptables", q=filter_q or None))
            label = (request.form.get("new_label") or "").strip() or new_cid
            url = (request.form.get("new_url") or "").strip()
            db = (request.form.get("new_db") or "").strip()
            user = (request.form.get("new_user") or "").strip()
            password = (request.form.get("new_password") or "").strip() or None
            if not url or not db or not user:
                flash("URL, nom de base (db) et utilisateur Odoo sont requis.", "danger")
                return redirect(url_for("staff.rapports_comptables", q=filter_q or None))
            try:
                upsert_client(
                    clients_path,
                    new_cid,
                    label,
                    normalize_odoo_base_url(url),
                    db,
                    user,
                    password,
                    [],
                )
                flash(f"Base enregistrée : {label} (identifiant {new_cid}).", "success")
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(url_for("staff.rapports_comptables", q=filter_q or None))
            return redirect(
                url_for("staff.rapports_comptables", client_id=new_cid, q=filter_q or None)
            )

        cid = (request.form.get("client_id") or "").strip().lower()
        if cid not in reg:
            flash("Base / client inconnu.", "danger")
            return redirect(url_for("staff.rapports_comptables"))
        if action == "prefill":
            rid = (request.form.get("report_id") or "").strip()
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    client_id=cid,
                    q=filter_q,
                    report_id=rid or None,
                )
            )
        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(cid)
        except Exception as e:
            flash(f"Connexion impossible : {e!s}", "danger")
            return redirect(url_for("staff.rapports_comptables", client_id=cid, q=filter_q))
        if action == "personalize":
            try:
                rid = int(request.form.get("report_id") or "0")
            except ValueError:
                rid = 0
            if (request.form.get("confirm") or "").strip() != "OUI":
                flash("Tapez OUI en majuscules pour confirmer la personnalisation.", "warning")
                return redirect(
                    url_for(
                        "staff.rapports_comptables",
                        client_id=cid,
                        q=filter_q,
                        report_id=rid if rid > 0 else None,
                    )
                )
            if rid <= 0:
                flash("Indiquez un identifiant de rapport (account.report) valide.", "danger")
                return redirect(url_for("staff.rapports_comptables", client_id=cid, q=filter_q))
            try:
                new_rid = duplicate_account_report(models, db, uid, pwd, rid)
                personalize_fix_detail_complete(models, db, uid, pwd, new_rid)
                src_label = read_account_report_label(models, db, uid, pwd, rid)
                rlabel = read_account_report_label(models, db, uid, pwd, new_rid)
                flash(
                    f"Copie créée depuis le rapport id={rid} (« {src_label} »), puis personnalisée : "
                    f"nouveau rapport id={new_rid} (« {rlabel} »). L’original n’a pas été modifié.",
                    "success",
                )
            except Exception as e:
                flash(f"Échec personnalisation : {e!s}", "danger")
                return redirect(
                    url_for(
                        "staff.rapports_comptables",
                        client_id=cid,
                        q=filter_q,
                        report_id=rid if rid > 0 else None,
                    )
                )
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    client_id=cid,
                    q=filter_q,
                    report_id=new_rid,
                )
            )
        if action == "unlink":
            try:
                rid = int(request.form.get("report_id") or "0")
            except ValueError:
                rid = 0
            expected = f"SUPPRIMER-{rid}"
            if (request.form.get("confirm_delete") or "").strip() != expected:
                flash("Confirmation de suppression incorrecte.", "danger")
                return redirect(url_for("staff.rapports_comptables", client_id=cid, q=filter_q))
            if rid <= 0:
                flash("Identifiant de rapport invalide.", "danger")
                return redirect(url_for("staff.rapports_comptables", client_id=cid, q=filter_q))
            try:
                rlabel = read_account_report_label(models, db, uid, pwd, rid)
                unlink_account_report(models, db, uid, pwd, rid)
                flash(f"Rapport « {rlabel} » (id={rid}) supprimé.", "success")
            except Exception as e:
                flash(f"Suppression impossible : {e!s}", "danger")
            return redirect(url_for("staff.rapports_comptables", client_id=cid, q=filter_q))
        flash("Action non reconnue.", "warning")
        return redirect(url_for("staff.rapports_comptables", client_id=cid, q=filter_q))

    selected = (request.args.get("client_id") or "").strip().lower()
    if selected not in reg:
        selected = ""
    filter_q = (request.args.get("q") or "").strip()
    prefill_rid = request.args.get("report_id", type=int)

    conn_status = "idle"
    conn_detail = ""
    reports: list = []
    if selected:
        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(selected)
            ok, msg = probe_odoo_reports_access(models, db, uid, pwd)
            conn_detail = msg
            if ok:
                conn_status = "ok"
                reports = search_account_reports(models, db, uid, pwd, filter_q)
            else:
                conn_status = "error"
        except Exception as e:
            conn_status = "error"
            conn_detail = str(e)

    return render_template(
        "staff/accounting_reports_utility.html",
        clients=reg,
        selected_client=selected,
        filter_q=filter_q,
        conn_status=conn_status,
        conn_detail=conn_detail,
        reports=reports,
        prefill_report_id=prefill_rid,
        utility_title=UTILITY_TITLE,
        utility_version=UTILITY_VERSION,
        utility_date=UTILITY_DATE,
        utility_author=UTILITY_AUTHOR,
    )
