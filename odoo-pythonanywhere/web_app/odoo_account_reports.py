"""Liste / filtre des rapports comptables Odoo (account.report) pour l’utilitaire staff."""
from __future__ import annotations

from typing import Any

from personalize_syscohada_detail import execute_kw
from web_app import app_version

# Titre spécifique à l’écran ; version / date / auteur = source unique app_version.py
UTILITY_TITLE = "Rapports comptables Odoo"
UTILITY_VERSION = app_version.TOOLBOX_APP_VERSION
UTILITY_DATE = app_version.TOOLBOX_APP_DATE
UTILITY_AUTHOR = app_version.TOOLBOX_APP_AUTHOR


def format_report_name(val: Any) -> str:
    """Affichage prioritaire en français (traductions Odoo sur account.report.name)."""
    if isinstance(val, dict):
        for k in ("fr_FR", "fr_BE", "fr_CA", "fr_CH", "fr_LU"):
            if val.get(k):
                return str(val[k])
        for key in sorted(val.keys()):
            if isinstance(key, str) and key.startswith("fr_") and val.get(key):
                return str(val[key])
        for k in ("en_US", "en_GB"):
            if val.get(k):
                return str(val[k])
        for v in val.values():
            if v:
                return str(v)
        return str(val)
    if val is None:
        return "—"
    return str(val)


def read_account_report_label(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> str:
    """Libellé du rapport en français (via contexte RPC)."""
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["name"]},
    )
    if not rows:
        return f"#{report_id}"
    return format_report_name(rows[0].get("name"))


def probe_odoo_reports_access(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> tuple[bool, str]:
    """Teste l’API sur la base : modèle account.report + comptage."""
    try:
        has_model = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.model",
            "search_count",
            [[("model", "=", "account.report")]],
        )
        if not has_model:
            return False, "Le modèle « account.report » est absent (module Comptabilité / version Odoo ?)."
        n = int(
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "search_count",
                [[]],
            )
        )
        return True, f"Connexion OK — {n} rapport(s) comptable(s) référencé(s)."
    except Exception as e:
        return False, str(e)


def search_account_reports(
    models: Any,
    db: str,
    uid: int,
    password: str,
    filter_text: str,
    *,
    limit: int = 400,
) -> list[dict[str, Any]]:
    q = (filter_text or "").strip()
    domain: list = []
    if q:
        domain = [("name", "ilike", q)]
    ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [domain],
        {"limit": limit, "order": "id desc"},
    )
    if not ids:
        return []
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [ids],
        {"fields": ["id", "name"]},
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "name": format_report_name(r.get("name")),
                "name_raw": r.get("name"),
            }
        )
    return out


def unlink_account_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> None:
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "unlink",
        [[report_id]],
    )
