"""Registre des bases clients Odoo (fichier JSON hors Git sur le serveur)."""
from __future__ import annotations

import json
import re
import tempfile
import xmlrpc.client
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from odoo_client import normalize_odoo_base_url

from web_app.client_apps import normalize_app_ids

# Clé registre = nom technique de la base Odoo (normalisé minuscules), aligné PostgreSQL / Odoo courant.
_REGISTRY_DB_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _normalize_environment(raw: Any) -> str:
    s = str(raw or "production").strip().lower()
    return s if s in ("production", "test") else "production"


def normalize_registry_db_key(db: str) -> str:
    """Valide et normalise le nom de base utilisé comme identifiant unique dans le registre et les comptes."""
    s = (db or "").strip().lower()
    if not _REGISTRY_DB_KEY_RE.match(s):
        raise ValueError(
            "Nom de base (db) : lettre ou chiffre en tête, puis lettres, chiffres, tiret ou underscore (max 63 car.)."
        )
    return s


def validate_client_id(client_id: str) -> str:
    """Alias : l’identifiant portail / registre est le nom de base normalisé."""
    return normalize_registry_db_key(client_id)


def registry_netloc(cfg: ClientOdooConfig) -> str:
    return urlparse(cfg.url).netloc or ""


@dataclass(frozen=True)
class ClientOdooConfig:
    id: str
    label: str
    url: str
    db: str
    user: str
    password: str
    apps: tuple[str, ...]
    environment: str = "production"
    portfolio_client_id: str | None = None


def _parse_portfolio_client_id(raw: Any) -> str | None:
    s = str(raw or "").strip().lower()
    if not s:
        return None
    try:
        return normalize_registry_db_key(s)
    except ValueError:
        return None


def _row_to_config(row: dict[str, Any]) -> ClientOdooConfig:
    db_key = normalize_registry_db_key(str(row.get("db", "")).strip())
    apps = normalize_app_ids(row.get("apps"))
    label_raw = str(row.get("label", "")).strip()
    label_use = label_raw if label_raw else db_key
    return ClientOdooConfig(
        id=db_key,
        label=label_use,
        url=normalize_odoo_base_url(str(row["url"])),
        db=db_key,
        user=str(row["user"]).strip(),
        password=str(row["password"]),
        apps=apps,
        environment=_normalize_environment(row.get("environment")),
        portfolio_client_id=_parse_portfolio_client_id(row.get("portfolio_client_id")),
    )


def clients_sorted_for_select(reg: dict[str, ClientOdooConfig]) -> list[tuple[str, ClientOdooConfig]]:
    """Liste plate triée par nom de base puis id (pour <select>)."""
    return sorted(
        reg.items(),
        key=lambda x: (x[1].db.casefold(), 0 if x[1].environment == "production" else 1, x[0].casefold()),
    )


def clients_grouped_for_select(reg: dict[str, ClientOdooConfig]) -> list[tuple[str, list[tuple[str, ClientOdooConfig]]]]:
    """Rétrocompatibilité gabarits : un seul groupe « Bases » avec toutes les entrées triées."""
    items = clients_sorted_for_select(reg)
    return [("Bases", items)] if items else []


def distinct_odoo_hosts(reg: dict[str, ClientOdooConfig]) -> list[str]:
    """Hôtes distincts (schéma + host + port) pour filtrer les bases sur un même serveur Odoo."""
    hosts = {registry_netloc(c) for c in reg.values() if registry_netloc(c)}
    return sorted(hosts, key=str.casefold)


def configs_for_same_host(reg: dict[str, ClientOdooConfig], netloc: str) -> list[tuple[str, ClientOdooConfig]]:
    """Bases partageant le même hôte d’URL (prod + test sur un même serveur, etc.)."""
    host = (netloc or "").strip().lower()
    if not host:
        return []
    return sorted(
        [(cid, c) for cid, c in reg.items() if registry_netloc(c).lower() == host],
        key=lambda x: (0 if x[1].environment == "production" else 1, x[1].db.casefold()),
    )


def configs_for_portfolio_client(
    reg: dict[str, ClientOdooConfig], portfolio_client_id: str
) -> list[tuple[str, ClientOdooConfig]]:
    """Bases Odoo rattachées au même client portefeuille (slug dans portfolio_client_id)."""
    key = _parse_portfolio_client_id(portfolio_client_id)
    if not key:
        return []
    return sorted(
        [(cid, c) for cid, c in reg.items() if (c.portfolio_client_id or "").strip().lower() == key],
        key=lambda x: (0 if x[1].environment == "production" else 1, x[1].db.casefold()),
    )


def configs_for_label(reg: dict[str, ClientOdooConfig], label: str) -> list[tuple[str, ClientOdooConfig]]:
    """Déprécié : conservé pour appels anciens ; équivalent à même hôte si label ressemble à un netloc, sinon vide."""
    lab = (label or "").strip()
    if not lab:
        return []
    return configs_for_same_host(reg, lab)


