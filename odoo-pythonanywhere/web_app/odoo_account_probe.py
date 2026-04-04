"""Sonde les bases Odoo accessibles avec un couple login / mot de passe (XML-RPC)."""
from __future__ import annotations

import gzip
import http.cookiejar
import os
import re
import zlib
import time
import urllib.error
import urllib.parse
import urllib.request
import xmlrpc.client
from typing import Any
from urllib.parse import urlparse

from odoo_client import normalize_odoo_base_url

MAX_DATABASES_TO_PROBE = 48

# Hôtes odoo.com présents sur le portail marketing / login mais ce ne sont pas des bases client.
_PORTAL_IGNORE_INSTANCE_HOSTS: frozenset[str] = frozenset(
    {
        "www.odoo.com",
        "apps.odoo.com",
        "runbot.odoo.com",
        "upgrade.odoo.com",
        "podcast.odoo.com",
        "shop.odoo.com",
        "help.odoo.com",
    }
)


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


def _portal_page_suggests_captcha(html: str) -> bool:
    """Détecte reCAPTCHA, hCaptcha, Cloudflare Turnstile, etc. dans le HTML."""
    low = html.lower()
    markers = (
        "g-recaptcha",
        "recaptcha",
        "hcaptcha",
        "cf-turnstile",
        "challenges.cloudflare.com",
        "turnstile",
        "data-sitekey",
        "challenge-platform",
        "captcha-container",
    )
    return any(m in low for m in markers)


def _extract_odoo_portal_csrf_token(html: str) -> str | None:
    """
    Le portail www.odoo.com a servi le CSRF soit en <input name=\"csrf_token\">, soit dans le JS
    « var odoo = { csrf_token: \"…\" } » (cas actuel sur le frontend website).
    """
    patterns = (
        # <input> : ordre name/value variable, espaces / retours ligne
        r'<input\b[^>]*\bname\s*=\s*["\']csrf_token["\'][^>]*\bvalue\s*=\s*["\']([^"\']+)["\']',
        r'<input\b[^>]*\bvalue\s*=\s*["\']([^"\']+)["\'][^>]*\bname\s*=\s*["\']csrf_token["\']',
        r'name="csrf_token"[^>]*\bvalue="([^"]+)"',
        r'\bvalue="([^"]+)"[^>]*name="csrf_token"',
        r"name='csrf_token'[^>]*\bvalue='([^']+)'",
        r"\bvalue='([^']+)'[^>]*name='csrf_token'",
        # Odoo website / assets : odoo.__session_info__ ou var odoo = { csrf_token: "…" }
        r'\bcsrf_token\s*:\s*"([^"]+)"',
        r"\bcsrf_token\s*:\s*'([^']+)'",
        # JSON compact éventuel dans la page
        r'"csrf_token"\s*:\s*"([^"]+)"',
    )
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            tok = (m.group(1) or "").strip()
            if tok:
                return tok
    return None


def _portal_captcha_blocked_message() -> str:
    return (
        "Le portail Odoo.com exige une étape anti-robot (captcha / reCAPTCHA / Turnstile). "
        "Les requêtes depuis PythonAnywhere (IP de datacenter) la déclenchent très souvent ; "
        "la toolbox ne peut pas la remplir. "
        "Pistes : utiliser le mode avec URL d’instance (db.list) si le serveur l’expose ; "
        "ou ouvrir « Mes bases » dans un navigateur et recopier les liens ; "
        "ou lancer un script équivalent depuis votre PC (réseau résidentiel)."
    )


def _portal_browser_header_pairs() -> list[tuple[str, str]]:
    """En-têtes proches d’un navigateur (évite en partie les blocages « bot » trop grossiers)."""
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    return [
        ("User-Agent", ua),
        (
            "Accept",
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        ),
        ("Accept-Language", "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"),
        # Pas « gzip » : urllib ne décompresse pas Content-Encoding:gzip si on l’accepte explicitement,
        # ce qui casse tout parsing HTML (CSRF, liens Mes bases).
        ("Accept-Encoding", "identity"),
        ("Upgrade-Insecure-Requests", "1"),
        ("DNT", "1"),
    ]


def _decode_portal_http_body(headers: Any, raw: bytes) -> str:
    """
    Texte UTF-8 du corps HTTP. Même avec Accept-Encoding: identity, certains CDN renvoient du gzip
    sans toujours respecter la négociation ; urllib ne décompresse pas — d’où HTML illisible et CSRF introuvable.
    """
    if not raw:
        return ""
    enc = ""
    try:
        enc = (headers.get("Content-Encoding") or "").lower().strip()
    except (AttributeError, TypeError):
        pass
    data = raw
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(raw)
        except OSError:
            data = raw
    elif enc == "deflate":
        try:
            data = zlib.decompress(raw, -zlib.MAX_WBITS)
        except OSError:
            data = raw
    return data.decode("utf-8", "replace")


