#!/usr/bin/env python3
"""
Lance capture + bundle en lisant ``debug_odoo_defaults.json`` (pas de questions).

1. Copiez ``debug_odoo_defaults.example.json`` → ``debug_odoo_defaults.json``
2. Collez ``report_url`` (une fois) depuis Odoo
3. ``python run_debug_capture.py``  ou  double-clic ``CAPTURE_DEBUG_RIPAILLE.cmd``

Si la capture Playwright échoue (session absente : ``odoo_browser_state.json``), le script
génère quand même ``debug_pl_bundle.json`` (partie API + message sur l’UI manquante).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_DEFAULTS = _SCRIPT_DIR / "debug_odoo_defaults.json"
_EXAMPLE = _SCRIPT_DIR / "debug_odoo_defaults.example.json"


def main() -> None:
    cfg_path = _DEFAULTS
    if not cfg_path.is_file():
        print(
            f"Fichier absent : {cfg_path}\n"
            f"Copiez {_EXAMPLE.name} en {cfg_path.name} et renseignez au moins report_url.",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = (cfg.get("base_url") or "").strip()
    report = (cfg.get("report_url") or "").strip()
    aname = (cfg.get("analytic_name") or "").strip()
    if not base or not report or not aname:
        print(
            "debug_odoo_defaults.json : renseignez base_url, report_url (URL complete du rapport) et analytic_name.",
            file=sys.stderr,
        )
        sys.exit(1)

    dates_ytd = bool(cfg.get("dates_ytd", True))
    d1 = (cfg.get("date_from") or "").strip()
    d2 = (cfg.get("date_to") or "").strip()
    if not dates_ytd and (not d1 or not d2):
        print(
            "Si dates_ytd est false, renseignez date_from et date_to (YYYY-MM-DD).",
            file=sys.stderr,
        )
        sys.exit(1)

    from project_pl_analytic_report import default_period_ytd

    if dates_ytd:
        d1, d2 = default_period_ytd()

    py = sys.executable
    capture = _SCRIPT_DIR / "capture_odoo_report_view.py"
    bundle = _SCRIPT_DIR / "odoo_pl_debug_bundle.py"

    state = _SCRIPT_DIR / "odoo_browser_state.json"
    print("Capture navigateur…")
    r1 = subprocess.run(
        [py, str(capture), "--base-url", base, "--report-url", report],
        cwd=str(_SCRIPT_DIR),
    )
    if r1.returncode != 0:
        print(
            f"\n--- Capture navigateur en échec (code {r1.returncode}) — le bundle API est quand même généré. ---\n"
            "Causes fréquentes : pas de session Playwright. Une fois :\n"
            f'  python capture_odoo_report_view.py --init --base-url "{base}"\n'
            f"ou le script CONNEXION_ODOO_UNE_FOIS — fichier attendu : {state}\n",
            file=sys.stderr,
        )

    print("Calcul API + bundle…")
    r2 = subprocess.run(
        [
            py,
            str(bundle),
            "--analytic-name",
            aname,
            "--date-from",
            d1,
            "--date-to",
            d2,
        ],
        cwd=str(_SCRIPT_DIR),
    )
    if r2.returncode != 0:
        sys.exit(r2.returncode)

    out = _SCRIPT_DIR / "debug_pl_bundle.json"
    print(f"OK — {out}")
    if sys.platform == "win32":
        subprocess.run(["explorer", "/select,", str(out)], check=False)


if __name__ == "__main__":
    main()
