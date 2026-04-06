"""Espace Senedoo : choix client / apps + utilitaires (personnalisation rapport)."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from web_app.blueprints.public import login_required_staff
from web_app import app_version
from web_app.client_apps import apps_for_template
from web_app.odoo_instance_info import collect_authenticated_instance_metadata
from web_app.odoo_registry import (
    client_has_app,
    clients_sorted_for_select,
    configs_for_same_host,
    connect_xmlrpc,
    distinct_odoo_hosts,
    load_clients_registry,
    normalize_registry_db_key,
    registry_netloc,
    upsert_client,
)
from web_app.odoo_account_probe import MAX_DATABASES_TO_PROBE, probe_account_databases
from web_app.pointage_import_util import (
    ALLOWED_SUFFIX,
    parse_pointage_csv,
    safe_upload_filename,
)
from odoo_client import OdooClient, normalize_odoo_base_url
from create_balance_6cols_via_api import (
    BALANCE_OHADA_NAME_FR,
    collect_balance_ohada_report_ids_for_cleanup,
    create_toolbox_balance_ohada,
    find_balance_ohada_report_id,
    purge_balance_ohada_instances,
    rewrite_toolbox_balance_ohada_aggregation_all_rpc,
    rewrite_toolbox_balance_ohada_outer_gross_all_rpc,
)
from personalize_pl_analytic_budget import (
    personalize_pl_analytic_budget_options,
    probe_financial_budget_analytic_summary,
)
from personalize_syscohada_detail import personalize_fix_detail_complete
from project_pl_analytic_report import (
    build_report,
    default_period_ytd,
    report_to_excel_bytes,
    search_analytic_accounts_for_select,
)

from web_app.odoo_account_reports import (
    UTILITY_AUTHOR,
    UTILITY_DATE,
    UTILITY_TITLE,
    UTILITY_TITLE_BALANCE,
    UTILITY_TITLE_PL_ANALYTIC_API,
    UTILITY_TITLE_PL_BUDGET,
    UTILITY_VERSION,
    account_report_backend_list_url,
    account_report_execution_url,
    account_report_odoo_form_url,
    duplicate_account_report,
    ensure_account_report_reporting_menu,
    find_account_report_backend_list_action_id,
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
    flash(f"Base active pour les applications : {_registry()[cid].db}", "success")
    return redirect(url_for("staff.apps_home"))


@bp.route("/apps")
@login_required_staff
def apps_home():
    reg = _registry()
    cid = session.get("staff_selected_client_id")
    label = None
    staff_apps: list[dict] = []
    if cid and cid in reg:
        label = reg[cid].db
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
            f"Base : {cfg.db}",
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
    ctx = f"Mode équipe · base {cfg.db}"

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


def _pl_analytic_url_params(
    *,
    client_id: str | None = None,
    filter_host: str | None = None,
    analytic_q: str | None = None,
    filter_q: str | None = None,
    report_id: int | None = None,
    add_base_only: bool = False,
) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if client_id:
        d["client_id"] = client_id
    fh = (filter_host or "").strip()
    if fh:
        d["filter_host"] = fh
    aq = (analytic_q or "").strip()
    if aq:
        d["aq"] = aq
    fq = (filter_q or "").strip()
    if fq:
        d["q"] = fq
    if report_id is not None and int(report_id) > 0:
        d["report_id"] = int(report_id)
    if add_base_only:
        d["add_base_only"] = "1"
    return d


_SESSION_PL_ANALYTIC = "staff_pl_analytic_prefs"


def _pl_analytic_prefs() -> dict[str, Any]:
    raw = session.get(_SESSION_PL_ANALYTIC)
    return dict(raw) if isinstance(raw, dict) else {}


def _pl_analytic_prefs_merge_save(**kwargs: Any) -> None:
    d = _pl_analytic_prefs()
    for k, v in kwargs.items():
        if v is None and k in (
            "last_created_report_id",
            "last_created_client_id",
        ):
            d.pop(k, None)
        else:
            d[k] = v
    session[_SESSION_PL_ANALYTIC] = d
    session.modified = True


def _pl_analytic_highlight_info(
    prefs: dict[str, Any],
    selected: str,
    reports: list[dict[str, Any]],
) -> tuple[int | None, bool]:
    """Dernière copie toolbox pour cette base : id + indique si absent du filtre courant."""
    cid = (prefs.get("last_created_client_id") or "").strip().lower()
    rid = prefs.get("last_created_report_id")
    try:
        rid_i = int(rid) if rid is not None else 0
    except (TypeError, ValueError):
        rid_i = 0
    if not selected or not cid or cid != selected or rid_i <= 0:
        return None, False
    ids_in = {int(r["id"]) for r in reports}
    if rid_i in ids_in:
        return rid_i, False
    return rid_i, True


@bp.route("/utilities/pl-analytique-projet", methods=["GET", "POST"])
@login_required_staff
def pl_analytic_project_report():
    """
    Compte de résultat analytique (réalisé / budget / %) : tableau généré à la volée
    via l’API (sans toucher aux rapports Odoo pour ce tableau).

    Sur la même page : copie personnalisée d’un ``account.report`` (comme « P&L analytique / budget ») :
    duplication, options analytique/budget, renommage et suppression de la copie.
    Période du tableau API = année civile en cours jusqu’à aujourd’hui (calcul serveur).
    """
    reg = _registry()

    def ru(**kwargs: Any) -> str:
        return url_for("staff.pl_analytic_project_report", **kwargs)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        filter_host_post = (request.form.get("filter_host") or "").strip()
        analytic_q_post = (request.form.get("analytic_q") or "").strip()
        filter_q_post = (request.form.get("filter_q") or "").strip()
        add_base_only_post = (request.form.get("add_base_only") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

        def _ru_err(
            client_id: str | None = None,
            filter_host_override: str | None = None,
        ):
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=client_id,
                        filter_host=filter_host_override
                        if filter_host_override is not None
                        else filter_host_post,
                        add_base_only=add_base_only_post,
                        analytic_q=analytic_q_post,
                        filter_q=filter_q_post,
                    ),
                ),
            )

        if action == "add_client":
            clients_path = current_app.config["TOOLBOX_CLIENTS_PATH"]
            url = (request.form.get("new_url") or "").strip()
            db = (request.form.get("new_db") or "").strip()
            user = (request.form.get("new_user") or "").strip()
            password = (request.form.get("new_password") or "").strip() or None
            try:
                new_cid = normalize_registry_db_key(db)
            except ValueError as e:
                flash(str(e), "danger")
                return _ru_err()
            if not url or not user:
                flash("URL et utilisateur Odoo sont requis.", "danger")
                return _ru_err()
            env_raw = (request.form.get("new_environment") or "").strip().lower()
            env_kw = env_raw if env_raw in ("production", "test") else None
            try:
                upsert_client(
                    clients_path,
                    new_cid,
                    new_cid,
                    normalize_odoo_base_url(url),
                    db,
                    user,
                    password,
                    [],
                    environment=env_kw,
                )
                flash(f"Base enregistrée : {new_cid}.", "success")
            except ValueError as e:
                flash(str(e), "danger")
                return _ru_err()
            net = urlparse(normalize_odoo_base_url(url)).netloc
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=new_cid,
                        filter_host=filter_host_post or net,
                        analytic_q=analytic_q_post,
                        filter_q=filter_q_post,
                    ),
                ),
            )

        cid = (request.form.get("client_id") or "").strip().lower()
        if cid not in reg:
            flash("Base / client inconnu.", "danger")
            return _ru_err()

        if action == "prefill":
            rid = (request.form.get("report_id") or "").strip()
            try:
                rid_int = int(rid) if rid else 0
            except ValueError:
                rid_int = 0
            _pl_analytic_prefs_merge_save(
                client_id=cid,
                filter_host=registry_netloc(reg[cid]),
                filter_q=filter_q_post,
                analytic_q=analytic_q_post,
            )
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=cid,
                        filter_q=filter_q_post,
                        analytic_q=analytic_q_post,
                        report_id=rid_int if rid_int > 0 else None,
                        filter_host=registry_netloc(reg[cid]),
                    ),
                ),
            )

        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(cid)
        except Exception as e:
            flash(f"Connexion impossible : {e!s}", "danger")
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=cid,
                        filter_host=registry_netloc(reg[cid]),
                        analytic_q=analytic_q_post,
                        filter_q=filter_q_post,
                    ),
                ),
            )

        fl_save = registry_netloc(reg[cid])
        _pl_analytic_prefs_merge_save(
            client_id=cid,
            filter_host=fl_save,
            filter_q=filter_q_post,
            analytic_q=analytic_q_post,
        )

        if action == "personalize_pl_budget":
            try:
                rid = int(request.form.get("report_id") or "0")
            except ValueError:
                rid = 0
            if rid <= 0:
                flash("Indiquez un identifiant de rapport (account.report) valide.", "danger")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_q=filter_q_post,
                            analytic_q=analytic_q_post,
                            filter_host=fl_save,
                        ),
                    ),
                )
            try:
                new_rid = duplicate_account_report(
                    models,
                    db,
                    uid,
                    pwd,
                    rid,
                    name_suffix=" — copie Senedoo (analytique budget)",
                )
                personalize_fix_detail_complete(models, db, uid, pwd, new_rid)
                opt = personalize_pl_analytic_budget_options(models, db, uid, pwd, new_rid)
                src_label = read_account_report_label(models, db, uid, pwd, rid)
                rlabel = read_account_report_label(models, db, uid, pwd, new_rid)
                written = ", ".join(f"{k}={v}" for k, v in opt["written"].items())
                flash(
                    f"P&L pilotage : copie id={new_rid} (« {rlabel} ») depuis id={rid} (« {src_label} »). "
                    f"Options rapport : {written}. "
                    f"Dans Odoo, sélectionnez un compte analytique et un budget puis vérifiez si la colonne budget "
                    f"se restreint (sinon voir DEPLOY_PYTHONANYWHERE.md — Studio / contournement).",
                    "success",
                )
            except Exception as e:
                flash(f"Échec personnalisation P&L analytique / budget : {e!s}", "danger")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_q=filter_q_post,
                            analytic_q=analytic_q_post,
                            report_id=rid if rid > 0 else None,
                            filter_host=fl_save,
                        ),
                    ),
                )
            _pl_analytic_prefs_merge_save(
                client_id=cid,
                filter_host=fl_save,
                filter_q=filter_q_post,
                analytic_q=analytic_q_post,
                last_created_report_id=new_rid,
                last_created_client_id=cid,
            )
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=cid,
                        filter_q=filter_q_post,
                        analytic_q=analytic_q_post,
                        report_id=new_rid,
                        filter_host=fl_save,
                    ),
                ),
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
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_q=filter_q_post,
                            analytic_q=analytic_q_post,
                            filter_host=fl_save,
                        ),
                    ),
                )
            if not new_name:
                flash("Saisissez un nom pour le rapport.", "warning")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_q=filter_q_post,
                            analytic_q=analytic_q_post,
                            filter_host=fl_save,
                        ),
                    ),
                )
            try:
                write_account_report_name(models, db, uid, pwd, rid, new_name)
                flash(f"Rapport id={rid} renommé : « {new_name} ».", "success")
            except Exception as e:
                flash(f"Impossible de renommer le rapport : {e!s}", "danger")
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=cid,
                        filter_q=filter_q_post,
                        analytic_q=analytic_q_post,
                        filter_host=fl_save,
                    ),
                ),
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
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_q=filter_q_post,
                            analytic_q=analytic_q_post,
                            filter_host=fl_save,
                        ),
                    ),
                )
            if rid <= 0:
                flash("Identifiant de rapport invalide.", "danger")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_q=filter_q_post,
                            analytic_q=analytic_q_post,
                            filter_host=fl_save,
                        ),
                    ),
                )
            try:
                rlabel = read_account_report_label(models, db, uid, pwd, rid)
                meta = unlink_account_report(models, db, uid, pwd, rid)
                extra = ""
                if meta.get("menus_unlinked") or meta.get("client_actions_unlinked"):
                    extra = (
                        f" Menus Odoo supprimés : {meta.get('menus_unlinked', 0)}, "
                        f"actions client : {meta.get('client_actions_unlinked', 0)}."
                    )
                flash(f"Rapport « {rlabel} » (id={rid}) supprimé.{extra}", "success")
                pr = _pl_analytic_prefs()
                if int(pr.get("last_created_report_id") or 0) == int(rid) and (
                    (pr.get("last_created_client_id") or "").strip().lower() == cid
                ):
                    _pl_analytic_prefs_merge_save(
                        last_created_report_id=None,
                        last_created_client_id=None,
                    )
            except Exception as e:
                flash(f"Suppression impossible : {e!s}", "danger")
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=cid,
                        filter_q=filter_q_post,
                        analytic_q=analytic_q_post,
                        filter_host=fl_save,
                    ),
                ),
            )

        if action == "budget_probe":
            try:
                msg = probe_financial_budget_analytic_summary(models, db, uid, pwd)
                if len(msg) > 900:
                    msg = msg[:897] + "…"
                flash(f"Sonde budget / analytique : {msg}", "info")
            except Exception as e:
                flash(f"Sonde : {e!s}", "danger")
            return redirect(
                ru(
                    **_pl_analytic_url_params(
                        client_id=cid,
                        filter_host=fl_save,
                        analytic_q=analytic_q_post,
                        filter_q=filter_q_post,
                    ),
                ),
            )

        if action == "run_report":
            try:
                aid = int(request.form.get("analytic_account_id") or "0")
            except ValueError:
                aid = 0
            date_from, date_to = default_period_ytd()
            full_line = (request.form.get("full_line_balance") or "").strip().lower() in (
                "1",
                "on",
                "yes",
                "true",
            )
            currency_mode = (request.form.get("currency_mode") or "company").strip()
            if currency_mode not in ("company", "transaction"):
                currency_mode = "company"
            if aid <= 0:
                flash("Choisissez un axe analytique (projet) dans la liste.", "warning")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_host=fl_save,
                            analytic_q=analytic_q_post,
                            filter_q=filter_q_post,
                        ),
                    ),
                )
            try:
                report = build_report(
                    models,
                    db,
                    uid,
                    pwd,
                    aid,
                    date_from,
                    date_to,
                    full_line_balance=full_line,
                    currency_mode=currency_mode,
                    account_report_id=None,
                )
            except Exception as e:
                flash(f"Échec du calcul : {e!s}", "danger")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_host=fl_save,
                            analytic_q=analytic_q_post,
                            filter_q=filter_q_post,
                        ),
                    ),
                )

            valid_hosts = set(distinct_odoo_hosts(reg))
            fh = fl_save
            if fh and fh not in valid_hosts:
                fh = ""
            clients_for_select = (
                configs_for_same_host(reg, fh) if fh else clients_sorted_for_select(reg)
            )
            conn_status = "ok"
            conn_detail = ""
            try:
                ok, msg = probe_odoo_reports_access(models, db, uid, pwd)
                conn_detail = msg
                if not ok:
                    conn_status = "error"
            except Exception:
                pass
            analytic_accounts = search_analytic_accounts_for_select(
                models, db, uid, pwd, analytic_q_post
            )
            reports: list = []
            report_open_urls: dict[int, str] = {}
            if conn_status == "ok":
                try:
                    reports = search_account_reports(models, db, uid, pwd, filter_q_post)
                except Exception:
                    reports = []
                if reports and cid in reg:
                    bu = reg[cid].url
                    for r in reports:
                        report_open_urls[int(r["id"])] = account_report_odoo_form_url(
                            bu, int(r["id"])
                        )
            prefs_now = _pl_analytic_prefs()
            abc = prefs_now.get("analytic_account_by_client")
            if not isinstance(abc, dict):
                abc = {}
            abc[cid] = aid
            _pl_analytic_prefs_merge_save(
                client_id=cid,
                filter_host=fh,
                filter_q=filter_q_post,
                analytic_q=analytic_q_post,
                analytic_account_by_client=abc,
            )
            hp_id, hp_miss = _pl_analytic_highlight_info(
                _pl_analytic_prefs(), cid, reports
            )
            return render_template(
                "staff/pl_analytic_report.html",
                clients=reg,
                clients_sorted=clients_sorted_for_select(reg),
                clients_for_select=clients_for_select,
                distinct_odoo_hosts=distinct_odoo_hosts(reg),
                selected_client=cid,
                filter_host=fh,
                filter_q=filter_q_post,
                analytic_q=analytic_q_post,
                analytic_accounts=analytic_accounts,
                reports=reports,
                report_open_urls=report_open_urls,
                prefill_report_id=None,
                prefill_report_name="",
                highlight_report_id=hp_id,
                highlight_report_missing=hp_miss,
                conn_status=conn_status,
                conn_detail=conn_detail,
                utility_title=UTILITY_TITLE_PL_ANALYTIC_API,
                utility_version=UTILITY_VERSION,
                utility_date=UTILITY_DATE,
                utility_author=UTILITY_AUTHOR,
                report_result=report,
                form_analytic_id=aid,
                form_full_line=full_line,
                form_currency_mode=currency_mode,
                add_base_only=False,
            )

        if action == "export_excel":
            try:
                aid = int(request.form.get("analytic_account_id") or "0")
            except ValueError:
                aid = 0
            date_from, date_to = default_period_ytd()
            full_line = (request.form.get("full_line_balance") or "").strip().lower() in (
                "1",
                "on",
                "yes",
                "true",
            )
            currency_mode = (request.form.get("currency_mode") or "company").strip()
            if currency_mode not in ("company", "transaction"):
                currency_mode = "company"
            if aid <= 0:
                flash("Choisissez un axe analytique pour l’export.", "warning")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_host=fl_save,
                            analytic_q=analytic_q_post,
                            filter_q=filter_q_post,
                        ),
                    ),
                )
            try:
                report = build_report(
                    models,
                    db,
                    uid,
                    pwd,
                    aid,
                    date_from,
                    date_to,
                    full_line_balance=full_line,
                    currency_mode=currency_mode,
                    account_report_id=None,
                )
                raw = report_to_excel_bytes(report)
            except RuntimeError as e:
                flash(str(e), "danger")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_host=fl_save,
                            analytic_q=analytic_q_post,
                            filter_q=filter_q_post,
                        ),
                    ),
                )
            except Exception as e:
                flash(f"Export Excel : {e!s}", "danger")
                return redirect(
                    ru(
                        **_pl_analytic_url_params(
                            client_id=cid,
                            filter_host=fl_save,
                            analytic_q=analytic_q_post,
                            filter_q=filter_q_post,
                        ),
                    ),
                )
            safe_db = "".join(c for c in reg[cid].db if c.isalnum() or c in "-_")[:40]
            fname = f"pl_analytique_{safe_db}_{aid}.xlsx"
            return send_file(
                io.BytesIO(raw),
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=fname,
            )

        flash("Action non reconnue.", "warning")
        return redirect(
            ru(
                **_pl_analytic_url_params(
                    client_id=cid,
                    filter_host=fl_save,
                    analytic_q=analytic_q_post,
                    filter_q=filter_q_post,
                ),
            ),
        )

    prefs = _pl_analytic_prefs()

    if "client_id" in request.args:
        selected = (request.args.get("client_id") or "").strip().lower()
    else:
        selected = (prefs.get("client_id") or "").strip().lower()
    if selected not in reg:
        selected = ""

    if "filter_host" in request.args:
        filter_host = (request.args.get("filter_host") or "").strip()
    else:
        filter_host = (prefs.get("filter_host") or "").strip()

    valid_hosts = set(distinct_odoo_hosts(reg))
    if filter_host and filter_host not in valid_hosts:
        filter_host = ""
    if (
        selected
        and filter_host
        and registry_netloc(reg[selected]).lower() != filter_host.lower()
    ):
        selected = ""
    if selected and not filter_host:
        filter_host = registry_netloc(reg[selected])

    add_base_only = (request.args.get("add_base_only") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if add_base_only:
        selected = ""

    if "q" in request.args:
        filter_q = (request.args.get("q") or "").strip()
    else:
        filter_q = (prefs.get("filter_q") or "").strip()

    if "aq" in request.args:
        analytic_q = (request.args.get("aq") or "").strip()
    else:
        analytic_q = (prefs.get("analytic_q") or "").strip()

    prefill_rid = request.args.get("report_id", type=int)

    conn_status = "idle"
    conn_detail = ""
    analytic_accounts: list[dict[str, Any]] = []
    reports: list = []
    report_open_urls: dict[int, str] = {}
    prefill_report_name = ""
    if selected:
        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(selected)
            ok, msg = probe_odoo_reports_access(models, db, uid, pwd)
            conn_detail = msg
            conn_status = "ok" if ok else "error"
            if ok:
                analytic_accounts = search_analytic_accounts_for_select(
                    models, db, uid, pwd, analytic_q
                )
                try:
                    reports = search_account_reports(models, db, uid, pwd, filter_q)
                except Exception:
                    reports = []
                if reports and selected in reg:
                    bu = reg[selected].url
                    for r in reports:
                        report_open_urls[int(r["id"])] = account_report_odoo_form_url(
                            bu, int(r["id"])
                        )
                if prefill_rid and prefill_rid > 0:
                    for r in reports:
                        if int(r["id"]) == int(prefill_rid):
                            prefill_report_name = (str(r.get("name") or "")).strip()
                            break
                    if not prefill_report_name:
                        try:
                            prefill_report_name = (
                                read_account_report_label(
                                    models, db, uid, pwd, int(prefill_rid)
                                )
                                or ""
                            ).strip()
                        except Exception:
                            prefill_report_name = ""
        except Exception as e:
            conn_status = "error"
            conn_detail = str(e)

    highlight_report_id, highlight_report_missing = _pl_analytic_highlight_info(
        prefs, selected, reports
    )

    default_analytic_id = None
    abc_get = prefs.get("analytic_account_by_client")
    if isinstance(abc_get, dict) and selected:
        raw_aid = abc_get.get(selected)
        try:
            da = int(raw_aid) if raw_aid is not None else 0
        except (TypeError, ValueError):
            da = 0
        if da > 0:
            default_analytic_id = da

    clients_for_select = (
        configs_for_same_host(reg, filter_host)
        if filter_host
        else clients_sorted_for_select(reg)
    )

    if not add_base_only:
        _pl_analytic_prefs_merge_save(
            client_id=selected,
            filter_host=filter_host,
            filter_q=filter_q,
            analytic_q=analytic_q,
        )

    return render_template(
        "staff/pl_analytic_report.html",
        clients=reg,
        clients_sorted=clients_sorted_for_select(reg),
        clients_for_select=clients_for_select,
        distinct_odoo_hosts=distinct_odoo_hosts(reg),
        selected_client=selected,
        filter_host=filter_host,
        filter_q=filter_q,
        analytic_q=analytic_q,
        analytic_accounts=analytic_accounts,
        reports=reports,
        report_open_urls=report_open_urls,
        prefill_report_id=prefill_rid,
        prefill_report_name=prefill_report_name,
        highlight_report_id=highlight_report_id,
        highlight_report_missing=highlight_report_missing,
        conn_status=conn_status,
        conn_detail=conn_detail,
        utility_title=UTILITY_TITLE_PL_ANALYTIC_API,
        utility_version=UTILITY_VERSION,
        utility_date=UTILITY_DATE,
        utility_author=UTILITY_AUTHOR,
        report_result=None,
        form_analytic_id=default_analytic_id,
        form_full_line=False,
        form_currency_mode="company",
        add_base_only=add_base_only,
    )


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
    filter_host: str | None = None,
    add_base_only: bool = False,
    open_meta: bool = False,
    balance_done: bool = False,
) -> dict[str, Any]:
    d: dict[str, Any] = {}
    if client_id:
        d["client_id"] = client_id
    qs = (q or "").strip()
    if qs:
        d["q"] = qs
    if report_id is not None and report_id > 0:
        d["report_id"] = report_id
    fh = (filter_host or "").strip()
    if fh:
        d["filter_host"] = fh
    if add_base_only:
        d["add_base_only"] = "1"
    if open_meta:
        d["open_meta"] = "1"
    if balance_done:
        d["balance_done"] = "1"
    return d


_ACCOUNTING_EP = {
    "pl_standard": "staff.rapports_comptables",
    "pl_budget": "staff.rapports_pl_budget",
    "balance": "staff.rapports_balance",
}


def _accounting_reports_page(accounting_mode: str):
    reg = _registry()

    def ru(**kwargs):
        return url_for(_ACCOUNTING_EP[accounting_mode], **kwargs)

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        filter_q = (request.form.get("filter_q") or "").strip()
        filter_host_post = (request.form.get("filter_host") or "").strip()
        add_base_only_post = (request.form.get("add_base_only") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

        def _ru_err(
            *,
            client_id: str | None = None,
            report_id: int | None = None,
            filter_host_override: str | None = None,
        ):
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=client_id,
                        q=filter_q,
                        report_id=report_id,
                        filter_host=filter_host_override
                        if filter_host_override is not None
                        else filter_host_post,
                        add_base_only=add_base_only_post,
                    ),
                ),
            )

        if action == "add_client":
            clients_path = current_app.config["TOOLBOX_CLIENTS_PATH"]
            url = (request.form.get("new_url") or "").strip()
            db = (request.form.get("new_db") or "").strip()
            user = (request.form.get("new_user") or "").strip()
            password = (request.form.get("new_password") or "").strip() or None
            try:
                new_cid = normalize_registry_db_key(db)
            except ValueError as e:
                flash(str(e), "danger")
                return _ru_err()
            if not url or not user:
                flash("URL et utilisateur Odoo sont requis.", "danger")
                return _ru_err()
            env_raw = (request.form.get("new_environment") or "").strip().lower()
            env_kw = env_raw if env_raw in ("production", "test") else None
            try:
                upsert_client(
                    clients_path,
                    new_cid,
                    new_cid,
                    normalize_odoo_base_url(url),
                    db,
                    user,
                    password,
                    [],
                    environment=env_kw,
                )
                flash(f"Base enregistrée : {new_cid}.", "success")
            except ValueError as e:
                flash(str(e), "danger")
                return _ru_err()
            net = urlparse(normalize_odoo_base_url(url)).netloc
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=new_cid,
                        q=filter_q,
                        filter_host=filter_host_post or net,
                    ),
                )
            )

        cid = (request.form.get("client_id") or "").strip().lower()
        if cid not in reg:
            flash("Base / client inconnu.", "danger")
            return _ru_err()
        if action == "prefill":
            rid = (request.form.get("report_id") or "").strip()
            try:
                rid_int = int(rid) if rid else 0
            except ValueError:
                rid_int = 0
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        report_id=rid_int if rid_int > 0 else None,
                        filter_host=registry_netloc(reg[cid]),
                    ),
                )
            )
        fl_save = registry_netloc(reg[cid])
        try:
            models, db, uid, pwd = get_xmlrpc_for_staff_client_id(cid)
        except Exception as e:
            flash(f"Connexion impossible : {e!s}", "danger")
            return redirect(
                ru(
                    **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
                )
            )
        if action == "budget_probe" and accounting_mode == "pl_budget":
            try:
                msg = probe_financial_budget_analytic_summary(models, db, uid, pwd)
                if len(msg) > 900:
                    msg = msg[:897] + "…"
                flash(f"Sonde budget / analytique : {msg}", "info")
            except Exception as e:
                flash(f"Sonde budget : {e!s}", "danger")
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        filter_host=fl_save,
                    ),
                )
            )
        if action == "personalize" and accounting_mode == "pl_standard":
            try:
                rid = int(request.form.get("report_id") or "0")
            except ValueError:
                rid = 0
            if rid <= 0:
                flash("Indiquez un identifiant de rapport (account.report) valide.", "danger")
                return redirect(
                    ru(
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
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
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            report_id=rid if rid > 0 else None,
                            filter_host=fl_save,
                        ),
                    )
                )
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        report_id=new_rid,
                        filter_host=fl_save,
                    ),
                )
            )
        if action == "personalize_pl_budget" and accounting_mode == "pl_budget":
            try:
                rid = int(request.form.get("report_id") or "0")
            except ValueError:
                rid = 0
            if rid <= 0:
                flash("Indiquez un identifiant de rapport (account.report) valide.", "danger")
                return redirect(
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            filter_host=fl_save,
                        ),
                    )
                )
            try:
                new_rid = duplicate_account_report(
                    models,
                    db,
                    uid,
                    pwd,
                    rid,
                    name_suffix=" — copie Senedoo (analytique budget)",
                )
                personalize_fix_detail_complete(models, db, uid, pwd, new_rid)
                opt = personalize_pl_analytic_budget_options(models, db, uid, pwd, new_rid)
                src_label = read_account_report_label(models, db, uid, pwd, rid)
                rlabel = read_account_report_label(models, db, uid, pwd, new_rid)
                written = ", ".join(f"{k}={v}" for k, v in opt["written"].items())
                flash(
                    f"P&L pilotage : copie id={new_rid} (« {rlabel} ») depuis id={rid} (« {src_label} »). "
                    f"Options rapport : {written}. "
                    f"Dans Odoo, sélectionnez un compte analytique et un budget puis vérifiez si la colonne budget "
                    f"se restreint (sinon voir DEPLOY_PYTHONANYWHERE.md — Studio / contournement).",
                    "success",
                )
            except Exception as e:
                flash(f"Échec personnalisation P&L analytique / budget : {e!s}", "danger")
                return redirect(
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            report_id=rid if rid > 0 else None,
                            filter_host=fl_save,
                        ),
                    )
                )
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        report_id=new_rid,
                        filter_host=fl_save,
                    ),
                )
            )
        if action == "create_balance_ohada" and accounting_mode == "balance":
            try:
                prior_ohada = sorted(
                    collect_balance_ohada_report_ids_for_cleanup(models, db, uid, pwd)
                )
                new_rid = create_toolbox_balance_ohada(models, db, uid, pwd)
                rlabel = read_account_report_label(models, db, uid, pwd, new_rid)
                msg = (
                    f"« {rlabel or BALANCE_OHADA_NAME_FR} » créé sur Odoo "
                    f"(account.report id={new_rid}) — balance 6 colonnes OHADA."
                )
                if prior_ohada:
                    msg += (
                        " Une ou plusieurs instances toolbox précédentes (codes bal_ohada ; "
                        "menus / actions liés à ces rapports uniquement) ont été retirées "
                        f"(anciens id : {', '.join(str(x) for x in prior_ohada)})."
                    )
                try:
                    _ba, menu_mid = ensure_account_report_reporting_menu(
                        models,
                        db,
                        uid,
                        pwd,
                        new_rid,
                        (rlabel or BALANCE_OHADA_NAME_FR).strip()[:240] or BALANCE_OHADA_NAME_FR,
                        under_trial_balance=True,
                    )
                    if menu_mid:
                        msg += (
                            " Une entrée de menu a été ajoutée sous Grands livres "
                            "(selon droits Odoo) — utilisez le lien ci-dessous pour l’analyse."
                        )
                except Exception:
                    pass
                flash(msg, "success")
            except Exception as e:
                flash(f"Échec création Balance OHADA : {e!s}", "danger")
                return redirect(
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            filter_host=fl_save,
                        ),
                    )
                )
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        report_id=new_rid,
                        filter_host=fl_save,
                        balance_done=True,
                    ),
                )
            )
        if action == "rewrite_balance_ohada_outer_gross" and accounting_mode == "balance":
            try:
                pairs = rewrite_toolbox_balance_ohada_outer_gross_all_rpc(
                    models, db, uid, pwd
                )
            except Exception as e:
                flash(f"Échec réécriture colonnes extérieures : {e!s}", "danger")
                return redirect(
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            filter_host=fl_save,
                        ),
                    )
                )
            if not pairs:
                flash(
                    "Aucun rapport Balance OHADA toolbox sur cette base (ligne bal_ohada).",
                    "warning",
                )
            else:
                ok_ids = [str(r) for r, o in pairs if o]
                bad = [str(r) for r, o in pairs if not o]
                msg = (
                    "Colonnes extérieures réécrites en mode « brut » (débit/crédit > 0) pour "
                    f"rapport(s) id : {', '.join(ok_ids) or '—'}."
                )
                if bad:
                    msg += f" Échec partiel sur id : {', '.join(bad)}."
                flash(msg, "success" if not bad else "warning")
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        filter_host=fl_save,
                    ),
                )
            )
        if action == "rewrite_balance_ohada_aggregation" and accounting_mode == "balance":
            try:
                triples = rewrite_toolbox_balance_ohada_aggregation_all_rpc(
                    models, db, uid, pwd
                )
            except Exception as e:
                flash(f"Échec mode net (aggregation) : {e!s}", "danger")
                return redirect(
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            filter_host=fl_save,
                        ),
                    )
                )
            if not triples:
                flash(
                    "Aucun rapport Balance OHADA toolbox sur cette base (ligne bal_ohada).",
                    "warning",
                )
            else:
                lines: list[str] = []
                for rid, ok, reason in triples:
                    st = "OK" if ok else "échec"
                    lines.append(f"id {rid} : {st} ({reason})")
                any_ok = any(t[1] for t in triples)
                any_bad = any(not t[1] for t in triples)
                flash(
                    "Mode net (aggregation) — résultat par rapport : "
                    + " ; ".join(lines)
                    + ". Rouvrez la balance dans Odoo. Si l’affichage est faux, recliquez « Colonnes extérieures → brut ».",
                    "success" if any_ok and not any_bad else ("warning" if any_ok else "danger"),
                )
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        filter_host=fl_save,
                    ),
                )
            )
        if action == "unlink_balance_ohada" and accounting_mode == "balance":
            if (request.form.get("confirm_delete") or "").strip() != "SUPPRIMER-BALANCE-OHADA":
                flash(
                    "Confirmation incorrecte : saisissez exactement SUPPRIMER-BALANCE-OHADA.",
                    "danger",
                )
                return redirect(
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            filter_host=fl_save,
                        ),
                    )
                )
            to_remove = collect_balance_ohada_report_ids_for_cleanup(models, db, uid, pwd)
            if not to_remove:
                flash(
                    "Aucune instance toolbox Balance OHADA sur cette base "
                    "(repère technique : lignes de rapport code bal_ohada ou bal_ohada_section).",
                    "warning",
                )
                return redirect(
                    ru(
                        **_rapports_url_params(
                            client_id=cid,
                            q=filter_q,
                            filter_host=fl_save,
                        ),
                    )
                )
            try:
                purge_balance_ohada_instances(models, db, uid, pwd)
                ids_txt = ", ".join(str(x) for x in sorted(to_remove))
                flash(
                    f"Rapport(s) toolbox Balance OHADA retiré(s) (id : {ids_txt}). "
                    "Menus et actions client pointant sur ces id ont été nettoyés lorsque l’API y a accès.",
                    "success",
                )
            except Exception as e:
                flash(f"Suppression impossible : {e!s}", "danger")
            return redirect(
                ru(
                    **_rapports_url_params(
                        client_id=cid,
                        q=filter_q,
                        filter_host=fl_save,
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
                    ru(
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
                    )
                )
            if not new_name:
                flash("Saisissez un nom pour le rapport.", "warning")
                return redirect(
                    ru(
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
                    )
                )
            try:
                write_account_report_name(models, db, uid, pwd, rid, new_name)
                flash(f"Rapport id={rid} renommé : « {new_name} ».", "success")
            except Exception as e:
                flash(f"Impossible de renommer le rapport : {e!s}", "danger")
            return redirect(
                ru(
                    **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
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
                    ru(
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
                    )
                )
            if rid <= 0:
                flash("Identifiant de rapport invalide.", "danger")
                return redirect(
                    ru(
                        **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
                    )
                )
            try:
                rlabel = read_account_report_label(models, db, uid, pwd, rid)
                meta = unlink_account_report(models, db, uid, pwd, rid)
                extra = ""
                if meta.get("menus_unlinked") or meta.get("client_actions_unlinked"):
                    extra = (
                        f" Menus Odoo supprimés : {meta.get('menus_unlinked', 0)}, "
                        f"actions client : {meta.get('client_actions_unlinked', 0)}."
                    )
                flash(f"Rapport « {rlabel} » (id={rid}) supprimé.{extra}", "success")
            except Exception as e:
                flash(f"Suppression impossible : {e!s}", "danger")
            return redirect(
                ru(
                    **_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save),
                )
            )
        flash("Action non reconnue.", "warning")
        return redirect(
            ru(**_rapports_url_params(client_id=cid, q=filter_q, filter_host=fl_save)),
        )

    selected = (request.args.get("client_id") or "").strip().lower()
    if selected not in reg:
        selected = ""
    filter_q = (request.args.get("q") or "").strip()
    prefill_rid = request.args.get("report_id", type=int)

    filter_host = (request.args.get("filter_host") or "").strip()
    valid_hosts = set(distinct_odoo_hosts(reg))
    if filter_host and filter_host not in valid_hosts:
        filter_host = ""
    if (
        selected
        and filter_host
        and registry_netloc(reg[selected]).lower() != filter_host.lower()
    ):
        selected = ""
    if selected and not filter_host:
        filter_host = registry_netloc(reg[selected])

    add_base_only = (request.args.get("add_base_only") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    open_instance_meta = (request.args.get("open_meta") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if add_base_only:
        selected = ""

    conn_status = "idle"
    conn_detail = ""
    reports: list = []
    balance_ohada_report_id: int | None = None
    instance_meta_rows: list[tuple[str, str]] = []
    label_picker_rows: list[dict[str, Any]] = []
    sibling_rows: list[dict[str, Any]] = []

    if not add_base_only and not selected and reg:
        if filter_host:
            to_probe = configs_for_same_host(reg, filter_host)
        else:
            to_probe = sorted(
                reg.items(),
                key=lambda x: (
                    x[1].db.casefold(),
                    0 if x[1].environment == "production" else 1,
                    x[0].lower(),
                ),
            )
        for cid, ccfg in to_probe:
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
                if accounting_mode == "balance":
                    reports = []
                    balance_ohada_report_id = find_balance_ohada_report_id(
                        models, db, uid, pwd
                    )
                else:
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

        sibs = configs_for_same_host(reg, registry_netloc(reg[selected]))
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

    if accounting_mode == "balance":
        utitle = UTILITY_TITLE_BALANCE
    elif accounting_mode == "pl_budget":
        utitle = UTILITY_TITLE_PL_BUDGET
    else:
        utitle = UTILITY_TITLE
    report_open_urls: dict[int, str] = {}
    if selected and conn_status == "ok" and reports and selected in reg:
        bu = reg[selected].url
        for r in reports:
            report_open_urls[int(r["id"])] = account_report_odoo_form_url(bu, int(r["id"]))

    clients_for_select = (
        configs_for_same_host(reg, filter_host)
        if filter_host
        else clients_sorted_for_select(reg)
    )

    prefill_report_name = ""
    if selected and conn_status == "ok" and prefill_rid and prefill_rid > 0:
        for r in reports:
            if int(r["id"]) == int(prefill_rid):
                prefill_report_name = (str(r.get("name") or "")).strip()
                break
        if not prefill_report_name:
            try:
                m, dbn, u, p = get_xmlrpc_for_staff_client_id(selected)
                prefill_report_name = (
                    read_account_report_label(m, dbn, u, p, int(prefill_rid)) or ""
                ).strip()
            except Exception:
                prefill_report_name = ""

    balance_done_q = (request.args.get("balance_done") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    # Lien « exécution » Odoo : ne pas exiger selected_client — la sélection peut être vidée si
    # filter_host ne correspond pas au netloc enregistré, alors que client_id reste valide dans l’URL.
    cid_param = (request.args.get("client_id") or "").strip().lower()
    runner_client = selected if selected in reg else ""
    if (
        accounting_mode == "balance"
        and balance_done_q
        and not runner_client
        and cid_param in reg
    ):
        runner_client = cid_param

    brid_for_balance_links: int | None = None
    if accounting_mode == "balance" and selected in reg and conn_status == "ok":
        brid_for_balance_links = balance_ohada_report_id
        if balance_done_q and prefill_rid and prefill_rid > 0:
            brid_for_balance_links = int(prefill_rid)

    if (
        accounting_mode == "balance"
        and selected in reg
        and conn_status == "ok"
        and brid_for_balance_links
        and brid_for_balance_links > 0
        and not (prefill_report_name or "").strip()
    ):
        try:
            m, dbn, u, p = get_xmlrpc_for_staff_client_id(selected)
            prefill_report_name = (
                read_account_report_label(m, dbn, u, p, int(brid_for_balance_links)) or ""
            ).strip()
        except Exception:
            prefill_report_name = ""

    balance_show_links = (
        accounting_mode == "balance"
        and runner_client in reg
        and conn_status == "ok"
        and brid_for_balance_links is not None
        and brid_for_balance_links > 0
    )
    balance_exec_url = ""
    balance_form_url = ""
    balance_list_url = ""
    balance_menu_id: int | None = None
    if balance_show_links:
        bu = reg[runner_client].url
        brid = int(brid_for_balance_links or 0)
        balance_form_url = account_report_odoo_form_url(bu, brid)
        try:
            m, dbn, u, p = get_xmlrpc_for_staff_client_id(runner_client)
            list_aid = find_account_report_backend_list_action_id(m, dbn, u, p)
            if list_aid:
                balance_list_url = account_report_backend_list_url(bu, list_aid)
            act_name = (
                (prefill_report_name or BALANCE_OHADA_NAME_FR or f"Rapport {brid}")
                .strip()[:240]
                or f"Rapport {brid}"
            )
            aid, menu_mid = ensure_account_report_reporting_menu(
                m,
                dbn,
                u,
                p,
                brid,
                act_name,
                under_trial_balance=True,
            )
            balance_menu_id = menu_mid
            if aid:
                balance_exec_url = account_report_execution_url(
                    bu, aid, menu_id=menu_mid
                )
        except Exception:
            pass

    return render_template(
        "staff/accounting_reports_utility.html",
        clients=reg,
        clients_sorted=clients_sorted_for_select(reg),
        clients_for_select=clients_for_select,
        distinct_odoo_hosts=distinct_odoo_hosts(reg),
        selected_client=selected,
        filter_host=filter_host,
        filter_q=filter_q,
        conn_status=conn_status,
        conn_detail=conn_detail,
        reports=reports,
        prefill_report_id=prefill_rid,
        prefill_report_name=prefill_report_name,
        balance_show_links=balance_show_links,
        balance_exec_url=balance_exec_url,
        balance_form_url=balance_form_url,
        balance_list_url=balance_list_url,
        balance_menu_id=balance_menu_id,
        balance_ohada_report_id=balance_ohada_report_id,
        label_picker_rows=label_picker_rows,
        sibling_rows=sibling_rows,
        instance_meta_rows=instance_meta_rows,
        add_base_only=add_base_only,
        open_instance_meta=open_instance_meta,
        accounting_mode=accounting_mode,
        accounting_endpoint=_ACCOUNTING_EP[accounting_mode],
        report_open_urls=report_open_urls,
        utility_title=utitle,
        utility_version=UTILITY_VERSION,
        utility_date=UTILITY_DATE,
        utility_author=UTILITY_AUTHOR,
    )


@bp.route("/utilities/personalize-report", methods=["GET", "POST"])
@bp.route("/utilities/rapports-comptables", methods=["GET", "POST"])
@login_required_staff
def rapports_comptables():
    return _accounting_reports_page("pl_standard")


@bp.route("/utilities/personalize-pl-budget", methods=["GET", "POST"])
@login_required_staff
def rapports_pl_budget():
    return _accounting_reports_page("pl_budget")


@bp.route("/utilities/personalize-balance", methods=["GET", "POST"])
@login_required_staff
def rapports_balance():
    return _accounting_reports_page("balance")


_BALANCE_6COL_EXAMPLE_XML = (
    Path(__file__).resolve().parents[2] / "examples" / "balance_generale_6_col_studio.example.xml"
)


@bp.route("/utilities/balance-6col-example.xml", methods=["GET"])
@login_required_staff
def download_balance_6col_example_xml():
    """Gabarit XML balance 6 colonnes (Studio / module) — pas d’import automatique vers Odoo."""
    if not _BALANCE_6COL_EXAMPLE_XML.is_file():
        abort(404)
    return send_file(
        _BALANCE_6COL_EXAMPLE_XML,
        as_attachment=True,
        download_name="balance_generale_6_col_studio.example.xml",
        mimetype="application/xml",
        max_age=0,
    )
