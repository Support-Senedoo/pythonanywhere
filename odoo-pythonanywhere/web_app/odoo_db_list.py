"""Liste des bases Odoo : XML-RPC db.list + liste configurable (ex. bases gérées Senedoo)."""
from __future__ import annotations

import re
import xmlrpc.client
from typing import Any
from urllib.parse import urlparse


def managed_databases_from_env(raw: str | None) -> list[str]:
    """Parse TOOLBOX_ODOO_MANAGED_DATABASES : noms séparés par virgule, point-virgule ou saut de ligne."""
    if not (raw or "").strip():
        return []
    parts = re.split(r"[\n;,]+", raw)
    return sorted({p.strip() for p in parts if p.strip()}, key=str.lower)


def fetch_databases_from_server(base_url: str) -> tuple[list[str], str | None]:
    """
    Appelle /xmlrpc/2/db list() sur l’URL Odoo.
    Retourne (liste, erreur). Erreur non bloquante si la liste env est utilisée ailleurs.
    """
    u = (base_url or "").strip().rstrip("/")
    if not u:
        return [], "URL vide."
    parsed = urlparse(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return [], "URL invalide (http/https requis)."
    endpoint = f"{u}/xmlrpc/2/db"
    try:
        proxy = xmlrpc.client.ServerProxy(endpoint, allow_none=True)
        raw: Any = proxy.list()
        if not isinstance(raw, list):
            return [], "Le serveur n’a pas renvoyé une liste de bases."
        names = [str(x).strip() for x in raw if str(x).strip()]
        return sorted(set(names), key=str.lower), None
    except xmlrpc.client.Fault as e:
        return [], f"XML-RPC : {e.faultString}"
    except OSError as e:
        return [], f"Réseau / SSL : {e!s}"
    except Exception as e:
        return [], str(e)


def merge_database_suggestions(
    *,
    url: str,
    env_managed_raw: str | None,
) -> tuple[list[str], str | None]:
    """Fusionne bases renvoyées par le serveur (si URL fournie) et liste configurée sur le portail."""
    from_env = managed_databases_from_env(env_managed_raw)
    u = (url or "").strip()
    if not u:
        return sorted(from_env, key=str.lower), None
    from_server, err = fetch_databases_from_server(u)
    merged = sorted(set(from_server) | set(from_env), key=str.lower)
    return merged, err
