"""Registre des bases clients Odoo (fichier JSON hors Git sur le serveur)."""
from __future__ import annotations

import json
import xmlrpc.client
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClientOdooConfig:
    id: str
    label: str
    url: str
    db: str
    user: str
    password: str


def load_clients_registry(path: str | Path) -> dict[str, ClientOdooConfig]:
    p = Path(path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, ClientOdooConfig] = {}
    for row in data.get("clients", []):
        cid = str(row["id"]).strip()
        out[cid] = ClientOdooConfig(
            id=cid,
            label=str(row.get("label") or cid),
            url=str(row["url"]).rstrip("/"),
            db=str(row["db"]),
            user=str(row["user"]),
            password=str(row["password"]),
        )
    return out


def connect_xmlrpc(cfg: ClientOdooConfig) -> tuple[Any, str, int, str]:
    """Retourne (models_proxy, db, uid, password) pour les scripts type personalize_syscohada."""
    base = cfg.url.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(cfg.db, cfg.user, cfg.password, {})
    if not uid:
        raise RuntimeError("Authentification Odoo refusée pour ce client.")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, cfg.db, int(uid), cfg.password
