"""Espace Senedoo : choix client / apps + utilitaires (personnalisation rapport)."""
from __future__ import annotations

from typing import Any

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
from web_app.odoo_instance_info import collect_authenticated_instance_metadata
from web_app.odoo_registry import (
    client_has_app,
    clients_grouped_for_select,
    configs_for_label,
    connect_xmlrpc,
    distinct_client_labels,
    load_clients_registry,
    upsert_client,
    validate_client_id,
)
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
    write_account_report_name,
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


def _rapports_url_params(
    *,
    client_id: str | None = None,
    q: str | None = None,
    report_id: int | None = None,
    filter_label: str | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if client_id:
        d["client_id"] = client_id
    qs = (q or "").strip()
    if qs:
        d["q"] = qs
    if report_id is not None and report_id > 0:
        d["report_id"] = report_id
    fl = (filter_label or "").strip()
    if fl:
        d["filter_label"] = fl
    return d


@bp.route("/utilities/personalize-report", methods=["GET", "POST"])
@bp.route("/utilities/rapports-comptables", methods=["GET", "POST"])
@login_required_staff
def rapports_comptables():
    reg = _registry()

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        filter_q = (request.form.get("filter_q") or "").strip()
        filter_label_post = (request.form.get("filter_label") or "").strip()

        if action == "add_client":
            clients_path = current_app.config["TOOLBOX_CLIENTS_PATH"]
            try:
                new_cid = validate_client_id(request.form.get("new_client_id") or "")
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(
                    url_for("staff.rapports_comptables", **_rapports_url_params(q=filter_q, filter_label=filter_label_post))
                )
            label = (request.form.get("new_label") or "").strip() or new_cid
            url = (request.form.get("new_url") or "").strip()
            db = (request.form.get("new_db") or "").strip()
            user = (request.form.get("new_user") or "").strip()
            password = (request.form.get("new_password") or "").strip() or None
            if not url or not db or not user:
                flash("URL, nom de base (db) et utilisateur Odoo sont requis.", "danger")
                return redirect(
                    url_for("staff.rapports_comptables", **_rapports_url_params(q=filter_q, filter_label=filter_label_post))
                )
            env_raw = (request.form.get("new_environment") or "").strip().lower()
            env_kw = env_raw if env_raw in ("production", "test") else None
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
                    environment=env_kw,
                )
                flash(f"Base enregistrée : {label} (identifiant {new_cid}).", "success")
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(
                    url_for("staff.rapports_comptables", **_rapports_url_params(q=filter_q, filter_label=filter_label_post))
                )
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    **_rapports_url_params(
                        client_id=new_cid,
                        q=filter_q,
                        filter_label=filter_label_post or label,
                    ),
                )
            )

        cid = (request.form.get("client_id") or "").strip().lower()
        if cid not in reg:
            flash("Base / client inconnu.", "danger")
            return redirect(url_for("staff.rapports_comptables", **_rapports_url_params(q=filter_q, filter_label=filter_label_post)))
        if action == "prefill":
            rid = (request.form.get("report_id") or "").strip()
            try:
                rid_int = int(rid) if rid else 0
            except ValueError:
                rid_int = 0
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        report_id=rid_int if rid_int > 0 else None,
                        filter_label=reg[cid].label,
                    ),
                )
            )
        fl_save = reg[cid].label
        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(cid)
        except Exception as e:
            flash(f"Connexion impossible : {e!s}", "danger")
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
                )
            )
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
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            report_id=rid if rid > 0 else None,
                            filter_label=fl_save,
                        ),
                    )
                )
            if rid <= 0:
                flash("Indiquez un identifiant de rapport (account.report) valide.", "danger")
                return redirect(
                    url_for(
                        "staff.rapports_comptables",
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
                    )
                )
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
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            report_id=rid if rid > 0 else None,
                            filter_label=fl_save,
                        ),
                    )
                )
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        report_id=new_rid,
                        filter_label=fl_save,
                    ),
                )
            )
        if action == "rename_report":
            try:
                rid = int(request.form.get("report_id") or "0")
            except ValueError:
                rid = 0
            new_name = (request.form.get("new_report_name") or "").strip()
            if rid <= 0:
                flash("Identifiant de rapport invalide.", "danger")
                return redirect(
                    url_for(
                        "staff.rapports_comptables",
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
                    )
                )
            if not new_name:
                flash("Saisissez un nom pour le rapport.", "warning")
                return redirect(
                    url_for(
                        "staff.rapports_comptables",
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
                    )
                )
            try:
                write_account_report_name(models, db, uid, pwd, rid, new_name)
                flash(f"Rapport id={rid} renommé : « {new_name} ».", "success")
            except Exception as e:
                flash(f"Impossible de renommer le rapport : {e!s}", "danger")
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
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
                return redirect(
                    url_for(
                        "staff.rapports_comptables",
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
                    )
                )
            if rid <= 0:
                flash("Identifiant de rapport invalide.", "danger")
                return redirect(
                    url_for(
                        "staff.rapports_comptables",
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
                    )
                )
            try:
                rlabel = read_account_report_label(models, db, uid, pwd, rid)
                unlink_account_report(models, db, uid, pwd, rid)
                flash(f"Rapport « {rlabel} » (id={rid}) supprimé.", "success")
            except Exception as e:
                flash(f"Suppression impossible : {e!s}", "danger")
            return redirect(
                url_for(
                    "staff.rapports_comptables",
                    **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
                )
            )
        flash("Action non reconnue.", "warning")
        return redirect(
            url_for(
                "staff.rapports_comptables",
                **_rapports_url_params(client_id=cid, q=filter_q, filter_label=fl_save),
            )
        )

    selected = (request.args.get("client_id") or "").strip().lower()
    if selected not in reg:
        selected = ""
    filter_q = (request.args.get("q") or "").strip()
    prefill_rid = request.args.get("report_id", type=int)

    filter_label = (request.args.get("filter_label") or "").strip()
    valid_labels = {c.label for c in reg.values()}
    if filter_label and filter_label not in valid_labels:
        filter_label = ""
    if selected and filter_label and reg[selected].label != filter_label:
        selected = ""
    if selected and not filter_label:
        filter_label = reg[selected].label

    conn_status = "idle"
    conn_detail = ""
    reports: list = []
    instance_meta_rows: list[tuple[str, str]] = []
    label_picker_rows: list[dict[str, Any]] = []
    sibling_rows: list[dict[str, Any]] = []

    if filter_label and not selected:
        for cid, ccfg in configs_for_label(reg, filter_label):
            pr: dict[str, Any] = {"client_id": cid, "cfg": ccfg, "ok": False, "msg": ""}
            try:
                m, dbn, u, p = connect_xmlrpc(ccfg)
                okp, msgp = probe_odoo_reports_access(m, dbn, u, p)
                pr["ok"] = okp
                pr["msg"] = msgp
            except Exception as e:
                pr["msg"] = str(e)
            label_picker_rows.append(pr)

    if selected:
        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(selected)
            ok, msg = probe_odoo_reports_access(models, db, uid, pwd)
            conn_detail = msg
            if ok:
                conn_status = "ok"
                reports = search_account_reports(models, db, uid, pwd, filter_q)
                try:
                    instance_meta_rows = collect_authenticated_instance_metadata(
                        models, db, uid, pwd, reg[selected].url
                    )
                except Exception:
                    instance_meta_rows = []
            else:
                conn_status = "error"
        except Exception as e:
            conn_status = "error"
            conn_detail = str(e)

        sibs = configs_for_label(reg, reg[selected].label)
        if len(sibs) > 1:
            for cid, ccfg in sibs:
                sr: dict[str, Any] = {
                    "client_id": cid,
                    "cfg": ccfg,
                    "current": cid == selected,
                    "ok": False,
                    "msg": "",
                }
                if cid == selected:
                    sr["ok"] = conn_status == "ok"
                    sr["msg"] = conn_detail
                else:
                    try:
                        m, dbn, u, p = connect_xmlrpc(ccfg)
                        okp, msgp = probe_odoo_reports_access(m, dbn, u, p)
                        sr["ok"] = okp
                        sr["msg"] = msgp
                    except Exception as e:
                        sr["msg"] = str(e)
                sibling_rows.append(sr)

    return render_template(
        "staff/accounting_reports_utility.html",
        clients=reg,
        clients_grouped=clients_grouped_for_select(reg),
        distinct_client_labels=distinct_client_labels(reg),
        selected_client=selected,
        filter_label=filter_label,
        filter_q=filter_q,
        conn_status=conn_status,
        conn_detail=conn_detail,
        reports=reports,
        prefill_report_id=prefill_rid,
        label_picker_rows=label_picker_rows,
        sibling_rows=sibling_rows,
        instance_meta_rows=instance_meta_rows,
        utility_title=UTILITY_TITLE,
        utility_version=UTILITY_VERSION,
        utility_date=UTILITY_DATE,
        utility_author=UTILITY_AUTHOR,
    )
