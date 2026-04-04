"""Sonde les bases Odoo accessibles avec un couple login / mot de passe (XML-RPC)."""
from __future__ import annotations

import re
import xmlrpc.client
from typing import Any
from urllib.parse import urlparse

MAX_DATABASES_TO_PROBE = 48


def _safe_url(base_url: str) -> tuple[str | None, str | None]:
    u = (base_url or "").strip().rstrip("/")
    if not u:
        return None, "URL vide."
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None, "URL invalide (http/https + hôte requis)."
    return u, None


def _company_label(name_val: Any) -> str:
    if isinstance(name_val, dict):
        for k in ("fr_FR", "en_US", "fr_BE"):
            if name_val.get(k):
                return str(name_val[k])
        for v in name_val.values():
            if v:
                return str(v)
    if name_val is None:
        return "—"
    return str(name_val)


def parse_extra_database_names(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[\n;,]+", raw)
    return sorted({p.strip() for p in parts if p.strip()}, key=str.lower)


def probe_account_databases(
    base_url: str,
    login: str,
    password: str,
    extra_databases_text: str,
) -> dict[str, Any]:
    """
    Retourne un dict avec :
    - url_ok, url_error
    - server_version (dict ou erreur)
    - db_list_error (si list() échoue)
    - candidate_names (liste des noms testés)
    - truncated (bool)
    - rows : liste de { database, accessible, uid, companies, base_version, detail }
    """
    out: dict[str, Any] = {
        "url_ok": False,
        "url_error": None,
        "server_version": None,
        "db_list_error": None,
        "candidate_names": [],
        "truncated": False,
        "rows": [],
    }
    u, err = _safe_url(base_url)
    if err:
        out["url_error"] = err
        return out
    out["url_ok"] = True
    base = u

    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    try:
        out["server_version"] = common.version()
    except Exception as e:
        out["server_version"] = {"_error": str(e)}

    from_list: list[str] = []
    try:
        db_proxy = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/db", allow_none=True)
        raw_list = db_proxy.list()
        if isinstance(raw_list, list):
            from_list = [str(x).strip() for x in raw_list if str(x).strip()]
    except Exception as e:
        out["db_list_error"] = str(e)

    extras = parse_extra_database_names(extra_databases_text)
    merged = sorted(set(from_list) | set(extras), key=str.lower)
    truncated = len(merged) > MAX_DATABASES_TO_PROBE
    if truncated:
        merged = merged[:MAX_DATABASES_TO_PROBE]
    out["candidate_names"] = merged
    out["truncated"] = truncated

    login_c = (login or "").strip()
    pwd = password or ""
    if not login_c:
        out["rows"] = [
            {
                "database": d,
                "accessible": False,
                "uid": None,
                "companies": [],
                "base_version": None,
                "detail": "Login vide — non testé.",
            }
            for d in merged
        ]
        return out

    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)

    for db in merged:
        row: dict[str, Any] = {
            "database": db,
            "accessible": False,
            "uid": None,
            "companies": [],
            "base_version": None,
            "detail": "",
        }
        try:
            uid = common.authenticate(db, login_c, pwd, {})
            if not uid:
                row["detail"] = "Authentification refusée (mauvais mot de passe ou utilisateur absent de cette base)."
                out["rows"].append(row)
                continue
            uid_i = int(uid)
            row["accessible"] = True
            row["uid"] = uid_i

            detail_bits: list[str] = []
            try:
                comps = models.execute_kw(
                    db,
                    uid_i,
                    pwd,
                    "res.company",
                    "search_read",
                    [[]],
                    {"fields": ["name", "email"], "limit": 8},
                )
                if isinstance(comps, list):
                    for c in comps:
                        nm = _company_label(c.get("name"))
                        em = (c.get("email") or "").strip()
                        row["companies"].append(f"{nm}" + (f" <{em}>" if em else ""))
            except Exception as e:
                detail_bits.append(f"Sociétés : {e!s}")

            try:
                base_mod = models.execute_kw(
                    db,
                    uid_i,
                    pwd,
                    "ir.module.module",
                    "search_read",
                    [[["name", "=", "base"]]],
                    {"fields": ["name", "latest_version"], "limit": 1},
                )
                if base_mod and isinstance(base_mod, list):
                    row["base_version"] = base_mod[0].get("latest_version") or "—"
            except Exception:
                pass

            try:
                users = models.execute_kw(
                    db,
                    uid_i,
                    pwd,
                    "res.users",
                    "read",
                    [[uid_i]],
                    {"fields": ["login", "name", "lang"]},
                )
                if users and isinstance(users, list):
                    u0 = users[0]
                    lu = (u0.get("login") or "").strip()
                    nm = (u0.get("name") or "").strip()
                    lg = (u0.get("lang") or "").strip()
                    ub = [f"API : {lu or '—'}"]
                    if nm:
                        ub.append(f"nom {nm}")
                    if lg:
                        ub.append(f"langue {lg}")
                    detail_bits.append(" ; ".join(ub))
            except Exception as e:
                detail_bits.append(f"Utilisateur : {e!s}")

            row["detail"] = " ".join(detail_bits).strip()

        except xmlrpc.client.Fault as e:
            row["detail"] = f"XML-RPC : {e.faultString}"
        except OSError as e:
            row["detail"] = f"Réseau : {e!s}"
        except Exception as e:
            row["detail"] = str(e)

        out["rows"].append(row)

    return out
