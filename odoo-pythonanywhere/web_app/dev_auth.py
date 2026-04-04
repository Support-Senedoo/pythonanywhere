"""Identifiants de démo (désactivables en prod avec TOOLBOX_DISABLE_DEV_LOGIN=1)."""
from __future__ import annotations

import os

from web_app.users_store import ToolboxUser

_DEV_LOGIN = "test"
_DEV_PASSWORD = "passer"


def dev_login_disabled() -> bool:
    return os.environ.get("TOOLBOX_DISABLE_DEV_LOGIN", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def try_dev_user(login: str, password: str, portal: str) -> ToolboxUser | None:
    if dev_login_disabled():
        return None
    login_clean = (login or "").strip().lower()
    password_clean = (password or "").strip()
    if login_clean != _DEV_LOGIN or password_clean != _DEV_PASSWORD:
        return None
    portal = (portal or "client").strip().lower()
    if portal == "client":
        cid = (os.environ.get("TOOLBOX_TEST_CLIENT_ID") or "la_ripaille").strip()
        return ToolboxUser(login=_DEV_LOGIN, role="client", client_id=cid)
    if portal == "staff":
        return ToolboxUser(login=_DEV_LOGIN, role="staff", client_id=None)
    return None