def _extract_instance_urls_from_portal_html(html: str) -> list[str]:
    """Repère les URL d’instances hébergées chez Odoo dans le HTML « Mes bases »."""
    found: set[str] = set()
    for m in re.finditer(r"https://([\w.-]+\.odoo\.com)\b", html, re.I):
        host = m.group(1).lower().rstrip(".")
        if host.startswith("www.") or "odoocdn" in host or host in _PORTAL_IGNORE_INSTANCE_HOSTS:
            continue
        found.add(f"https://{host}")
    for m in re.finditer(r"//([\w.-]+\.odoo\.com)\b", html, re.I):
        host = m.group(1).lower().rstrip(".")
        if host.startswith("www.") or "odoocdn" in host or host in _PORTAL_IGNORE_INSTANCE_HOSTS:
            continue
        found.add(f"https://{host}")
    return sorted(found)


def _portal_origin_lang_databases_url() -> tuple[str, str, str]:
    """Retourne (origin sans slash final, chemin langue ex. /fr_FR, URL complète Mes bases)."""
    origin = (os.environ.get("TOOLBOX_ODOO_PORTAL_ORIGIN") or "https://www.odoo.com").rstrip("/")
    lang = (os.environ.get("TOOLBOX_ODOO_PORTAL_LANG") or "/fr_FR").strip()
    if not lang.startswith("/"):
        lang = "/" + lang
    lang = lang.rstrip("/")
    databases_url = f"{origin}{lang}/my/databases"
    return origin, lang, databases_url


def _normalize_portal_cookie_header(raw: str | None) -> str | None:
    """Nettoie l’en-tête Cookie collé depuis les outils développeur (une ligne ou plusieurs)."""
    s = (raw or "").strip()
    if not s:
        return None
    if len(s) > 16000:
        return None
    if s.lower().startswith("cookie:"):
        s = s[7:].strip()
    s = re.sub(r"[\r\n]+", "; ", s)
    s = re.sub(r";\s*;+", ";", s)
    s = s.strip().strip(";").strip()
    return s or None


def _probes_from_mes_bases_html(db_html: str) -> tuple[list[tuple[str, str]], str | None]:
    """Construit la liste (url_rpc, nom_base_pg) à partir du HTML de la page « Mes bases »."""
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
        low = db_html.lower()
        bits: list[str] = []
        if "web/login" in low or ('name="login"' in low and "csrf_token" in low):
            bits.append(
                "Le HTML ressemble à une page de connexion (session absente ou expirée), pas à la liste des bases."
            )
        if "my/databases" not in low and "mes bases" not in low:
            bits.append(
                "Le contenu ne ressemble pas à la page « Mes bases » (mauvaise langue / URL ? "
                "Vérifiez TOOLBOX_ODOO_PORTAL_LANG, ex. /fr_FR, comme dans l’URL du navigateur)."
            )
        if re.search(r"apps\.odoo\.com|runbot\.odoo\.com", db_html, re.I):
            bits.append(
                "Seuls des liens génériques du site odoo.com (apps, runbot…) sont présents — pas d’instance client détectée."
            )
        hint = (" " + " ".join(bits)) if bits else ""
        return [], (
            "Aucune instance *.odoo.com exploitable détectée sur la page."
            + hint
            + " Depuis PythonAnywhere, le login + mot de passe échoue souvent (captcha) : "
            "connectez-vous dans le navigateur, ouvrez « Mes bases », puis utilisez le champ « Cookie portail » "
            "(en-tête Cookie de la requête document vers /my/databases)."
        )
    return probes, None


def fetch_odoo_com_portal_probes_from_browser_session(cookie_raw: str) -> tuple[list[tuple[str, str]], str | None]:
    """
    Après connexion manuelle sur odoo.com (captcha validé dans le navigateur), réutilise les cookies
    pour charger /my/databases depuis le serveur (ex. PythonAnywhere) sans refaire le login HTTP.
    """
    ch = _normalize_portal_cookie_header(cookie_raw)
    if not ch:
        return [], (
            "Cookie de session invalide ou trop long (max. 16000 caractères). "
            "Collez l’en-tête « Cookie » complet depuis les outils développeur (voir aide sur la page)."
        )
    _origin, _lang, databases_url = _portal_origin_lang_databases_url()
    headers = dict(_portal_browser_header_pairs())
    headers["Cookie"] = ch
    req = urllib.request.Request(databases_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=35) as r:
            raw = r.read()
            db_html = _decode_portal_http_body(r.headers, raw)
            final_u = r.geturl()
    except (OSError, urllib.error.HTTPError) as e:
        return [], f"Lecture « Mes bases » avec session navigateur : {e!s}"

    if "web/login" in final_u:
        return [], (
            "Les cookies ne suffisent pas (redirection vers la connexion). "
            "Ouvrez la même langue que l’outil (ex. /fr_FR), connectez-vous, ouvrez « Mes bases », "
            "puis recopiez tout l’en-tête Cookie de la requête vers cette page (onglet Réseau)."
        )
    if "accounts.odoo.com" in final_u:
        return [], (
            "Redirection vers accounts.odoo.com : la session navigateur ne correspond pas à ce que le portail attend. "
            "Reprenez le Cookie sur la requête document vers www.odoo.com/…/my/databases après « Mes bases »."
        )

    return _probes_from_mes_bases_html(db_html)


