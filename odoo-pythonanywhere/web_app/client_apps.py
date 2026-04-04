"""Catalogue des applications exposées aux clients (staff configure par client)."""
from __future__ import annotations

from typing import Any

# id technique → libellé + route Flask côté client ; staff utilise staff_apps_odoo_status avec client sélectionné
KNOWN_APPS: dict[str, dict[str, Any]] = {
    "odoo_status": {
        "label": "État connexion Odoo",
        "description": "Version serveur, authentification API, indicateur partenaires.",
        "client_endpoint": "legacy.client_odoo_status",
        "staff_endpoint": "staff.staff_apps_odoo_status",
    },
}

DEFAULT_APP_IDS = ("odoo_status",)


def normalize_app_ids(raw: list | tuple | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_APP_IDS
    out: list[str] = []
    for a in raw:
        s = str(a).strip()
        if s in KNOWN_APPS and s not in out:
            out.append(s)
    return tuple(out) if out else DEFAULT_APP_IDS


def apps_for_template(app_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for aid in app_ids:
        meta = KNOWN_APPS.get(aid)
        if not meta:
            continue
        row = {
            "id": aid,
            "label": meta["label"],
            "description": meta.get("description", ""),
            "client_endpoint": meta["client_endpoint"],
        }
        if meta.get("staff_endpoint"):
            row["staff_endpoint"] = meta["staff_endpoint"]
        rows.append(row)
    return rows
