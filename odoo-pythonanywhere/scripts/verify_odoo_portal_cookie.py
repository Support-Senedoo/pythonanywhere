#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test du cookie portail odoo.com **sans Flask** : télécharge « Mes bases » et affiche les URLs trouvées.

Prérequis : depuis le dossier ``odoo-pythonanywhere`` (ou PYTHONPATH vers la racine du projet).

Usage :

  cd odoo-pythonanywhere
  python3 scripts/verify_odoo_portal_cookie.py /chemin/vers/fichier_cookie.txt

  cat fichier_cookie.txt | python3 scripts/verify_odoo_portal_cookie.py -

  python3 scripts/verify_odoo_portal_cookie.py -
  # puis coller la ligne Cookie, terminer par Ctrl+D (Mac/Linux) ou Ctrl+Z Entrée (Windows)

Variables d’environnement optionnelles (comme la toolbox) :

  TOOLBOX_ODOO_PORTAL_ORIGIN   (défaut https://www.odoo.com)
  TOOLBOX_ODOO_PORTAL_LANG     (défaut /fr_FR)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from web_app.odoo_account_probe import fetch_odoo_com_portal_probes_from_browser_session  # noqa: E402


def _read_cookie_arg() -> str:
    if len(sys.argv) < 2:
        print(
            __doc__.strip(),
            file=sys.stderr,
        )
        raise SystemExit(2)
    arg = sys.argv[1].strip()
    if arg == "-":
        return sys.stdin.read().strip()
    return Path(arg).expanduser().read_text(encoding="utf-8").strip()


def main() -> None:
    raw = _read_cookie_arg()
    if not raw:
        print("Cookie vide.", file=sys.stderr)
        raise SystemExit(2)
    pairs, err = fetch_odoo_com_portal_probes_from_browser_session(raw)
    if err:
        print("Erreur :", err, file=sys.stderr)
        raise SystemExit(1)
    if not pairs:
        print("Aucune instance trouvée dans le HTML.", file=sys.stderr)
        raise SystemExit(1)
    print(f"{len(pairs)} instance(s) détectée(s) :\n")
    for url, db in pairs:
        print(f"  - {db!r}  →  {url}")


if __name__ == "__main__":
    main()