def fetch_odoo_com_portal_probes(login: str, password: str) -> tuple[list[tuple[str, str]], str | None]:
    """
    Connexion sur www.odoo.com (formulaire web) puis lecture de /my/databases.
    Retourne une liste de (url_rpc_base, nom_base_pg) et éventuellement un message d’erreur.
    """
    login_c = (login or "").strip()
    pwd = password or ""
    if not login_c or not pwd:
        return [], (
            "Pour lister les bases via le portail Odoo.com (sans URL d’instance), "
            "le mot de passe est obligatoire — l’URL n’est pas requise dans ce mode. "
            "Remplissez le mot de passe puis renvoyez le formulaire."
        )

    origin, lang, databases_url = _portal_origin_lang_databases_url()
    login_page = f"{origin}{lang}/web/login"
    redirect_path = f"{lang}/my/databases"

    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = _portal_browser_header_pairs()

    try:
        q = urllib.parse.urlencode({"redirect": redirect_path})
        login_url_with_q = f"{login_page}?{q}"
        r = opener.open(login_url_with_q, timeout=35)
        raw_login = r.read()
        html = _decode_portal_http_body(r.headers, raw_login)
    except (OSError, urllib.error.HTTPError) as e:
        return [], f"Réseau / portail Odoo.com (page login) : {e!s}"

    if _portal_page_suggests_captcha(html):
        return [], _portal_captcha_blocked_message()

    csrf = _extract_odoo_portal_csrf_token(html)
    if not csrf:
        hint = ""
        if len(html) < 4000 and "csrf_token" not in html.lower():
            hint = (
                " La réponse ressemble à une page vide ou bloquée (souvent gzip non décodé ou WAF) ; "
                "vérifiez le déploiement de la toolbox, ou utilisez le mode « cookie navigateur » après connexion manuelle."
            )
        return [], (
            "Impossible de lire le formulaire de connexion odoo.com (jeton CSRF manquant — le portail a peut‑être changé)."
            + hint
        )

    time.sleep(0.6)

    data = urllib.parse.urlencode(
        {
            "csrf_token": csrf,
            "login": login_c,
            "password": pwd,
            "redirect": redirect_path,
        }
    ).encode()
    post_h = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": login_url_with_q,
        "Origin": origin,
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }
    req = urllib.request.Request(login_url_with_q, data=data, method="POST", headers=post_h)
    try:
        r2 = opener.open(req, timeout=35)
        r2.read()
    except (OSError, urllib.error.HTTPError) as e:
        return [], f"Connexion portail Odoo.com : {e!s}"

    try:
        r3 = opener.open(databases_url, timeout=35)
        raw_db = r3.read()
        db_html = _decode_portal_http_body(r3.headers, raw_db)
        final_u = r3.geturl()
    except (OSError, urllib.error.HTTPError) as e:
        return [], f"Lecture « Mes bases » : {e!s}"

    if "web/login" in final_u:
        hint = ""
        low = db_html.lower()
        if "two-factor" in low or "two factor" in low or "authenticator" in low or "2fa" in low:
            hint = (
                " La page renvoyée évoque une double authentification : ce script ne peut pas la valider — "
                "désactivez temporairement la 2FA sur le portail odoo.com, ou utilisez le mode avec URL d’instance."
            )
        elif _portal_page_suggests_captcha(db_html):
            hint = " " + _portal_captcha_blocked_message()
        return [], (
            "Échec de connexion au portail Odoo.com (e-mail, mot de passe, ou accès « Mes bases »). "
            "Vérifiez identifiants, droits sur « Mes bases », et si le compte impose une connexion via accounts.odoo.com / SSO uniquement."
            + hint
            + f" (URL finale : {final_u})"
        )

    probes, perr = _probes_from_mes_bases_html(db_html)
    if perr:
        return [], perr
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
    *,
    portal_session_cookie: str | None = None,
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
        cookie_raw = (portal_session_cookie or "").strip()
        if cookie_raw:
            pairs, perr = fetch_odoo_com_portal_probes_from_browser_session(cookie_raw)
        else:
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
