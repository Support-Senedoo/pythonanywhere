#!/usr/bin/env python3
"""
Vérifie que la page « Rapports comptables » rend bien le HTML attendu (session staff simulée).

À lancer après toute modification de accounting_reports_utility.html ou de la vue associée :

  cd odoo-pythonanywhere
  python scripts/verify_accounting_reports_page.py

Sortie 0 = les marqueurs obligatoires sont présents dans le HTML généré localement.
Pour une URL déployée (optionnel, cookie de session staff requis) :

  set TOOLBOX_VERIFY_URL=https://votre-site.pythonanywhere.com/staff/utilities/rapports-comptables
  set TOOLBOX_VERIFY_COOKIE="session=...."
  python scripts/verify_accounting_reports_page.py --remote
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Toujours présents (même sans base sélectionnée)
REQUIRED_ALWAYS = [
    'id="ajouter-base-odoo"',
    'name="new_client_id"',
    'value="add_client"',
    "Ajouter une base Odoo au registre",
    "Enregistrer la base",
    "copie automatique",
    # Apostrophes typographiques du gabarit Jinja
    "le rapport d\u2019origine n\u2019est pas modifié",
]

# Uniquement si ?client_id=… pointe vers un client connu du registre
REQUIRED_WITH_CLIENT = [
    'id="report_id_p"',
    "Créer la copie et personnaliser",
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

    urls = (
        "/staff/utilities/rapports-comptables",
        "/staff/utilities/personalize-report",
    )
    for path in urls:
        r = client.get(path)
        if r.status_code != 200:
            print(f"ERREUR {path} : HTTP {r.status_code}", file=sys.stderr)
            return 1
        html = r.get_data(as_text=True)
        missing = _missing_markers(html, REQUIRED_ALWAYS)
        if missing:
            print(f"ERREUR {path} : marqueurs absents :", file=sys.stderr)
            for m in missing:
                print(f"  - {m!r}", file=sys.stderr)
            return 1
        print(f"OK {path} ({len(html)} caractères) — bloc « ajouter base »")

        if first_cid:
            r2 = client.get(f"{path}?client_id={first_cid}")
            if r2.status_code != 200:
                print(f"ERREUR {path}?client_id=… : HTTP {r2.status_code}", file=sys.stderr)
                return 1
            html2 = r2.get_data(as_text=True)
            missing2 = _missing_markers(html2, REQUIRED_ALWAYS + REQUIRED_WITH_CLIENT)
            if missing2:
                print(f"ERREUR {path}?client_id={first_cid} : marqueurs absents :", file=sys.stderr)
                for m in missing2:
                    print(f"  - {m!r}", file=sys.stderr)
                return 1
            print(f"OK {path}?client_id={first_cid} ({len(html2)} car.) — personnalisation")
        else:
            print(
                "Note : aucun client dans toolbox_clients.json — sous-partie « personnaliser » non vérifiée "
                "(normal en clone sans fichier clients)."
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
    missing = _missing_markers(html, REQUIRED_ALWAYS)
    if missing:
        print("ERREUR déploiement : le HTML distant ne contient pas les marqueurs de base :", file=sys.stderr)
        for m in missing:
            print(f"  - {m!r}", file=sys.stderr)
        print(
            "\nCause fréquente : pas de git pull / Reload sur PythonAnywhere, ou cache navigateur.",
            file=sys.stderr,
        )
        return 1
    print(f"OK distant {url} ({len(html)} caractères)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Vérifie le HTML de la page Rapports comptables.")
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