def count_bases_for_portfolio_client(path: str | Path, portfolio_client_id: str) -> int:
    """Nombre de bases Odoo dont le champ portfolio_client_id correspond (normalisé)."""
    key = (portfolio_client_id or "").strip().lower()
    if not key:
        return 0
    n = 0
    for cfg in load_clients_registry(path).values():
        if (cfg.portfolio_client_id or "").strip().lower() == key:
            n += 1
    return n


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


def upsert_client(
    path: str | Path,
    client_id: str,
    label: str,
    url: str,
    db: str,
    user: str,
    password: str | None,
    apps: list[str],
    *,
    environment: str | None = None,
    portfolio_client_id: str | None = None,
) -> None:
    """Enregistre une base ; id reste le nom de base normalisé ; label = libellé affichage (défaut = db)."""
    del client_id
    db_key = normalize_registry_db_key(str(db or "").strip())
    display_label = (label or "").strip() or db_key
    data = read_clients_raw(path)
    clients: list[dict[str, Any]] = list(data.get("clients", []))
    url = (url or "").strip().rstrip("/")
    user = (user or "").strip()
    app_ids = list(normalize_app_ids(apps))

    found_idx: int | None = None
    for i, row in enumerate(clients):
        rid = str(row.get("id", "")).strip().lower()
        try:
            rdb = normalize_registry_db_key(str(row.get("db", "")).strip())
        except ValueError:
            rdb = ""
        if rid == db_key or rdb == db_key:
            found_idx = i
            break

    if found_idx is not None:
        row = clients[found_idx]
        pwd = password if password is not None else str(row.get("password", ""))
        env_use = (
            _normalize_environment(environment)
            if environment is not None
            else _normalize_environment(row.get("environment"))
        )
        pcid: str | None
        if portfolio_client_id is not None:
            pcid = _parse_portfolio_client_id(portfolio_client_id)
        else:
            pcid = _parse_portfolio_client_id(row.get("portfolio_client_id"))
        row_out: dict[str, Any] = {
            "id": db_key,
            "label": display_label,
            "url": url,
            "db": db_key,
            "user": user,
            "password": pwd,
            "apps": app_ids,
            "environment": env_use,
        }
        if pcid:
            row_out["portfolio_client_id"] = pcid
        clients[found_idx] = row_out
    else:
        if not password:
            raise ValueError("Mot de passe Odoo requis pour une nouvelle base.")
        pcid_new = _parse_portfolio_client_id(portfolio_client_id) if portfolio_client_id is not None else None
        env_use = _normalize_environment(environment or "production")
        new_row: dict[str, Any] = {
            "id": db_key,
            "label": display_label,
            "url": url,
            "db": db_key,
            "user": user,
            "password": password,
            "apps": app_ids,
            "environment": env_use,
        }
        if pcid_new:
            new_row["portfolio_client_id"] = pcid_new
        clients.append(new_row)
    data["clients"] = clients
    write_clients_raw(path, data)


def delete_client(path: str | Path, client_id: str) -> None:
    cid = normalize_registry_db_key(str(client_id or "").strip())
    data = read_clients_raw(path)
    clients = [c for c in data.get("clients", []) if str(c.get("id", "")).strip().lower() != cid]
    if len(clients) == len(data.get("clients", [])):
        raise ValueError("Base introuvable.")
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


def migrate_registry_ids_to_database_names(
    clients_path: str | Path,
    users_path: str | Path | None = None,
) -> dict[str, str]:
    """
    Réécrit toolbox_clients.json : id = label = nom de base normalisé.
    Retourne l’ancienne map old_registry_id -> new_db_key pour contrôle.
    Optionnel : met à jour client_id dans toolbox_users.json.
    """
    cp = Path(clients_path)
    data = read_clients_raw(cp)
    raw_clients: list[dict[str, Any]] = list(data.get("clients", []))
    mapping: dict[str, str] = {}
    seen_keys: set[str] = set()
    new_rows: list[dict[str, Any]] = []

    for row in raw_clients:
        db_raw = str(row.get("db", "")).strip()
        db_key = normalize_registry_db_key(db_raw)
        old_id = str(row.get("id", db_key)).strip().lower()
        if old_id != db_key:
            mapping[old_id] = db_key
        if db_key in seen_keys:
            raise ValueError(f"Deux entrées partagent la base {db_key!r} : fusionnez ou corrigez avant migration.")
        seen_keys.add(db_key)
        new_row = dict(row)
        new_row["id"] = db_key
        if not str(new_row.get("label", "")).strip():
            new_row["label"] = db_key
        new_row["db"] = db_key
        new_rows.append(new_row)

    data["clients"] = new_rows
    write_clients_raw(cp, data)

    if users_path is not None:
        up = Path(users_path)
        if up.is_file():
            udata = json.loads(up.read_text(encoding="utf-8"))
            users = udata.get("users", [])
            for u in users:
                if not isinstance(u, dict):
                    continue
                oc = str(u.get("client_id", "")).strip().lower()
                if oc and oc in mapping:
                    u["client_id"] = mapping[oc]
            udata["users"] = users
            write_clients_raw(up, udata)

    return mapping
