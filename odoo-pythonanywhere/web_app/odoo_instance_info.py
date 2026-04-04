"""Lecture d’informations instance Odoo (version publique + paramètres après authentification)."""
from __future__ import annotations

from typing import Any

import xmlrpc.client

from odoo_client import normalize_odoo_base_url
from personalize_syscohada_detail import execute_kw


def read_public_server_version(base_url: str) -> dict[str, Any]:
    """Appelle xmlrpc/2/common.version() sans authentification (disponible sur la plupart des instances)."""
    try:
        u = normalize_odoo_base_url(base_url).rstrip("/") + "/xmlrpc/2/common"
        common = xmlrpc.client.ServerProxy(u, allow_none=True)
        v = common.version()
        return v if isinstance(v, dict) else {"raw": v}
    except Exception as e:
        return {"_xmlrpc_error": str(e)}


def _get_param(models: Any, db: str, uid: int, password: str, key: str) -> Any:
    try:
        return execute_kw(models, db, uid, password, "ir.config_parameter", "get_param", [key])
    except Exception:
        return None


def collect_authenticated_instance_metadata(
    models: Any,
    db: str,
    uid: int,
    password: str,
    base_url: str,
) -> list[tuple[str, str]]:
    """Paires (libellé, valeur) pour affichage ; champs absents ou vides omis."""
    rows: list[tuple[str, str]] = []
    pub = read_public_server_version(base_url)
    if pub.get("_xmlrpc_error"):
        rows.append(("Version publique (common)", f"— {pub['_xmlrpc_error']}"))
    else:
        if pub.get("server_version"):
            rows.append(("Version serveur (common.version)", str(pub["server_version"])))
        if pub.get("server_version_info") is not None:
            rows.append(("Détail version (tuple)", str(pub["server_version_info"])))
        serie = pub.get("server_serie") or pub.get("series")
        if serie:
            rows.append(("Série Odoo", str(serie)))

    param_map = [
        ("database.uuid", "UUID base"),
        ("database.expiration_date", "Date limite / expiration"),
        ("database.expiration_reason", "Motif (expiration / abonnement)"),
        ("database.enterprise_code", "Code entreprise"),
        ("database.is_neutralized", "Base neutralisée"),
        ("web.base.url", "URL configurée (web.base.url)"),
    ]
    for k, label in param_map:
        v = _get_param(models, db, uid, password, k)
        if v not in (None, False, ""):
            rows.append((label, str(v)))

    try:
        ent = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "search_count",
            [[("name", "=", "web_enterprise"), ("state", "=", "installed")]],
        )
        rows.append(
            (
                "Type / édition",
                "Enterprise (web_enterprise installé)" if ent else "Community (sans web_enterprise)",
            )
        )
    except Exception as e:
        rows.append(("Type / édition", f"— {e}"))

    try:
        cids = execute_kw(models, db, uid, password, "res.company", "search", [[]], {"limit": 1})
        if cids:
            c = execute_kw(
                models,
                db,
                uid,
                password,
                "res.company",
                "read",
                [cids],
                {"fields": ["name"]},
            )
            if c and c[0].get("name"):
                rows.append(("Société principale", str(c[0]["name"])))
    except Exception:
        pass

    try:
        bids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "search",
            [[("name", "=", "base"), ("state", "=", "installed")]],
            {"limit": 1},
        )
        if bids:
            br = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.module.module",
                "read",
                [bids],
                {"fields": ["latest_version"]},
            )
            if br and br[0].get("latest_version"):
                rows.append(("Module « base » (latest_version)", str(br[0]["latest_version"])))
    except Exception:
        pass

    rows.append(("Nom technique PostgreSQL (db)", db))
    rows.append(("URL instance", normalize_odoo_base_url(base_url)))
    return rows
