#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML-RPC Odoo avec le **même registre** que la toolbox PythonAnywhere (``toolbox_clients.json``).

Ne charge **pas** Flask : utilisable depuis une console Bash PA (hors venv web) ou en local.

Résolution de la base (``client_id`` = nom de base normalisé, comme dans le menu staff) :

1. ``--client-id <db>``
2. ``TOOLBOX_XMLRPC_CLIENT_ID`` (sur PA : même valeur que la base choisie dans l’utilitaire staff)
3. ``TOOLBOX_XMLRPC_CLIENT_ID_FILE`` : fichier dont la première ligne est le ``client_id``
4. Fichier miroir de l’interface staff (écrit automatiquement au choix de base) :
   ``TOOLBOX_STAFF_SELECTED_CLIENT_FILE`` ou par défaut ``<racine>/.toolbox_staff_selected_client``
5. registre avec **une seule** base → utilisée par défaut

Fichier clients : ``TOOLBOX_CLIENTS_PATH``, ``--clients-path``, ou
``<racine_odoo-pythonanywhere>/toolbox_clients.json``.

Exemples (dossier courant = ``odoo-pythonanywhere/``) :

  python3 scripts/xmlrpc_toolbox_client.py --list

  python3 scripts/xmlrpc_toolbox_client.py --client-id ma_base

  TOOLBOX_XMLRPC_CLIENT_ID=ma_base python3 scripts/xmlrpc_toolbox_client.py

  python3 scripts/xmlrpc_toolbox_client.py --json \\
    '{"model":"res.users","method":"search_read","args":[[["id","=",2]]],"kwargs":{"fields":["login"],"limit":1}}'

Sur PythonAnywhere :

  export TOOLBOX_CLIENTS_PATH=/home/senedoo/pythonanywhere/odoo-pythonanywhere/toolbox_clients.json
  export TOOLBOX_XMLRPC_CLIENT_ID=ma_base
  python3 ~/pythonanywhere/odoo-pythonanywhere/scripts/xmlrpc_toolbox_client.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xmlrpc.client
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from odoo_client import normalize_odoo_base_url  # noqa: E402

_REGISTRY_DB_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def normalize_registry_db_key(db: str) -> str:
    s = (db or "").strip().lower()
    if not _REGISTRY_DB_KEY_RE.match(s):
        raise ValueError(
            "Nom de base (db) : lettre ou chiffre en tête, puis lettres, chiffres, tiret ou underscore (max 63 car.)."
        )
    return s


@dataclass(frozen=True)
class ClientOdooConfig:
    id: str
    url: str
    db: str
    user: str
    password: str
    environment: str = "production"


def _normalize_environment(raw: Any) -> str:
    s = str(raw or "production").strip().lower()
    return s if s in ("production", "test") else "production"


