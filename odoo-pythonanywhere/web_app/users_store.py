"""Utilisateurs toolbox (login web), fichier JSON hors Git."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash


@dataclass(frozen=True)
class ToolboxUser:
    login: str
    role: str  # "client" | "staff"
    client_id: str | None  # obligatoire si role=client


def load_users(path: str | Path) -> dict[str, dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    by_login: dict[str, dict[str, Any]] = {}
    for row in data.get("users", []):
        login = str(row["login"]).strip()
        by_login[login] = row
    return by_login


def verify_user(path: str | Path, login: str, password: str) -> ToolboxUser | None:
    users = load_users(path)
    row = users.get(login.strip())
    if not row:
        return None
    h = row.get("password_hash") or row.get("hash")
    if not h or not check_password_hash(str(h), password):
        return None
    role = str(row.get("role", "")).strip().lower()
    if role not in ("client", "staff"):
        return None
    cid = row.get("client_id")
    if role == "client":
        if not cid or not str(cid).strip():
            return None
        return ToolboxUser(login=login, role=role, client_id=str(cid).strip())
    return ToolboxUser(login=login, role=role, client_id=None)
