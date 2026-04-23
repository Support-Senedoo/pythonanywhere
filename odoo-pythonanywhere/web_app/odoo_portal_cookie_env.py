"""Lecture du cookie portail odoo.com depuis l’environnement (évite de le recoller à chaque requête)."""
from __future__ import annotations

import os
from pathlib import Path

_MAX_COOKIE_CHARS = 16000


def read_portal_cookie_from_environment() -> str | None:
    """
    Ordre : ``TOOLBOX_ODOO_PORTAL_COOKIE`` (ligne brute), sinon contenu de ``TOOLBOX_ODOO_PORTAL_COOKIE_FILE``.
    Le fichier peut contenir soit la valeur seule, soit une ligne ``Cookie: …`` (préfixe retiré).
    """
    raw = (os.environ.get("TOOLBOX_ODOO_PORTAL_COOKIE") or "").strip()
    if raw:
        return raw[:_MAX_COOKIE_CHARS]
    path = (os.environ.get("TOOLBOX_ODOO_PORTAL_COOKIE_FILE") or "").strip()
    if not path:
        return None
    try:
        data = Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not data:
        return None
    if data.lower().startswith("cookie:"):
        data = data[7:].strip()
    return data[:_MAX_COOKIE_CHARS]


def portal_cookie_configured_in_environment() -> bool:
    return bool(read_portal_cookie_from_environment())
