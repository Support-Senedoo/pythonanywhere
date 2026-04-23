#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ouvre un navigateur **visible**, charge odoo.com puis la page « Mes bases ».

Intervention : captcha + login dans la fenêtre. Dès que l’URL contient ``/my/databases``,
affiche la ligne ``Cookie`` (stdout) et optionnellement l’écrit dans un fichier.

Dépendances : ``pip install -r requirements-capture-browser.txt`` puis
``playwright install chromium`` (et ``playwright install firefox`` si ``--browser firefox``).

**Si le captcha échoue systématiquement dans la fenêtre Playwright** :

1. Utilise ``--browser chrome`` (Chrome / Chromium Google installé sur la machine, souvent mieux noté).
2. Utilise ``--profile ~/.cache/senedoo_odoo_portal_pw`` : la **première** fois tu passes captcha + login
   dans cette fenêtre ; les prochaines exécutions réutilisent le même profil (souvent **sans** recaptcha).
3. Essaie ``--browser firefox``.
4. Connexion en **4G / autre réseau** que le bureau (box pro, VPN).
5. Dernier recours : **Chrome ou Safari sans script** — connecte-toi à odoo.com, Mes bases,
   puis copie le Cookie depuis les outils développeur (onglet Réseau) ; test avec
   ``scripts/verify_odoo_portal_cookie.py``.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: WPS433
    except ImportError as e:
        print(
            "Playwright manquant. Installez :\n"
            "  pip install -r requirements-capture-browser.txt\n"
            "  playwright install chromium\n"
            "  # si --browser firefox : playwright install firefox",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    return sync_playwright


def _portal_lang() -> str:
    return (os.environ.get("TOOLBOX_ODOO_PORTAL_LANG") or "/fr_FR").strip() or "/fr_FR"


def _portal_origin() -> str:
    return (os.environ.get("TOOLBOX_ODOO_PORTAL_ORIGIN") or "https://www.odoo.com").rstrip("/")


def _chromium_launch_args() -> list[str]:
    """Réduit un peu la signature « bot » (sans garantie contre reCAPTCHA / Turnstile)."""
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
    ]


def _context_options() -> dict:
    return {
        "viewport": {"width": 1400, "height": 900},
        "locale": "fr-FR",
        "timezone_id": "Africa/Dakar",
        "ignore_https_errors": False,
    }


def _print_captcha_help() -> None:
    print(
        "\n--- Captcha qui refuse de se valider ? ---\n"
        "  1) Relance avec :  --browser chrome --profile ~/.cache/senedoo_odoo_portal_pw\n"
        "  2) Ou :  --browser firefox\n"
        "  3) Réseau mobile / hors VPN entreprise\n"
        "  4) Sans Playwright : navigateur normal + copie Cookie + verify_odoo_portal_cookie.py\n",
        file=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture cookie portail odoo.com après login manuel (Playwright).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--write-file",
        metavar="PATH",
        help="Écrire le cookie dans ce fichier (mode 600), prêt pour TOOLBOX_ODOO_PORTAL_COOKIE_FILE",
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "chrome", "firefox"),
        default="chromium",
        help="Moteur : chromium (défaut), chrome (Chrome Google installé), ou firefox",
    )
    parser.add_argument(
        "--profile",
        metavar="DIR",
        help="Dossier profil persistant Chromium/Chrome : session réutilisée entre les lancements "
        "(créez un dossier vide ou réutilisez le même chemin). Fortement recommandé si captcha bloque.",
    )
    args = parser.parse_args()

    origin = _portal_origin()
    lang = _portal_lang()
    if not lang.startswith("/"):
        lang = "/" + lang
    databases_url = f"{origin}{lang}/my/databases"
    login_url = f"{origin}{lang}/web/login?redirect={quote(lang + '/my/databases', safe='')}"

    sync_playwright = _require_playwright()
    ctx_options = _context_options()
    browser = None
    context = None

    try:
        with sync_playwright() as p:
            if args.profile and args.browser != "firefox":
                profile_dir = str(Path(args.profile).expanduser())
                Path(profile_dir).mkdir(parents=True, exist_ok=True)
                launch_kw: dict = {
                    "user_data_dir": profile_dir,
                    "headless": False,
                    "args": _chromium_launch_args(),
                    **ctx_options,
                }
                if args.browser == "chrome":
                    launch_kw["channel"] = "chrome"
                context = p.chromium.launch_persistent_context(**launch_kw)
                page = context.pages[0] if context.pages else context.new_page()
                print(f"Profil persistant : {profile_dir}", file=sys.stderr)
            elif args.browser == "firefox":
                browser = p.firefox.launch(headless=False)
                context = browser.new_context(**ctx_options)
                page = context.new_page()
            else:
                launch_kw2: dict = {
                    "headless": False,
                    "args": _chromium_launch_args(),
                }
                if args.browser == "chrome":
                    launch_kw2["channel"] = "chrome"
                browser = p.chromium.launch(**launch_kw2)
                context = browser.new_context(**ctx_options)
                page = context.new_page()

            print(f"Cible « Mes bases » : {databases_url}", file=sys.stderr)
            print(
                "→ Connectez-vous dans la fenêtre (captcha inclus). "
                "Le script attend jusqu’à 10 min que l’URL contienne /my/databases …",
                file=sys.stderr,
            )

            try:
                # D’abord Mes bases : si session déjà valide (profil persistant), pas de login.
                page.goto(databases_url, wait_until="domcontentloaded", timeout=120_000)
                time.sleep(1.5)
                cur = page.url or ""
                if "/my/databases" not in cur or "web/login" in cur.lower():
                    print(
                        f"→ Redirection login ou session absente — ouverture : {login_url}",
                        file=sys.stderr,
                    )
                    page.goto(login_url, wait_until="domcontentloaded", timeout=120_000)

                try:
                    page.wait_for_function(
                        "() => { const p = document.location.pathname || ''; "
                        "return p.includes('/my/databases') && !p.includes('/web/login'); }",
                        timeout=600_000,
                    )
                except Exception as e:
                    print(f"Échec (timeout 10 min) : {e}", file=sys.stderr)
                    _print_captcha_help()
                    raise SystemExit(2) from e

                jar = context.cookies([page.url])
                parts = [
                    f"{c['name']}={c['value']}"
                    for c in jar
                    if c.get("name") and c.get("value") is not None
                ]
                header = "; ".join(parts)
                if not header.strip():
                    print("Aucun cookie collecté pour l’URL courante.", file=sys.stderr)
                    _print_captcha_help()
                    raise SystemExit(3)

                line = header
                print(line)
                if args.write_file:
                    out = Path(args.write_file).expanduser()
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(line + "\n", encoding="utf-8")
                    try:
                        out.chmod(0o600)
                    except OSError:
                        pass
                    print(
                        f"Écrit : {out}\n"
                        "Sur PythonAnywhere : TOOLBOX_ODOO_PORTAL_COOKIE_FILE + Reload Web.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "\nCollez cette ligne dans TOOLBOX_ODOO_PORTAL_COOKIE ou un fichier "
                        "pour TOOLBOX_ODOO_PORTAL_COOKIE_FILE — voir toolbox-env-exemple.txt.",
                        file=sys.stderr,
                    )
            finally:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
    except SystemExit:
        raise
    except Exception as e:
        print(f"Erreur : {e}", file=sys.stderr)
        _print_captcha_help()
        raise SystemExit(4) from e


if __name__ == "__main__":
    main()
