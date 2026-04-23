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
    session,
    url_for,
)

from odoo_client import normalize_odoo_base_url

from web_app.blueprints.public import login_required_staff
from web_app.client_apps import KNOWN_APPS
from web_app.odoo_account_probe import (
    MAX_DATABASES_TO_PROBE,
    format_db_list_error,
    probe_account_databases,
)
from web_app.odoo_registry import (
    delete_client,
    load_clients_registry,
    normalize_registry_db_key,
    registry_netloc,
    upsert_client,
)
from web_app.staff_odoo_work_session import (
    clear_staff_odoo_work_credentials,
    get_staff_odoo_work_credentials,
    save_staff_odoo_work_credentials,
    session_may_store_odoo_secrets,
    staff_odoo_work_login_saved,
)
from web_app.staff_selected_client_persist import persist_staff_selected_client_for_xmlrpc
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


def _portal_db_error_suggests_captcha(message: str | None) -> bool:
    """Message renvoyé par le portail / probe quand odoo.com bloque les robots (souvent sur PA)."""
    low = (message or "").lower()
    if not low:
        return False
    return any(
        n in low
        for n in (
            "captcha",
            "anti-robot",
            "turnstile",
            "recaptcha",
            "datacenter",
            "pythonanywhere",
        )
    )


def _probe_result_allows_remembering_credentials(result: dict[str, Any] | None) -> bool:
    if not result or result.get("url_error"):
        return False
    rows = result.get("rows")
    if isinstance(rows, list) and len(rows) > 0:
        return True
    if result.get("db_list_error"):
        return False
    names = result.get("candidate_names")
    return isinstance(names, list) and len(names) > 0


@bp.route("/odoo-connexion", methods=["GET", "POST"])
@login_required_staff
def odoo_connexion_staff():
    """
    Parcours simplifié : login + mot de passe (éventuellement URL instance ou cookie portail),
    liste des bases (portail Mes bases ou db.list), puis enregistrement dans le registre + base active.
    """
    store_ok = session_may_store_odoo_secrets(current_app)
    result: dict[str, Any] | None = None

    if request.method == "POST":
        action = (request.form.get("action") or "connect").strip()

        if action == "clear":
            clear_staff_odoo_work_credentials(session)
            flash(
                "Identifiants Odoo oubliés sur ce serveur (prochaine liste : saisie complète).",
                "info",
            )
            return redirect(url_for("staff_admin.odoo_connexion_staff"))

        if action == "register":
            db_raw = (request.form.get("database") or "").strip()
            inst_url = (request.form.get("instance_url") or "").strip()
            env = (request.form.get("environment") or "production").strip().lower()
            if env not in ("production", "test"):
                env = "production"
            creds = get_staff_odoo_work_credentials(session)
            login = ""
            password: str | None = None
            if creds:
                login = creds["login"]
                password = creds["password"]
            if not password:
                password = (request.form.get("odoo_password_register") or "").strip() or None
            if not login:
                login = (request.form.get("odoo_login_register") or "").strip()
            if not login or not password:
                flash(
                    "Login et mot de passe requis pour enregistrer la base "
                    "(reconnectez-vous ou saisissez-les dans le formulaire).",
                    "danger",
                )
                return redirect(url_for("staff_admin.odoo_connexion_staff"))
            try:
                cid = normalize_registry_db_key(db_raw)
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(url_for("staff_admin.odoo_connexion_staff"))
            if not inst_url:
                flash("URL d’instance manquante.", "danger")
                return redirect(url_for("staff_admin.odoo_connexion_staff"))
            try:
                upsert_client(
                    _clients_path(),
                    cid,
                    cid,
                    normalize_odoo_base_url(inst_url),
                    db_raw,
                    login,
                    password,
                    ["odoo_status"],
                    environment=env,
                )
            except ValueError as e:
                flash(str(e), "danger")
                return redirect(url_for("staff_admin.odoo_connexion_staff"))
            session["staff_selected_client_id"] = cid
            persist_staff_selected_client_for_xmlrpc(current_app, cid)
            flash(
                f"Base « {db_raw} » enregistrée dans le registre et sélectionnée pour les applications.",
                "success",
            )
            return redirect(url_for("staff.staff_home"))

        if action == "list_session":
            creds = get_staff_odoo_work_credentials(session)
            if not creds:
                flash(
                    "Aucun identifiant mémorisé : utilisez le formulaire ci-dessous "
                    "(ou activez les sessions fichiers sur ce déploiement).",
                    "warning",
                )
            else:
                result = probe_account_databases(
                    creds["base_url"],
                    creds["login"],
                    creds["password"],
                    portal_session_cookie=creds["portal_cookie"],
                )
        else:
            login = (request.form.get("odoo_login") or "").strip()
            password = (request.form.get("odoo_password") or "").strip()
            base_url = (request.form.get("odoo_url") or "").strip()
            portal_cookie = (request.form.get("odoo_portal_session_cookie") or "").strip()
            remember = (request.form.get("remember_session") or "1").strip() == "1"

            prev = get_staff_odoo_work_credentials(session)
            if prev:
                if not login:
                    login = prev["login"]
                if not password:
                    password = prev["password"]
                if not base_url:
                    base_url = prev["base_url"]
                if not portal_cookie and (prev.get("portal_cookie") or "").strip():
                    portal_cookie = (prev["portal_cookie"] or "").strip()

            if not login:
                flash("Login Odoo requis.", "warning")
            elif not base_url and not portal_cookie and not password:
                flash(
                    "Mot de passe requis (sauf si vous collez un cookie de session portail odoo.com).",
                    "warning",
                )
            else:
                result = probe_account_databases(
                    base_url,
                    login,
                    password,
                    portal_session_cookie=portal_cookie or None,
                )
                if (
                    store_ok
                    and remember
                    and _probe_result_allows_remembering_credentials(result)
                ):
                    save_staff_odoo_work_credentials(
                        session,
                        current_app,
                        login=login,
                        password=password,
                        base_url=base_url,
                        portal_cookie=portal_cookie or None,
                    )
                    flash(
                        "Identifiants mémorisés sur le serveur pour cette session navigateur "
                        "(bouton « Relancer la liste »).",
                        "success",
                    )
                elif remember and not store_ok and _probe_result_allows_remembering_credentials(result):
                    flash(
                        "Astuce : ce serveur n’utilise pas les sessions « fichiers » — le mot de passe ne peut pas "
                        "être conservé entre deux visites. Sur PythonAnywhere, c’est en général automatique ; "
                        "en local, définissez TOOLBOX_FILESYSTEM_SESSION=1 (voir déploiement).",
                        "info",
                    )

    db_err = (result or {}).get("db_list_error") if isinstance(result, dict) else None
    return render_template(
        "staff/admin/odoo_connexion.html",
        result=result,
        max_probe=MAX_DATABASES_TO_PROBE,
        session_store_ok=store_ok,
        session_login_saved=staff_odoo_work_login_saved(session),
        session_has_creds=bool(get_staff_odoo_work_credentials(session)),
        portal_captcha_blocked=_portal_db_error_suggests_captcha(
            db_err if isinstance(db_err, str) else None
        ),
    )


