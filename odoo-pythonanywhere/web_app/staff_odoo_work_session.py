"""Session staff : mémoriser login / mot de passe Odoo pour relancer la liste des bases sans ressaisie.

Uniquement lorsque la session Flask est stockée côté serveur (fichiers), pas dans le cookie signé :
voir ``TOOLBOX_SESSION_BACKEND`` dans ``create_app`` (PythonAnywhere ou ``TOOLBOX_FILESYSTEM_SESSION``).
"""
from __future__ import annotations

from typing import Any, TypedDict

from flask import Flask, session

STAFF_ODOO_WORK_LOGIN = "staff_odoo_work_login"
STAFF_ODOO_WORK_PASSWORD = "staff_odoo_work_password"
STAFF_ODOO_WORK_BASE_URL = "staff_odoo_work_base_url"
STAFF_ODOO_WORK_PORTAL_COOKIE = "staff_odoo_work_portal_cookie"


class StaffOdooWorkCredentials(TypedDict):
    login: str
    password: str
    base_url: str
    portal_cookie: str | None


def session_may_store_odoo_secrets(app: Flask) -> bool:
    return app.config.get("TOOLBOX_SESSION_BACKEND") == "filesystem"


def clear_staff_odoo_work_credentials(sess: Any) -> None:
    for k in (
        STAFF_ODOO_WORK_LOGIN,
        STAFF_ODOO_WORK_PASSWORD,
        STAFF_ODOO_WORK_BASE_URL,
        STAFF_ODOO_WORK_PORTAL_COOKIE,
    ):
        sess.pop(k, None)


def save_staff_odoo_work_credentials(
    sess: Any,
    app: Flask,
    *,
    login: str,
    password: str,
    base_url: str,
    portal_cookie: str | None,
) -> bool:
    if not session_may_store_odoo_secrets(app):
        return False
    login_c = (login or "").strip()
    pwd = password or ""
    if not login_c or not pwd:
        return False
    sess[STAFF_ODOO_WORK_LOGIN] = login_c
    sess[STAFF_ODOO_WORK_PASSWORD] = pwd
    sess[STAFF_ODOO_WORK_BASE_URL] = (base_url or "").strip()
    pc = (portal_cookie or "").strip()
    if len(pc) > 16000:
        pc = pc[:16000]
    sess[STAFF_ODOO_WORK_PORTAL_COOKIE] = pc
    return True


def get_staff_odoo_work_credentials(sess: Any) -> StaffOdooWorkCredentials | None:
    login = (sess.get(STAFF_ODOO_WORK_LOGIN) or "").strip()
    pwd = sess.get(STAFF_ODOO_WORK_PASSWORD)
    if not login or not isinstance(pwd, str) or not pwd:
        return None
    bu = sess.get(STAFF_ODOO_WORK_BASE_URL)
    base_url = bu.strip() if isinstance(bu, str) else ""
    c = sess.get(STAFF_ODOO_WORK_PORTAL_COOKIE)
    portal = c.strip() if isinstance(c, str) and c.strip() else None
    return StaffOdooWorkCredentials(
        login=login,
        password=pwd,
        base_url=base_url,
        portal_cookie=portal,
    )


def staff_odoo_work_login_saved(sess: Any) -> str:
    """Login mémorisé (sans mot de passe) pour l’affichage."""
    return (sess.get(STAFF_ODOO_WORK_LOGIN) or "").strip()
