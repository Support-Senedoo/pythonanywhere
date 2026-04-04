#!/usr/bin/env python3
"""
Vérifie que les pages de personnalisation de rapports rendent le HTML attendu (session staff simulée).

  cd odoo-pythonanywhere
  python scripts/verify_accounting_reports_page.py

Sortie 0 = marqueurs obligatoires présents.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Présents sur chaque page utilitaire rapports (sans base sélectionnée)
REQUIRED_COMMON = [
    'id="ajouter-base-odoo"',
    'name="filter_host"',
    'name="new_db"',
    'name="new_environment"',
    'value="add_client"',
    "Ajouter une nouvelle base",
    "Enregistrer la base",
    "sn-page-bottom-flash",
    "Autres personnalisations",
]

REQUIRED_PL_STANDARD_BASE = [
    "Compte de résultat — personnalisation (détail / SYSCOHADA)",
    "compte de résultat personnalisé",
]

REQUIRED_BALANCE_PAGE = REQUIRED_COMMON + [
    "6 colonnes",
    "Balance comptable — 6 colonnes",
]

REQUIRED_PL_BUDGET_BASE = [
    "Compte de résultat — analytique et budget",
    "P&amp;L analytique et budget",
]

REQUIRED_BALANCE_WITH_CLIENT_EXTRA = [
    'id="form-personalize-balance"',
    'value="personalize_balance"',
]

REQUIRED_WITH_CLIENT_PL_STANDARD = [
    'id="sn-reports-list"',
    'id="report_id_p"',
    'id="form-personalize-report"',
    "sn-personalize-overlay",
    "Créer la copie et personnaliser",
]

REQUIRED_WITH_CLIENT_PL_BUDGET = [
    'id="sn-reports-list"',
    'id="report_id_ab"',
    'id="form-personalize-pl-budget"',
    "sn-personalize-overlay",
    "Créer la copie (détail + analytique / budget)",
]


def _missing_markers(html: str, markers: list[str]) -> list[str]:
    return [m for m in markers if m not in html]


def verify_local() -> int:
    from web_app import create_app
    from web_app.odoo_registry import load_clients_registry

    app = create_app()
    app.testing = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["role"] = "staff"
        sess["login"] = "html_verify_bot"

    reg = load_clients_registry(app.config["TOOLBOX_CLIENTS_PATH"])
    first_cid = next(iter(reg.keys()), None)

    pages: list[tuple[str, list[str], list[str]]] = [
        (
            "/staff/utilities/rapports-comptables",
            REQUIRED_COMMON + REQUIRED_PL_STANDARD_BASE,
            REQUIRED_WITH_CLIENT_PL_STANDARD,
        ),
        (
            "/staff/utilities/personalize-report",
            REQUIRED_COMMON + REQUIRED_PL_STANDARD_BASE,
            REQUIRED_WITH_CLIENT_PL_STANDARD,
        ),
        (
            "/staff/utilities/personalize-pl-budget",
            REQUIRED_COMMON + REQUIRED_PL_BUDGET_BASE,
            REQUIRED_WITH_CLIENT_PL_BUDGET,
        ),
        (
            "/staff/utilities/personalize-balance",
            REQUIRED_BALANCE_PAGE,
            REQUIRED_BALANCE_WITH_CLIENT_EXTRA + ["Ouvrir dans Odoo", 'id="sn-reports-list"'],
        ),
    ]

    for path, required, extra_with_client in pages:
        r = client.get(path)
        if r.status_code != 200:
            print(f"ERREUR {path} : HTTP {r.status_code}", file=sys.stderr)
            return 1
        html = r.get_data(as_text=True)
        missing = _missing_markers(html, required)
        if missing:
            print(f"ERREUR {path} : marqueurs absents :", file=sys.stderr)
            for m in missing:
                print(f"  - {m!r}", file=sys.stderr)
            return 1
        print(f"OK {path} ({len(html)} caractères)")

        if first_cid:
            r2 = client.get(f"{path}?client_id={first_cid}")
            if r2.status_code != 200:
                print(f"ERREUR {path}?client_id=… : HTTP {r2.status_code}", file=sys.stderr)
                return 1
            html2 = r2.get_data(as_text=True)
            missing2 = _missing_markers(html2, required + extra_with_client)
            if missing2:
                print(f"ERREUR {path}?client_id={first_cid} : marqueurs absents :", file=sys.stderr)
                for m in missing2:
                    print(f"  - {m!r}", file=sys.stderr)
                return 1
            print(f"OK {path}?client_id={first_cid} ({len(html2)} car.) — zone personnalisation")
        else:
            print(
                "Note : aucun client dans toolbox_clients.json — zone personnalisation avec client non vérifiée."
            )
    return 0


def verify_remote() -> int:
    import urllib.request

    url = (os.environ.get("TOOLBOX_VERIFY_URL") or "").strip()
    cookie = (os.environ.get("TOOLBOX_VERIFY_COOKIE") or "").strip()
    if not url:
        print(
            "Définissez TOOLBOX_VERIFY_URL (ex. https://....pythonanywhere.com/staff/utilities/rapports-comptables)",
            file=sys.stderr,
        )
        return 1
    if not cookie:
        print(
            "Définissez TOOLBOX_VERIFY_COOKIE avec l’en-tête Cookie complet de votre session staff.",
            file=sys.stderr,
        )
        return 1
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": cookie,
            "User-Agent": "toolbox-verify-accounting-reports/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            html = resp.read().decode("utf-8", "replace")
    except OSError as e:
        print(f"ERREUR réseau : {e}", file=sys.stderr)
        return 1
    required = REQUIRED_COMMON + REQUIRED_PL_STANDARD_BASE
    missing = _missing_markers(html, required)
    if missing:
        print("ERREUR déploiement : le HTML distant ne contient pas les marqueurs de base :", file=sys.stderr)
        for m in missing:
            print(f"  - {m!r}", file=sys.stderr)
        return 1
    print(f"OK distant {url} ({len(html)} caractères)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Vérifie le HTML des pages personnalisation rapports.")
    p.add_argument(
        "--remote",
        action="store_true",
        help="Vérifier TOOLBOX_VERIFY_URL avec TOOLBOX_VERIFY_COOKIE (session staff)",
    )
    args = p.parse_args()
    if args.remote:
        return verify_remote()
    return verify_local()


if __name__ == "__main__":
    raise SystemExit(main())
