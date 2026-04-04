"""Sonde les bases Odoo accessibles avec un couple login / mot de passe (XML-RPC)."""
from __future__ import annotations

import http.cookiejar
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client
from typing import Any
from urllib.parse import urlparse

from odoo_client import normalize_odoo_base_url

MAX_DATABASES_TO_PROBE = 48


def _is_odoo_db_service_disabled(msg: str) -> bool:
    """
    Odoo SaaS 19+ : dispatch_rpc lève KeyError sur le service « db » (non exposé).
    str(Fault) repasse par repr() : on voit souvent \\'db\\' et non la sous-chaîne 'db' nue.
    """
    if "KeyError" not in msg:
        return False
    if "rpc_dispatchers" in msg or "dispatch_rpc" in msg:
        return True
    if "'db'" in msg:
        return True
    if "\\'db\\'" in msg:
        return True
    return False


def format_db_list_error(exc: BaseException) -> str:
    """Message lisible quand list() sur /xmlrpc/2/db échoue (souvent Odoo SaaS sans service « db »)."""
    msg = str(exc)
    if _is_odoo_db_service_disabled(msg):
        return (
            "Le service XML-RPC « db » n’est pas disponible sur cette instance "
            "(cas fréquent sur Odoo SaaS / versions récentes). "
            "Impossible de récupérer la liste des bases par ce canal."
        )
    if isinstance(exc, xmlrpc.client.Fault) and len(msg) > 400:
        return (
            "db.list() a été refusé ou n’est pas pris en charge par le serveur. "
            "Détail technique (extrait) : "
            + msg[:320].replace("\n", " ")
            + "…"
        )
    return msg


def _safe_url(base_url: str) -> tuple[str | None, str | None]:
    u = normalize_odoo_base_url((base_url or "").strip())
    if not u:
        return None, "URL vide."
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None, "URL invalide (http/https + hôte requis)."
    return u, None


def _host_to_db_name(hostname: str) -> str:
    """Déduit le nom de base PostgreSQL courant depuis l’hôte *.odoo.com / *.eu.odoo.com."""
    host = (hostname or "").lower().rstrip(".")
    for suf in (".eu.odoo.com", ".odoo.com"):
        if host.endswith(suf):
            return host[: -len(suf)]
    return ""


def _extract_instance_urls_from_portal_html(html: str) -> list[str]:
    """Repère les URL d’instances hébergées chez Odoo dans le HTML « Mes bases »."""
    found: set[str] = set()
    for m in re.finditer(r'https://([\w.-]+\.odoo\.com)(?:/|\?|"|\'|>|<|\s)', html, re.I):
        host = m.group(1).lower()
        if host.startswith("www.") or "odoocdn" in host:
            continue
        found.add(f"https://{host}")
    return sorted(found)


