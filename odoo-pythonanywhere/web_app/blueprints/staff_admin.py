"""Administration : clients Odoo + comptes (staff / client)."""
from __future__ import annotations

import os
import re
import xmlrpc.client
from typing import Any
from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from odoo_client import normalize_odoo_base_url

from web_app.blueprints.public import login_required_staff
from web_app.client_apps import KNOWN_APPS, apps_for_template
from web_app.odoo_account_probe import format_db_list_error
from web_app.odoo_registry import delete_client, load_clients_registry, upsert_client
from web_app.users_store import (
    count_users_for_client,
    delete_user,
    get_user_row,
    list_user_rows,
    update_portal_user,
    upsert_client_user,
    upsert_staff_user,
)


def managed_databases_from_env(raw: str | None) -> list[str]:
    """Parse TOOLBOX_ODOO_MANAGED_DATABASES : noms séparés par virgule, point-virgule ou saut de ligne."""
    if not (raw or "").strip():
        return []
    parts = re.split(r"[\n;,]+", raw)
    return sorted({p.strip() for p in parts if p.strip()}, key=str.lower)


def _fetch_databases_from_server(base_url: str) -> tuple[list[str], str | None]:
    u = normalize_odoo_base_url((base_url or "").strip())
    if not u:
        return [], "URL vide."
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return [], "URL invalide (http/https requis)."
    endpoint = f"{u}/xmlrpc/2/db"
    try:
        proxy = xmlrpc.client.ServerProxy(endpoint, allow_none=True)
        raw_list: Any = proxy.list()
        if not isinstance(raw_list, list):
            return [], "Le serveur n’a pas renvoyé une liste de bases."
        names = [str(x).strip() for x in raw_list if str(x).strip()]
        return sorted(set(names), key=str.lower), None
    except xmlrpc.client.Fault as e:
        return [], format_db_list_error(e)
    except OSError as e:
        return [], f"Réseau / SSL : {e!s}"
    except Exception as e:
        return [], format_db_list_error(e)


def merge_database_suggestions(
    *,
    url: str,
    env_managed_raw: str | None,
) -> tuple[list[str], str | None]:
    from_env = managed_databases_from_env(env_managed_raw)
    u = normalize_odoo_base_url((url or "").strip())
    if not u:
        return sorted(from_env, key=str.lower), None
    from_server, err = _fetch_databases_from_server(u)
    merged = sorted(set(from_server) | set(from_env), key=str.lower)
    return merged, err


def _client_id_in_registry(reg: dict, client_id: str) -> bool:
    return (client_id or "").strip().lower() in reg

bp = Blueprint("staff_admin", __name__, url_prefix="/admin")


def _users_path():
    return current_app.config["TOOLBOX_USERS_PATH"]


def _clients_path():
    return current_app.config["TOOLBOX_CLIENTS_PATH"]


def _odoo_db_presets() -> list[str]:
    return managed_databases_from_env(os.environ.get("TOOLBOX_ODOO_MANAGED_DATABASES"))


def _default_odoo_api_user_placeholder() -> str:
    """Placeholder champ login API (pas de mot de passe ici)."""
    return (os.environ.get("TOOLBOX_ODOO_DEFAULT_API_USER") or "support@senedoo.com").strip()


@bp.route("/odoo-databases")
@login_required_staff
def odoo_databases_suggest():
    """JSON : bases depuis TOOLBOX_ODOO_MANAGED_DATABASES + db.list() sur l’URL si fournie."""
    url = (request.args.get("url") or "").strip()
    merged, err = merge_database_suggestions(
        url=url,
        env_managed_raw=os.environ.get("TOOLBOX_ODOO_MANAGED_DATABASES"),
    )
    return jsonify({"databases": merged, "server_error": err})


@bp.route("/")
@login_required_staff
def admin_index():
    return redirect(url_for("staff_admin.clients_list"))


@bp.route("/clients")
@login_required_staff
def clients_list():
    reg = load_clients_registry(_clients_path())
    rows = []
    for cid, cfg in sorted(reg.items(), key=lambda x: x[1].label.lower()):
        rows.append(
            {
                "id": cid,
                "label": cfg.label,
                "url": cfg.url,
                "db": cfg.db,
                "apps": ", ".join(cfg.apps),
                "users_count": count_users_for_client(_users_path(), cid),
            }
        )
    return render_template("staff/admin/clients_list.html", clients=rows)


