#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ouvre un navigateur Chromium (visible), charge la connexion odoo.com puis Mes bases.

Intervention humaine : uniquement captcha / login dans la fenêtre. Dès que l’URL contient
``/my/databases``, le script affiche la ligne ``Cookie`` à coller dans la toolbox ou à mettre
dans TOOLBOX_ODOO_PORTAL_COOKIE / un fichier pour TOOLBOX_ODOO_PORTAL_COOKIE_FILE.

Dépendances : pip install playwright && playwright install chromium
  (voir requirements-capture-browser.txt à la racine du projet)
"""
from __future__ import annotations

import argparse
import os
import sys
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
            "  playwright install chromium",
            file=sys.stderr,
        )
        raise SystemExit(1) from e
    return sync_playwright


def _portal_lang() -> str:
    return (os.environ.get("TOOLBOX_ODOO_PORTAL_LANG") or "/fr_FR").strip() or "/fr_FR"


def _portal_origin() -> str:
    return (os.environ.get("TOOLBOX_ODOO_PORTAL_ORIGIN") or "https://www.odoo.com").rstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture cookie portail odoo.com après login manuel.")
    parser.add_argument(
        "--write-file",
        metavar="PATH",
        help="Écrire le cookie dans ce fichier (mode 600), prêt pour TOOLBOX_ODOO_PORTAL_COOKIE_FILE",
    )
    args = parser.parse_args()

    origin = _portal_origin()
    lang = _portal_lang()
    if not lang.startswith("/"):
        lang = "/" + lang
    login_url = f"{origin}{lang}/web/login?redirect={quote(lang + '/my/databases', safe='')}"

    sync_playwright = _require_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        print(f"Ouverture : {login_url}", file=sys.stderr)
        print(
            "→ Connectez-vous dans la fenêtre (captcha inclus). "
            "Le script attend la page « Mes bases »…",
            file=sys.stderr,
        )
        page.goto(login_url, wait_until="domcontentloaded", timeout=120_000)
        try:
            page.wait_for_function(
                "() => document.location.href.includes('/my/databases')",
                timeout=600_000,
            )
        except Exception as e:
            print(f"Échec d’attente Mes bases (timeout 10 min) : {e}", file=sys.stderr)
            raise SystemExit(2) from e

        # Cookies applicables à l’URL courante (équivalent navigateur pour Mes bases).
        jar = context.cookies([page.url])
        parts = [f"{c['name']}={c['value']}" for c in jar if c.get("name") and c.get("value") is not None]
        header = "; ".join(parts)
        if not header.strip():
            print("Aucun cookie collecté pour l’hôte courant — vérifiez le domaine.", file=sys.stderr)
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
                "Sur PythonAnywhere : définissez TOOLBOX_ODOO_PORTAL_COOKIE_FILE avec ce chemin "
                "(fichier hors Git, chmod 600) puis rechargement Web.",
                file=sys.stderr,
            )
        else:
            print(
                "\nCollez cette ligne dans la variable TOOLBOX_ODOO_PORTAL_COOKIE (onglet Web PA) "
                "ou créez un fichier et utilisez TOOLBOX_ODOO_PORTAL_COOKIE_FILE — voir toolbox-env-exemple.txt.",
                file=sys.stderr,
            )
        browser.close()


if __name__ == "__main__":
    main()