def fetch_odoo_com_portal_probes(login: str, password: str) -> tuple[list[tuple[str, str]], str | None]:
    """
    Connexion sur www.odoo.com (formulaire web) puis lecture de /my/databases.
    Retourne une liste de (url_rpc_base, nom_base_pg) et éventuellement un message d’erreur.
    """
    login_c = (login or "").strip()
    pwd = password or ""
    if not login_c or not pwd:
        return [], "Login et mot de passe sont requis pour le mode sans URL (portail Odoo.com)."

    origin = (os.environ.get("TOOLBOX_ODOO_PORTAL_ORIGIN") or "https://www.odoo.com").rstrip("/")
    lang = (os.environ.get("TOOLBOX_ODOO_PORTAL_LANG") or "/fr_FR").strip()
    if not lang.startswith("/"):
        lang = "/" + lang
    lang = lang.rstrip("/")

    login_page = f"{origin}{lang}/web/login"
    redirect_path = f"{lang}/my/databases"
    databases_url = f"{origin}{lang}/my/databases"

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [
        (
            "User-Agent",
            "SenedooToolbox/1.2 (+urllib; +https://github.com/Support-Senedoo/pythonanywhere)",
        )
    ]

    try:
        q = urllib.parse.urlencode({"redirect": redirect_path})
        r = opener.open(f"{login_page}?{q}", timeout=35)
        html = r.read().decode("utf-8", "replace")
    except (OSError, urllib.error.HTTPError) as e:
        return [], f"Réseau / portail Odoo.com (page login) : {e!s}"

    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    if not m:
        return [], "Impossible de lire le formulaire de connexion odoo.com (jeton CSRF manquant)."

    data = urllib.parse.urlencode(
        {
            "csrf_token": m.group(1),
            "login": login_c,
            "password": pwd,
            "redirect": redirect_path,
        }
    ).encode()
    req = urllib.request.Request(
        login_page,
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        r2 = opener.open(req, timeout=35)
        r2.read()
    except (OSError, urllib.error.HTTPError) as e:
        return [], f"Connexion portail Odoo.com : {e!s}"

    try:
        r3 = opener.open(databases_url, timeout=35)
        db_html = r3.read().decode("utf-8", "replace")
        final_u = r3.geturl()
    except (OSError, urllib.error.HTTPError) as e:
        return [], f"Lecture « Mes bases » : {e!s}"

    if "web/login" in final_u:
        return [], (
            "Échec de connexion au portail Odoo.com (e-mail, mot de passe, ou accès « Mes bases »). "
            "Vérifiez aussi la 2FA / sécurité du compte."
        )

    raw_urls = _extract_instance_urls_from_portal_html(db_html)
    probes: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for u in raw_urls:
        base = u.rstrip("/")
        p = urlparse(base)
        dbn = _host_to_db_name(p.hostname or "")
        if not dbn:
            continue
        key = (base, dbn)
        if key in seen:
            continue
        seen.add(key)
        probes.append((base, dbn))

    if not probes:
        return [], (
            "Aucune instance *.odoo.com détectée sur la page « Mes bases ». "
            "Le portail a peut‑être changé, ou le compte n’a pas d’instance listée ici."
        )

    return probes, None


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


def probe_account_databases(
    base_url: str,
    login: str,
    password: str,
) -> dict[str, Any]:
    """
    Retourne un dict avec :
    - url_ok, url_error
    - server_version (dict ou erreur)
    - db_list_error (si list() ou portail échoue)
    - probe_mode: \"instance_xmlrpc\" | \"odoo_com_portal\"
    - candidate_names (liste affichée)
    - truncated (bool)
    - rows : liste de { database, instance_url, accessible, uid, ... }
    """
    out: dict[str, Any] = {
        "url_ok": False,
        "url_error": None,
        "server_version": None,
        "db_list_error": None,
        "probe_mode": None,
        "candidate_names": [],
        "truncated": False,
        "rows": [],
    }

    login_c = (login or "").strip()
    pwd = password or ""

    probes: list[tuple[str, str]] = []

    if not (base_url or "").strip():
        out["url_ok"] = True
        out["probe_mode"] = "odoo_com_portal"
        pairs, perr = fetch_odoo_com_portal_probes(login_c, pwd)
        if perr:
            out["db_list_error"] = perr
            return out
        probes = pairs
    else:
        u, err = _safe_url(base_url)
        if err:
            out["url_error"] = err
            return out
        out["url_ok"] = True
        out["probe_mode"] = "instance_xmlrpc"
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
            out["db_list_error"] = format_db_list_error(e)

        merged = sorted(set(from_list), key=str.lower)
        probes = [(base, db) for db in merged]

    truncated = len(probes) > MAX_DATABASES_TO_PROBE
    if truncated:
        probes = probes[:MAX_DATABASES_TO_PROBE]
    out["truncated"] = truncated
    out["candidate_names"] = [f"{db} — {b}" for b, db in probes]

    if out["probe_mode"] == "odoo_com_portal" and probes:
        first_base = probes[0][0]
        common0 = xmlrpc.client.ServerProxy(f"{first_base}/xmlrpc/2/common", allow_none=True)
        try:
            out["server_version"] = common0.version()
        except Exception as e:
            out["server_version"] = {"_error": str(e)}

    if not login_c:
        out["rows"] = [
            {
                "database": db,
                "instance_url": b,
                "accessible": False,
                "uid": None,
                "companies": [],
                "base_version": None,
                "detail": "Login vide — non testé.",
            }
            for b, db in probes
        ]
        return out

    for rpc_base, db in probes:
        row: dict[str, Any] = {
            "database": db,
            "instance_url": rpc_base,
            "accessible": False,
            "uid": None,
            "companies": [],
            "base_version": None,
            "detail": "",
        }
        common = xmlrpc.client.ServerProxy(f"{rpc_base}/xmlrpc/2/common", allow_none=True)
        models = xmlrpc.client.ServerProxy(f"{rpc_base}/xmlrpc/2/object", allow_none=True)
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