def _row_to_config(row: dict[str, Any]) -> ClientOdooConfig:
    db_key = normalize_registry_db_key(str(row.get("db", "")).strip())
    return ClientOdooConfig(
        id=db_key,
        url=normalize_odoo_base_url(str(row["url"])),
        db=db_key,
        user=str(row["user"]).strip(),
        password=str(row["password"]),
        environment=_normalize_environment(row.get("environment")),
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


def registry_netloc(cfg: ClientOdooConfig) -> str:
    return urlparse(cfg.url).netloc or ""


def connect_xmlrpc(cfg: ClientOdooConfig) -> tuple[Any, str, int, str]:
    base = normalize_odoo_base_url(cfg.url).rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(cfg.db, cfg.user, cfg.password, {})
    if not uid:
        raise RuntimeError("Authentification Odoo refusée pour ce client.")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, cfg.db, int(uid), cfg.password


def _default_clients_path() -> Path:
    return Path(
        os.environ.get("TOOLBOX_CLIENTS_PATH", "").strip()
        or (_ROOT / "toolbox_clients.json"),
    )


def _read_client_id_from_file() -> str:
    raw = (os.environ.get("TOOLBOX_XMLRPC_CLIENT_ID_FILE") or "").strip()
    if not raw:
        return ""
    p = Path(raw)
    if not p.is_file():
        return ""
    line = (p.read_text(encoding="utf-8").splitlines() or [""])[0].strip().lower()
    return line


def _staff_selected_client_file_path() -> Path:
    raw = (os.environ.get("TOOLBOX_STAFF_SELECTED_CLIENT_FILE") or "").strip()
    if raw:
        return Path(raw)
    return _ROOT / ".toolbox_staff_selected_client"


def _read_staff_selected_client_id() -> str:
    p = _staff_selected_client_file_path()
    if not p.is_file():
        return ""
    line = (p.read_text(encoding="utf-8").splitlines() or [""])[0].strip().lower()
    return line


def resolve_client_id(
    explicit: str | None,
    reg: dict[str, ClientOdooConfig],
) -> str:
    cid = (explicit or "").strip().lower()
    if cid:
        return cid
    cid = (os.environ.get("TOOLBOX_XMLRPC_CLIENT_ID") or "").strip().lower()
    if cid:
        return cid
    cid = _read_client_id_from_file()
    if cid:
        return cid
    cid = _read_staff_selected_client_id()
    if cid:
        return cid
    if len(reg) == 1:
        return next(iter(reg.keys()))
    raise SystemExit(
        "client_id manquant : passez --client-id <nom_base>, ou définissez "
        "TOOLBOX_XMLRPC_CLIENT_ID (recommandé sur PA), ou TOOLBOX_XMLRPC_CLIENT_ID_FILE "
        "vers un fichier contenant le nom de base sur la première ligne, ou laissez la toolbox "
        "écrire le fichier staff (TOOLBOX_STAFF_SELECTED_CLIENT_FILE / .toolbox_staff_selected_client), "
        "ou un registre avec une seule base."
    )


def cmd_list(reg: dict[str, ClientOdooConfig]) -> int:
    if not reg:
        print("Aucun client dans le registre.", file=sys.stderr)
        return 1
    for cid, cfg in sorted(reg.items(), key=lambda x: (x[1].db.casefold(), x[0])):
        env = cfg.environment or "production"
        host = registry_netloc(cfg) or "?"
        print(f"{cid}\t{host}\t{env}\t{cfg.user}")
    return 0


def cmd_probe(models: Any, db: str, uid: int, pwd: str, common: Any, label: str) -> int:
    print(label, file=sys.stderr)
    ver = common.version()
    print("server_version:", ver.get("server_version", ver))
    n = models.execute_kw(db, uid, pwd, "res.partner", "search_count", [[]], {})
    print("res.partner search_count:", n)
    rows = models.execute_kw(
        db,
        uid,
        pwd,
        "res.users",
        "read",
        [[uid]],
        {"fields": ["login", "name"]},
    )
    if rows:
        print("utilisateur_xmlrpc:", rows[0])
    return 0


def cmd_json(models: Any, db: str, uid: int, pwd: str, payload: dict[str, Any]) -> int:
    model = str(payload.get("model") or "").strip()
    method = str(payload.get("method") or "").strip()
    if not model or not method:
        raise SystemExit('Le JSON doit contenir "model" et "method".')
    args = payload.get("args")
    if args is None:
        args = []
    if not isinstance(args, list):
        raise SystemExit('"args" doit être une liste (JSON).')
    kwargs = payload.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        raise SystemExit('"kwargs" doit être un objet (JSON).')
    out = models.execute_kw(db, uid, pwd, model, method, args, kwargs)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--clients-path",
        type=Path,
        default=None,
        help="Chemin toolbox_clients.json (défaut : TOOLBOX_CLIENTS_PATH ou ./toolbox_clients.json).",
    )
    p.add_argument(
        "--client-id",
        default="",
        help="Identifiant registre (= nom de base Odoo normalisé), comme dans la toolbox staff.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Lister les bases du registre (sans mots de passe) et quitter.",
    )
    p.add_argument(
        "--json",
        dest="json_call",
        default="",
        metavar="PAYLOAD",
        help='Appel execute_kw : JSON {"model","method","args","kwargs"} (kwargs optionnel).',
    )
    args = p.parse_args()

    cpath = args.clients_path or _default_clients_path()
    reg = load_clients_registry(cpath)
    if args.list:
        return cmd_list(reg)

    cid = resolve_client_id(args.client_id, reg)
    if cid not in reg:
        print(f"client_id inconnu dans le registre : {cid!r}", file=sys.stderr)
        print("Bases connues :", ", ".join(sorted(reg.keys())) or "(aucune)", file=sys.stderr)
        return 1
    cfg = reg[cid]
    base = normalize_odoo_base_url(cfg.url).rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    models, db, uid, pwd = connect_xmlrpc(cfg)
    banner = f"# client_id={cid} db={db} url={base}"
    if args.json_call.strip():
        try:
            payload = json.loads(args.json_call)
        except json.JSONDecodeError as e:
            print("JSON invalide :", e, file=sys.stderr)
            return 1
        if not isinstance(payload, dict):
            print("Le JSON racine doit être un objet.", file=sys.stderr)
            return 1
        print(banner, file=sys.stderr)
        return cmd_json(models, db, uid, pwd, payload)

    return cmd_probe(models, db, uid, pwd, common, banner)


if __name__ == "__main__":
    raise SystemExit(main())
