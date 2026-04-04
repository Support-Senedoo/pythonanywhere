"""Liste / filtre des rapports comptables Odoo (account.report) pour l’utilitaire staff."""
from __future__ import annotations

from typing import Any

from odoo_client import normalize_odoo_base_url
from personalize_syscohada_detail import execute_kw
from web_app import app_version

# Titre spécifique à l’écran ; version / date / auteur = source unique app_version.py
UTILITY_TITLE = "Compte de résultat — personnalisation (détail / SYSCOHADA)"
UTILITY_TITLE_BALANCE = "Balance comptable — 6 colonnes (Senedoo)"
UTILITY_TITLE_PL_BUDGET = "Compte de résultat — analytique et budget"
UTILITY_VERSION = app_version.TOOLBOX_APP_VERSION
UTILITY_DATE = app_version.TOOLBOX_APP_DATE
UTILITY_AUTHOR = app_version.TOOLBOX_APP_AUTHOR


def account_report_odoo_form_url(base_url: str, report_id: int) -> str:
    """Lien backend Odoo vers la fiche du rapport comptable (ouverture / exécution manuelle)."""
    base = normalize_odoo_base_url(base_url).rstrip("/")
    return f"{base}/web#id={int(report_id)}&model=account.report&view_type=form"


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


def _merge_report_name_for_rename(raw_name: Any, new_label: str) -> Any:
    """Met à jour le champ name (traduit ou simple) pour l’affichage liste en français."""
    if isinstance(raw_name, dict):
        out = dict(raw_name)
        touched = False
        for k in list(out.keys()):
            if isinstance(k, str) and (k == "fr_FR" or k.startswith("fr_")):
                out[k] = new_label
                touched = True
        if not touched:
            out["fr_FR"] = new_label
        return out
    return new_label


def write_account_report_name(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    new_label: str,
) -> None:
    """Écrit le libellé du rapport dans Odoo (champ name, y compris traductions fr_*)."""
    label = (new_label or "").strip()
    if not label:
        raise ValueError("Le nouveau nom ne peut pas être vide.")
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
        raise ValueError(f"Rapport comptable id={report_id} introuvable.")
    merged = _merge_report_name_for_rename(rows[0].get("name"), label)
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], {"name": merged}],
    )


def _copy_report_display_name(raw_name: Any, suffix: str) -> Any:
    """Construit le nom affiché du rapport dupliqué (traductions Odoo ou chaîne simple)."""
    if isinstance(raw_name, dict):
        out = dict(raw_name)
        for key in ("fr_FR", "fr_BE", "fr_CA", "en_US", "en_GB"):
            v = out.get(key)
            if v and isinstance(v, str) and suffix.strip() not in v:
                out[key] = v.rstrip() + suffix
                return out
        for k, v in list(out.items()):
            if v and isinstance(v, str) and suffix.strip() not in v:
                out[k] = v.rstrip() + suffix
                return out
        return out
    s = str(raw_name or "Rapport").strip()
    return s + suffix if suffix.strip() not in s else s


def duplicate_account_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    source_report_id: int,
    *,
    name_suffix: str = " — copie Senedoo",
) -> int:
    """
    Duplique un account.report (API copy), puis renomme la copie.
    La personnalisation Senedoo doit toujours s’appliquer sur cette copie, pas sur l’original.
    """
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[source_report_id]],
        {"fields": ["name"]},
    )
    if not rows:
        raise ValueError(f"Rapport comptable id={source_report_id} introuvable.")
    raw_name = rows[0].get("name")
    new_res = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "copy",
        [source_report_id],
        {},
    )
    if isinstance(new_res, dict) and new_res.get("id") is not None:
        new_id = int(new_res["id"])
    elif isinstance(new_res, (list, tuple)):
        new_id = int(new_res[0])
    else:
        new_id = int(new_res)
    new_name = _copy_report_display_name(raw_name, name_suffix)
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[new_id], {"name": new_name}],
    )
    return new_id
