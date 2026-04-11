#!/usr/bin/env python3
"""
Lance capture + bundle en lisant ``debug_odoo_defaults.json`` (pas de questions).

1. Copiez ``debug_odoo_defaults.example.json`` → ``debug_odoo_defaults.json``
2. Collez ``report_url`` (une fois) depuis Odoo
3. ``python run_debug_capture.py``  ou  double-clic ``CAPTURE_DEBUG_RIPAILLE.cmd``

**Prévol** : refuse de lancer la capture si ``.env`` ne définit pas ODOO_URL / ODOO_DB / ODOO_USER /
ODOO_PASSWORD (inutile de lancer Playwright sans pouvoir générer le bundle).

Si la capture Playwright échoue (session absente : ``odoo_browser_state.json``), le script
génère quand même ``debug_pl_bundle.json`` (partie API + message sur l’UI manquante).

**Vérification agent / CI** : ``python run_debug_capture.py --preflight-only`` (sans Odoo ni Playwright).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

_DEFAULTS = _SCRIPT_DIR / "debug_odoo_defaults.json"
_EXAMPLE = _SCRIPT_DIR / "debug_odoo_defaults.example.json"
_BUNDLE_OUT = _SCRIPT_DIR / "debug_pl_bundle.json"
_STATE = _SCRIPT_DIR / "odoo_browser_state.json"
_ENV_FILE = _SCRIPT_DIR / ".env"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE)
    except ImportError:
        pass


def _missing_odoo_env() -> list[str]:
    _load_dotenv()
    return [k for k in ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_PASSWORD") if not (os.environ.get(k) or "").strip()]


def _assert_bundle_file_nonempty(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 4:
        print(
            f"ERREUR : {path.name} absent ou vide après odoo_pl_debug_bundle.py. "
            "Cela ne devrait pas arriver — signalez-le.",
            file=sys.stderr,
        )
        sys.exit(3)


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture UI + bundle debug P&L (Ripaille).")
    ap.add_argument(
        "--preflight-only",
        action="store_true",
        help="Vérifie debug_odoo_defaults.json + .env + chemins ; sans Playwright ni XML-RPC.",
    )
    ns = ap.parse_args()

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

    missing_env = _missing_odoo_env()
    env_ok = not missing_env

    if ns.preflight_only:
        print("Prévol run_debug_capture (sans réseau)")
        print(f"  {cfg_path.name} : OK")
        print(f"  {_ENV_FILE.name} + ODOO_* : {'OK' if env_ok else 'MANQUANT — ' + ', '.join(missing_env)}")
        print(f"  {_STATE.name} (session Playwright) : {'présent' if _STATE.is_file() else 'absent — capture UI échouera'}")
        print(f"  période utilisée : {d1} → {d2}")
        sys.exit(0 if env_ok else 2)

    if not env_ok:
        print(
            "Impossible de générer le bundle : variables manquantes : "
            + ", ".join(missing_env)
            + f"\nRenseignez-les dans {_ENV_FILE.resolve()} (ou l'environnement). "
            "Sans cela, inutile de lancer la capture navigateur.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _STATE.is_file():
        print(
            f"Avertissement : {_STATE.name} absent — la capture Playwright va échouer ; "
            "le bundle API sera tout de même tenté après.\n"
            f'  Une fois : python capture_odoo_report_view.py --init --base-url "{base}"\n',
            file=sys.stderr,
        )

    py = sys.executable
    capture = _SCRIPT_DIR / "capture_odoo_report_view.py"
    bundle = _SCRIPT_DIR / "odoo_pl_debug_bundle.py"

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
            f"ou le script CONNEXION_ODOO_UNE_FOIS — fichier attendu : {_STATE}\n",
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

    _assert_bundle_file_nonempty(_BUNDLE_OUT)

    if r2.returncode != 0:
        try:
            data = json.loads(_BUNDLE_OUT.read_text(encoding="utf-8"))
            if data.get("bundle_fatal_error"):
                print(
                    f"\n{_BUNDLE_OUT.name} contient une erreur Odoo/API (clé bundle_fatal_error). "
                    "Ouvrez le fichier pour le détail.\n",
                    file=sys.stderr,
                )
        except Exception:
            pass
        sys.exit(r2.returncode)

    print(f"OK — {_BUNDLE_OUT}")
    if sys.platform == "win32":
        subprocess.run(["explorer", "/select,", str(_BUNDLE_OUT)], check=False)


if __name__ == "__main__":
    main()
