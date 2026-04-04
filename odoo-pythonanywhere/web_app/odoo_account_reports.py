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


def _ultimate_root_report_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    *,
    max_hops: int = 24,
) -> int:
    """Remonte les ``root_report_id`` jusqu’au rapport racine (menu / variantes Odoo)."""
    cur = int(report_id)
    for _ in range(max_hops):
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "read",
            [[cur]],
            {"fields": ["root_report_id"]},
        )
        if not rows:
            return cur
        rr = rows[0].get("root_report_id")
        if not rr or not (isinstance(rr, (list, tuple)) and rr[0]):
            return cur
        nxt = int(rr[0])
        if nxt == cur:
            return cur
        cur = nxt
    return cur


def _account_report_has_field(
    models: Any,
    db: str,
    uid: int,
    password: str,
    field_name: str,
) -> bool:
    try:
        fg = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "fields_get",
            [],
            {"attributes": ["type"]},
        )
    except Exception:
        return False
    return field_name in fg


def _link_report_copy_to_root(
    models: Any,
    db: str,
    uid: int,
    password: str,
    new_report_id: int,
    root_report_id: int,
) -> None:
    """Rattache la copie à la balance / racine d’origine (variante du même ``root_report_id``)."""
    if not _account_report_has_field(models, db, uid, password, "root_report_id"):
        return
    if new_report_id == root_report_id:
        return
    try:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[new_report_id], {"root_report_id": root_report_id}],
        )
    except Exception:
        pass


def _proposed_name_search_strings(proposed: Any) -> list[str]:
    out: list[str] = []
    if isinstance(proposed, dict):
        for k in ("fr_FR", "fr_BE", "fr_CA", "fr_CH", "en_US", "en_GB"):
            v = proposed.get(k)
            if v and str(v).strip():
                out.append(str(v).strip())
        for v in proposed.values():
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
    elif proposed:
        out.append(str(proposed).strip())
    return out or ["Rapport"]


def _copy_name_collides_existing(
    models: Any,
    db: str,
    uid: int,
    password: str,
    exclude_id: int,
    proposed: Any,
    *,
    root_for_sibling_check: int | None,
) -> bool:
    """True si un autre rapport porte déjà ce nom (recherche par langue + variantes même racine)."""
    langs = ("fr_FR", "fr_BE", "fr_CA", "en_US", "en_GB")
    for s in _proposed_name_search_strings(proposed):
        for lang in langs:
            hits = execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "search",
                [[("id", "!=", exclude_id), ("name", "=", s)]],
                {"limit": 2, "context": {"lang": lang}},
            )
            if hits:
                return True
        hits_plain = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "search",
            [[("id", "!=", exclude_id), ("name", "=", s)]],
            {"limit": 2},
        )
        if hits_plain:
            return True

    prop_display = format_report_name(proposed).strip().lower()
    if prop_display and prop_display != "—" and root_for_sibling_check:
        sib = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "search",
            [[("root_report_id", "=", root_for_sibling_check), ("id", "!=", exclude_id)]],
            {"limit": 500},
        )
        if sib:
            rows = execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "read",
                [sib],
                {"fields": ["name"]},
            )
            for r in rows:
                if format_report_name(r.get("name")).strip().lower() == prop_display:
                    return True
    return False


def _write_duplicate_unique_name(
    models: Any,
    db: str,
    uid: int,
    password: str,
    new_report_id: int,
    raw_source_name: Any,
    name_suffix: str,
    *,
    root_for_uniqueness: int | None,
) -> None:
    for i in range(50):
        suf = name_suffix if i == 0 else f"{name_suffix} ({i + 1})"
        proposed = _copy_report_display_name(raw_source_name, suf)
        if _copy_name_collides_existing(
            models,
            db,
            uid,
            password,
            new_report_id,
            proposed,
            root_for_sibling_check=root_for_uniqueness,
        ):
            continue
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[new_report_id], {"name": proposed}],
        )
        return
    raise ValueError(
        "Impossible d’attribuer un nom de rapport unique après 50 tentatives ; "
        "renommez manuellement dans Odoo."
    )


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
    Duplique un account.report (API ``copy``), rattache la copie au même ``root_report_id``
    que la balance / le rapport d’origine (racine remontée), puis renomme avec suffixe Senedoo.

    Si le nom existe déjà (autre rapport ou autre variante sous la même racine), le suffixe est
    incrémenté : ``… (2)``, ``… (3)``, etc.

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
    root_target = _ultimate_root_report_id(models, db, uid, password, source_report_id)

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

    _link_report_copy_to_root(models, db, uid, password, new_id, root_target)
    _write_duplicate_unique_name(
        models,
        db,
        uid,
        password,
        new_id,
        raw_name,
        name_suffix,
        root_for_uniqueness=root_target,
    )
    return new_id