@bp.route("/clients/new", methods=["GET", "POST"])
@login_required_staff
def client_new():
    if request.method == "POST":
        cid = (request.form.get("client_id") or "").strip()
        label = (request.form.get("label") or "").strip()
        url = normalize_odoo_base_url((request.form.get("url") or "").strip())
        db = (request.form.get("db") or "").strip()
        user = (request.form.get("odoo_user") or "").strip()
        password = (request.form.get("odoo_password") or "").strip() or None
        apps = [k for k in KNOWN_APPS if request.form.get(f"app_{k}")]
        try:
            upsert_client(
                _clients_path(),
                cid,
                label,
                url,
                db,
                user,
                password,
                apps,
            )
            flash(f"Client « {label} » créé.", "success")
            return redirect(url_for("staff_admin.clients_list"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template(
        "staff/admin/client_form.html",
        mode="new",
        client=None,
        known_apps=KNOWN_APPS,
        odoo_db_presets=_odoo_db_presets(),
        default_odoo_api_user=_default_odoo_api_user_placeholder(),
    )


@bp.route("/clients/<client_id>/edit", methods=["GET", "POST"])
@login_required_staff
def client_edit(client_id: str):
    reg = load_clients_registry(_clients_path())
    cid_key = (client_id or "").strip().lower()
    if cid_key not in reg:
        flash("Client introuvable.", "danger")
        return redirect(url_for("staff_admin.clients_list"))
    cfg = reg[cid_key]
    if request.method == "POST":
        label = (request.form.get("label") or "").strip()
        url = normalize_odoo_base_url((request.form.get("url") or "").strip())
        db = (request.form.get("db") or "").strip()
        user = (request.form.get("odoo_user") or "").strip()
        pw = (request.form.get("odoo_password") or "").strip()
        password = pw if pw else None
        apps = [k for k in KNOWN_APPS if request.form.get(f"app_{k}")]
        try:
            upsert_client(
                _clients_path(),
                cid_key,
                label,
                url,
                db,
                user,
                password,
                apps,
            )
            flash("Client mis à jour.", "success")
            return redirect(url_for("staff_admin.clients_list"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template(
        "staff/admin/client_form.html",
        mode="edit",
        client=cfg,
        known_apps=KNOWN_APPS,
        odoo_db_presets=_odoo_db_presets(),
        default_odoo_api_user=_default_odoo_api_user_placeholder(),
    )


@bp.route("/clients/<client_id>/delete", methods=["POST"])
@login_required_staff
def client_delete(client_id: str):
    cid_key = (client_id or "").strip().lower()
    if (request.form.get("confirm") or "").strip().casefold() != cid_key:
        flash("Tapez l’identifiant exact du client pour confirmer.", "warning")
        return redirect(url_for("staff_admin.client_edit", client_id=cid_key))
    if count_users_for_client(_users_path(), cid_key) > 0:
        flash("Supprimez ou réassignez d’abord les comptes client liés à ce profil.", "danger")
        return redirect(url_for("staff_admin.client_edit", client_id=cid_key))
    try:
        delete_client(_clients_path(), cid_key)
        flash("Client supprimé.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("staff_admin.clients_list"))


@bp.route("/users")
@login_required_staff
def users_list():
    rows = list_user_rows(_users_path())
    reg = load_clients_registry(_clients_path())
    labels = {cid: c.label for cid, c in reg.items()}
    return render_template(
        "staff/admin/users_list.html",
        users=rows,
        client_labels=labels,
    )


@bp.route("/users/new", methods=["GET", "POST"])
@login_required_staff
def user_new():
    reg = load_clients_registry(_clients_path())
    if request.method == "POST":
        role = (request.form.get("role") or "client").strip().lower()
        login = (request.form.get("login") or "").strip()
        password = (request.form.get("password") or "").strip()
        client_id = (request.form.get("client_id") or "").strip()
        try:
            if role == "staff":
                upsert_staff_user(_users_path(), login, password, is_new=True)
                flash(f"Compte équipe « {login} » créé.", "success")
            else:
                if not _client_id_in_registry(reg, client_id):
                    flash("Client inconnu dans le registre.", "danger")
                    return render_template(
                        "staff/admin/user_form.html",
                        mode="new",
                        user=None,
                        clients=reg,
                    )
                upsert_client_user(
                    _users_path(), login, password, client_id, is_new=True
                )
                flash(f"Compte client « {login} » créé.", "success")
            return redirect(url_for("staff_admin.users_list"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template(
        "staff/admin/user_form.html",
        mode="new",
        user=None,
        clients=reg,
    )


@bp.route("/users/<path:login>/edit", methods=["GET", "POST"])
@login_required_staff
def user_edit(login: str):
    row = get_user_row(_users_path(), login)
    if not row:
        flash("Utilisateur introuvable.", "danger")
        return redirect(url_for("staff_admin.users_list"))
    reg = load_clients_registry(_clients_path())
    role = str(row.get("role", "")).strip().lower()
    if request.method == "POST":
        new_login = (request.form.get("login") or "").strip()
        password = (request.form.get("password") or "").strip() or None
        client_id = (request.form.get("client_id") or "").strip()
        try:
            if role == "staff":
                final = update_portal_user(
                    _users_path(),
                    login,
                    new_login=new_login,
                    password=password,
                    role="staff",
                    client_id=None,
                )
                flash("Compte équipe mis à jour.", "success")
            else:
                if not _client_id_in_registry(reg, client_id):
                    flash("Client inconnu dans le registre.", "danger")
                    return render_template(
                        "staff/admin/user_form.html",
                        mode="edit",
                        user=row,
                        clients=reg,
                    )
                final = update_portal_user(
                    _users_path(),
                    login,
                    new_login=new_login,
                    password=password,
                    role="client",
                    client_id=client_id,
                )
                flash("Compte client mis à jour.", "success")
            if final.casefold() != (login or "").strip().casefold():
                return redirect(url_for("staff_admin.user_edit", login=final))
            return redirect(url_for("staff_admin.users_list"))
        except ValueError as e:
            flash(str(e), "danger")
    return render_template(
        "staff/admin/user_form.html",
        mode="edit",
        user=row,
        clients=reg,
    )


@bp.route("/users/<path:login>/delete", methods=["POST"])
@login_required_staff
def user_delete(login: str):
    c = (request.form.get("confirm_login") or "").strip()
    if c.casefold() != (login or "").strip().casefold():
        flash("Tapez l’identifiant exact pour confirmer la suppression.", "warning")
        return redirect(url_for("staff_admin.user_edit", login=login))
    try:
        delete_user(_users_path(), login)
        flash("Utilisateur supprimé.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("staff_admin.users_list"))
