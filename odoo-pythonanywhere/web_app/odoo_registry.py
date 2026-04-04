"""Registre des bases clients Odoo (fichier JSON hors Git sur le serveur)."""
from __future__ import annotations

import json
import re
import tempfile
import xmlrpc.client
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from odoo_client import normalize_odoo_base_url

from web_app.client_apps import normalize_app_ids

_CLIENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class ClientOdooConfig:
    id: str
    label: str
    url: str
    db: str
    user: str
    password: str
    apps: tuple[str, ...]


def _row_to_config(row: dict[str, Any]) -> ClientOdooConfig:
    cid = str(row["id"]).strip().lower()
    apps = normalize_app_ids(row.get("apps"))
    return ClientOdooConfig(
        id=cid,
        label=str(row.get("label") or cid),
        url=normalize_odoo_base_url(str(row["url"])),
        db=str(row["db"]).strip(),
        user=str(row["user"]).strip(),
        password=str(row["password"]),
        apps=apps,
    )


def load_clients_registry(path: str | Path) -> dict[str, ClientOdooConfig]:
    p = Path(path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, ClientOdooConfig] = {}
    for row in data.get("clients", []):
        try:
            cfg = _row_to_config(row)
            out[cfg.id] = cfg
        except (KeyError, TypeError, ValueError):
            continue
    return out


def read_clients_raw(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"clients": []}
    return json.loads(p.read_text(encoding="utf-8"))


def write_clients_raw(path: str | Path, data: dict[str, Any]) -> None:
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


def validate_client_id(client_id: str) -> str:
    s = (client_id or "").strip().lower()
    if not _CLIENT_ID_RE.match(s):
        raise ValueError(
            "Identifiant client : lettre minuscule puis lettres, chiffres ou _ (max 63 car.)."
        )
    return s


def upsert_client(
    path: str | Path,
    client_id: str,
    label: str,
    url: str,
    db: str,
    user: str,
    password: str | None,
    apps: list[str],
) -> None:
    cid = validate_client_id(client_id)
    data = read_clients_raw(path)
    clients: list[dict[str, Any]] = list(data.get("clients", []))
    url = (url or "").strip().rstrip("/")
    db = (db or "").strip()
    user = (user or "").strip()
    label = (label or "").strip() or cid
    app_ids = list(normalize_app_ids(apps))

    found = False
    for i, row in enumerate(clients):
        if str(row.get("id", "")).strip().lower() == cid:
            pwd = password if password is not None else str(row.get("password", ""))
            clients[i] = {
                "id": cid,
                "label": label,
                "url": url,
                "db": db,
                "user": user,
                "password": pwd,
                "apps": app_ids,
            }
            found = True
            break
    if not found:
        if not password:
            raise ValueError("Mot de passe Odoo requis pour un nouveau client.")
        clients.append(
            {
                "id": cid,
                "label": label,
                "url": url,
                "db": db,
                "user": user,
                "password": password,
                "apps": app_ids,
            }
        )
    data["clients"] = clients
    write_clients_raw(path, data)


def delete_client(path: str | Path, client_id: str) -> None:
    cid = str(client_id or "").strip().lower()
    if not cid:
        raise ValueError("Identifiant client manquant.")
    data = read_clients_raw(path)
    clients = [c for c in data.get("clients", []) if str(c.get("id", "")).strip().lower() != cid]
    if len(clients) == len(data.get("clients", [])):
        raise ValueError("Client introuvable.")
    data["clients"] = clients
    write_clients_raw(path, data)


def connect_xmlrpc(cfg: ClientOdooConfig) -> tuple[Any, str, int, str]:
    """Retourne (models_proxy, db, uid, password) pour les scripts type personalize_syscohada."""
    base = normalize_odoo_base_url(cfg.url).rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(cfg.db, cfg.user, cfg.password, {})
    if not uid:
        raise RuntimeError("Authentification Odoo refusée pour ce client.")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, cfg.db, int(uid), cfg.password


def client_has_app(cfg: ClientOdooConfig, app_id: str) -> bool:
    return app_id in cfg.apps
