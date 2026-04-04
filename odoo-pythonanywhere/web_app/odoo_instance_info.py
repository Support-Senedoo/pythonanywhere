"""Lecture d’informations instance Odoo (version publique + paramètres après authentification)."""
from __future__ import annotations

from typing import Any

import xmlrpc.client

from odoo_client import normalize_odoo_base_url
from personalize_syscohada_detail import execute_kw


def format_server_version_info(info: Any) -> str | None:
    """
    Normalise le tuple ``server_version_info`` renvoyé par ``common.version()`` (ex. ``(19, 0, 1, 0)``).

    Sur Odoo SaaS / récent, c’est souvent la forme la plus stable pour comparer les instances.
    """
    if info is None:
        return None
    if isinstance(info, (list, tuple)) and info:
        parts: list[str] = []
        for x in info[:6]:
            if isinstance(x, bool):
                parts.append("1" if x else "0")
            elif x is None:
                continue
            else:
                parts.append(str(x))
        return ".".join(parts) if parts else None
    return str(info)


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
            rows.append(("Version annoncée par le serveur (common.version)", str(pub["server_version"])))
        svi = pub.get("server_version_info")
        if svi is not None:
            rows.append(("server_version_info (brut)", str(svi)))
            svi_fmt = format_server_version_info(svi)
            if svi_fmt:
                rows.append(("Version dérivée de server_version_info", svi_fmt))
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
        ent_ids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "search",
            [[("name", "=", "web_enterprise"), ("state", "=", "installed")]],
            {"limit": 1},
        )
        ent = bool(ent_ids)
        rows.append(
            (
                "Type / édition",
                "Enterprise (web_enterprise installé)" if ent else "Community (sans web_enterprise)",
            )
        )
        if ent_ids:
            wer = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.module.module",
                "read",
                [ent_ids],
                {"fields": ["latest_version", "published_version"]},
            )
            if wer:
                w = wer[0]
                if w.get("latest_version"):
                    rows.append(
                        (
                            "Module web_enterprise — version installée (DB)",
                            str(w["latest_version"]),
                        )
                    )
                if w.get("published_version"):
                    rows.append(
                        (
                            "Module web_enterprise — published_version",
                            str(w["published_version"]),
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

    # Version « métier » de la base : ir.module.module sur base (latest_version = installée en DB, Odoo 19).
    try:
        mod_fields = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "fields_get",
            [],
            {"attributes": ["type"]},
        )
        base_read_fields = ["latest_version", "published_version"]
        if isinstance(mod_fields, dict) and "installed_version" in mod_fields:
            base_read_fields.append("installed_version")
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
                {"fields": base_read_fields},
            )
            if br:
                b0 = br[0]
                if b0.get("latest_version"):
                    rows.append(
                        (
                            "Version Odoo (module base, installée en base)",
                            str(b0["latest_version"]),
                        )
                    )
                if b0.get("published_version"):
                    rows.append(
                        (
                            "Module base — published_version (dépôt / SaaS)",
                            str(b0["published_version"]),
                        )
                    )
                if b0.get("installed_version"):
                    rows.append(
                        (
                            "Module base — installed_version (réf. disque / calcul Odoo)",
                            str(b0["installed_version"]),
                        )
                    )
    except Exception:
        pass

    rows.append(("Nom technique PostgreSQL (db)", db))
    rows.append(("URL instance", normalize_odoo_base_url(base_url)))
    return rows
