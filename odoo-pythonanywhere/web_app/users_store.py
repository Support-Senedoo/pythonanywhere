"""Utilisateurs toolbox (login web), fichier JSON hors Git."""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from web_app.odoo_registry import validate_client_id

_LOGIN_RE = re.compile(r"^[a-zA-Z0-9._@+-]{2,80}$")


@dataclass(frozen=True)
class ToolboxUser:
    login: str
    role: str  # "client" | "staff"
    client_id: str | None  # obligatoire si role=client


def read_users_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"users": []}
    return json.loads(p.read_text(encoding="utf-8"))


def write_users_file(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(p.parent))
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(text)
        Path(tmp).replace(p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _login_key(login: str) -> str:
    return (login or "").strip().lower()


def load_users(path: str | Path) -> dict[str, dict[str, Any]]:
    data = read_users_file(path)
    by_login: dict[str, dict[str, Any]] = {}
    for row in data.get("users", []):
        key = _login_key(str(row.get("login", "")))
        if not key:
            continue
        by_login[key] = row
    return by_login


def verify_user(path: str | Path, login: str, password: str) -> ToolboxUser | None:
    users = load_users(path)
    row = users.get(_login_key(login))
    if not row:
        return None
    h = row.get("password_hash") or row.get("hash")
    if not h or not check_password_hash(str(h), password):
        return None
    role = str(row.get("role", "")).strip().lower()
    if role not in ("client", "staff"):
        return None
    canon = str(row.get("login", "")).strip() or _login_key(login)
    cid = row.get("client_id")
    if role == "client":
        if not cid or not str(cid).strip():
            return None
        try:
            cid_norm = validate_client_id(str(cid))
        except ValueError:
            return None
        return ToolboxUser(login=canon, role=role, client_id=cid_norm)
    return ToolboxUser(login=canon, role=role, client_id=None)


def validate_login(login: str) -> str:
    s = (login or "").strip()
    if not _LOGIN_RE.match(s):
        raise ValueError(
            "Identifiant : 2–80 car., lettres, chiffres, . _ @ + -"
        )
    return s


def list_user_rows(path: str | Path) -> list[dict[str, Any]]:
    data = read_users_file(path)
    rows = []
    for row in data.get("users", []):
        login = str(row.get("login", "")).strip()
        if not login:
            continue
        rows.append(
            {
                "login": login,
                "role": str(row.get("role", "")).strip().lower(),
                "client_id": row.get("client_id"),
            }
        )
    return sorted(rows, key=lambda r: (r["role"], r["login"].lower()))


def _client_id_key(client_id: str | None) -> str:
    return (str(client_id or "")).strip().lower()


def count_users_for_client(path: str | Path, client_id: str) -> int:
    target = _client_id_key(client_id)
    if not target:
        return 0
    n = 0
    for row in list_user_rows(path):
        if row["role"] == "client" and _client_id_key(row.get("client_id")) == target:
            n += 1
    return n


def upsert_client_user(
    path: str | Path,
    login: str,
    password: str | None,
    client_id: str,
    *,
    is_new: bool,
) -> None:
    login = validate_login(login)
    try:
        client_id = validate_client_id(client_id)
    except ValueError as e:
        raise ValueError(str(e)) from e
    data = read_users_file(path)
    users: list[dict[str, Any]] = list(data.get("users", []))
    found = False
    for i, row in enumerate(users):
        if _login_key(str(row.get("login", ""))) == _login_key(login):
            if is_new:
                raise ValueError("Cet identifiant existe déjà.")
            h = row.get("password_hash") or row.get("hash")
            if password:
                h = generate_password_hash(password)
            if not h:
                raise ValueError("Mot de passe requis ou existant.")
            users[i] = {
                "login": login,
                "password_hash": h,
                "role": "client",
                "client_id": client_id,
            }
            found = True
            break
    if not found:
        if not is_new:
            raise ValueError("Utilisateur introuvable.")
        if not password:
            raise ValueError("Mot de passe requis pour un nouvel utilisateur.")
        users.append(
            {
                "login": login,
                "password_hash": generate_password_hash(password),
                "role": "client",
                "client_id": client_id,
            }
        )
    data["users"] = users
    write_users_file(path, data)


def upsert_staff_user(path: str | Path, login: str, password: str | None, *, is_new: bool) -> None:
    login = validate_login(login)
    data = read_users_file(path)
    users: list[dict[str, Any]] = list(data.get("users", []))
    found = False
    for i, row in enumerate(users):
        if _login_key(str(row.get("login", ""))) == _login_key(login):
            if is_new:
                raise ValueError("Cet identifiant existe déjà.")
            h = row.get("password_hash") or row.get("hash")
            if password:
                h = generate_password_hash(password)
            if not h:
                raise ValueError("Mot de passe requis ou existant.")
            users[i] = {
                "login": login,
                "password_hash": h,
                "role": "staff",
            }
            found = True
            break
    if not found:
        if not is_new:
            raise ValueError("Utilisateur introuvable.")
        if not password:
            raise ValueError("Mot de passe requis.")
        users.append(
            {
                "login": login,
                "password_hash": generate_password_hash(password),
                "role": "staff",
            }
        )
    data["users"] = users
    write_users_file(path, data)


def delete_user(path: str | Path, login: str) -> None:
    key = _login_key(login)
    data = read_users_file(path)
    users = [u for u in data.get("users", []) if _login_key(str(u.get("login", ""))) != key]
    if len(users) == len(data.get("users", [])):
        raise ValueError("Utilisateur introuvable.")
    data["users"] = users
    write_users_file(path, data)


def get_user_row(path: str | Path, login: str) -> dict[str, Any] | None:
    key = _login_key(login)
    for row in read_users_file(path).get("users", []):
        if _login_key(str(row.get("login", ""))) == key:
            return dict(row)
    return None