@bp.route("/clients")
@login_required_staff
def clients_list():
    reg = load_clients_registry(_clients_path())
    rows = []
    for cid, cfg in sorted(reg.items(), key=lambda x: x[1].db.lower()):
        rows.append(
            {
                "id": cid,
                "label": cfg.label,
                "url": cfg.url,
                "db": cfg.db,
                "filter_host": registry_netloc(cfg),
                "environment": cfg.environment,
                "apps": ", ".join(cfg.apps),
                "users_count": count_users_for_client(_users_path(), cid),
            }
        )
    return render_template("staff/admin/clients_list.html", clients=rows)


@bp.route("/clients/new", methods=["GET", "POST"])
@login_required_staff
def client_new():
    if request.method == "POST":
        url = normalize_odoo_base_url((request.form.get("url") or "").strip())
        db = (request.form.get("db") or "").strip()
        user = (request.form.get("odoo_user") or "").strip()
        password = (request.form.get("odoo_password") or "").strip() or None
        apps = [k for k in KNOWN_APPS if request.form.get(f"app_{k}")]
        try:
            cid = normalize_registry_db_key(db)
        except ValueError as e:
            flash(str(e), "danger")
        else:
            try:
                upsert_client(
                    _clients_path(),
                    cid,
                    cid,
                    url,
                    db,
                    user,
                    password,
                    apps,
                    environment=(request.form.get("environment") or "production"),
                )
                flash(f"Base « {cid} » enregistrée.", "success")
                return redirect(url_for("staff_admin.clients_list"))
            except ValueError as e:
                flash(str(e), "danger")
    return render_template(
        "staff/admin/client_form.html",
        mode="new",
        client=None,
        add_base_filter_host="",
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
        url = normalize_odoo_base_url((request.form.get("url") or "").strip())
        db = (request.form.get("db") or "").strip()
        user = (request.form.get("odoo_user") or "").strip()
        pw = (request.form.get("odoo_password") or "").strip()
        password = pw if pw else None
        apps = [k for k in KNOWN_APPS if request.form.get(f"app_{k}")]
        try:
            dbn = normalize_registry_db_key(db)
        except ValueError as e:
            flash(str(e), "danger")
        else:
            if dbn != cid_key:
                flash(
                    "Le nom de base (identifiant) ne peut pas être modifié : supprimez l’entrée et recréez-la si besoin.",
                    "danger",
                )
            else:
                try:
                    upsert_client(
                        _clients_path(),
                        cid_key,
                        cid_key,
                        url,
                        db,
                        user,
                        password,
                        apps,
                        environment=(request.form.get("environment") or "production"),
                    )
                    flash("Base mise à jour.", "success")
                    return redirect(url_for("staff_admin.clients_list"))
                except ValueError as e:
                    flash(str(e), "danger")
    return render_template(
        "staff/admin/client_form.html",
        mode="edit",
        client=cfg,
        add_base_filter_host=registry_netloc(cfg),
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
    labels = {cid: c.db for cid, c in reg.items()}
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
