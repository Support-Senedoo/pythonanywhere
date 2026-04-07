#!/usr/bin/env python3
"""
Bundle de debug P&L analytique / budget : **même paramètres** côté API (XML-RPC) et
côté capture navigateur (fichier produit par ``capture_odoo_report_view.py``).

Objectif : un seul fichier JSON (**sans mots de passe**) à joindre à une conversation pour
comparer le calcul ``project_pl_analytic_report.build_report`` avec ce qu’affiche Odoo,
sans enchaîner des tests à l’aveugle.

Prérequis
  - Fichier ``.env`` à côté des scripts (ou variables d’environnement) : ``ODOO_URL``,
    ``ODOO_DB``, ``ODOO_USER``, ``ODOO_PASSWORD``.
  - Optionnel : ``odoo_report_capture.json`` après capture du rapport (mêmes filtres
    analytique / période que dans l’UI).

Étapes recommandées
  1. Paramétrer le rapport dans Odoo (filtre analytique, budgets, période).
  2. Optionnel : ``python odoo_pl_debug_bundle.py ... --emit-capture-meta pl_capture_meta.json``
     puis capture avec ``--meta-json pl_capture_meta.json`` pour tracer les paramètres dans le JSON UI.
  3. Copier l’URL du rapport, lancer :
       python capture_odoo_report_view.py --base-url https://... --report-url "URL"
     (session Playwright déjà initialisée avec ``--init``).
  4. Lancer ce script avec les **mêmes** ``--analytic-id``, ``--date-from``, ``--date-to`` que l’UI :
       python odoo_pl_debug_bundle.py --analytic-id 42 --date-from 2026-01-01 --date-to 2026-04-06

Sortie : ``debug_pl_bundle.json`` (gitignored par défaut). Contient ``api_report``,
``ui_capture`` si présent, ``comparison`` (écarts détectés ligne / compte).

Sécurité : ne pas commiter ``debug_pl_bundle.json`` sur un dépôt public (montants réels).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from project_pl_analytic_report import (  # noqa: E402
    build_report,
    connect,
    rows_for_api_export,
)


_DEFAULT_CAPTURE = _SCRIPT_DIR / "odoo_report_capture.json"
_DEFAULT_OUT = _SCRIPT_DIR / "debug_pl_bundle.json"


def _parse_loose_number(text: str) -> float | None:
    """Essaie d'extraire un montant (espaces, CFA, parenthèses négatives, virgule décimale)."""
    if not text or not isinstance(text, str):
        return None
    s = text.strip()
    if not s or s.lower() in ("n/a", "—", "-", ""):
        return None
    neg = "(" in s and ")" in s
    s = re.sub(r"[^\d,.\-]", "", s.replace(" ", ""))
    s = s.replace(",", ".")
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _flatten_ui_rows(capture: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for t in capture.get("tables") or []:
        for r in t.get("rows") or []:
            if isinstance(r, list):
                rows.append([str(c) if c is not None else "" for c in r])
    return rows


def _row_matches_account_code(row: list[str], account_code: str) -> bool:
    code = (account_code or "").strip()
    if len(code) < 3:
        return False
    compact = code.replace(" ", "")
    joined = "".join(c.replace(" ", "") for c in row)
    if compact in joined:
        return True
    for c in row:
        cs = c.strip()
        if cs.startswith(code) or code in cs[:20]:
            return True
    return False


def _compare_api_vs_ui(
    api_lines: list[dict[str, Any]],
    ui_rows: list[list[str]],
    *,
    tolerance_ratio: float = 0.002,
) -> dict[str, Any]:
    """
    Pour chaque ligne API avec account_code, cherche une ligne UI qui contient ce code
    et compare le premier montant « plausible » de l’API au premier montant numérique UI
    (souvent colonne analytique) — heuristique, pas une preuve formelle.
    """
    notes: list[str] = []
    per_account: list[dict[str, Any]] = []

    for line in api_lines:
        code = (line.get("account_code") or "").strip()
        if not code:
            continue
        ar = float(line.get("realized") or 0.0)
        ab = float(line.get("budget") or 0.0)

        match_row: list[str] | None = None
        for r in ui_rows:
            if _row_matches_account_code(r, code):
                match_row = r
                break

        entry: dict[str, Any] = {
            "account_code": code,
            "api_realized": ar,
            "api_budget": ab,
            "api_percentage": line.get("percentage"),
            "ui_row_found": match_row is not None,
            "ui_cells": match_row,
        }

        if match_row:
            nums = []
            for c in match_row:
                v = _parse_loose_number(c)
                if v is not None:
                    nums.append(v)
            entry["ui_numeric_cells"] = nums
            if len(nums) >= 2:
                n0, n1 = nums[0], nums[1]
                entry["ui_first_numeric"] = n0
                entry["ui_second_numeric"] = n1
                d0 = abs(n0 - ar)
                d1 = abs(n1 - ar)
                entry["api_closer_to_column"] = "first" if d0 <= d1 else "second"
                if d1 < d0 - 1e-6:
                    notes.append(
                        f"{code}: le montant API ({ar:.2f}) est plus proche de la **2e** colonne numérique UI ({n1}) "
                        f"que de la 1re ({n0}) — typique si l’UI affiche [analytique, total] et que le % Odoo "
                        f"utilise encore le total."
                    )
                elif d0 <= max(abs(ar) * tolerance_ratio, 1.0):
                    entry["realized_match_ok"] = True
                else:
                    entry["realized_match_ok"] = False
            elif nums:
                v0 = nums[0]
                entry["ui_first_numeric"] = v0
                den = max(abs(ar), 1.0)
                rel = abs(v0 - ar) / den
                entry["realized_match_ok"] = rel <= tolerance_ratio

        per_account.append(entry)

    return {
        "accounts_compared": len(per_account),
        "notes": notes,
        "per_account": per_account,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Assemble API build_report + capture UI pour debug (un JSON à joindre au chat)."
    )
    p.add_argument("--analytic-id", type=int, required=True)
    p.add_argument("--date-from", required=True)
    p.add_argument("--date-to", required=True)
    p.add_argument("--capture-json", type=Path, default=_DEFAULT_CAPTURE, help="Sortie de capture_odoo_report_view.py")
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Fichier bundle JSON")
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    p.add_argument("--full-line-balance", action="store_true")
    p.add_argument("--currency", choices=("company", "transaction"), default="company")
    p.add_argument(
        "--emit-capture-meta",
        type=Path,
        default=None,
        help="Écrit un JSON (analytic_id, dates) pour --meta-json de capture_odoo_report_view.py.",
    )
    args = p.parse_args()

    if args.emit_capture_meta:
        meta = {
            "analytic_id": args.analytic_id,
            "date_from": args.date_from,
            "date_to": args.date_to,
            "full_line_balance": args.full_line_balance,
            "currency_mode": args.currency,
        }
        args.emit_capture_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Méta capture écrite : {args.emit_capture_meta.resolve()}")

    missing = [
        n
        for n, v in [
            ("ODOO_URL", args.url),
            ("ODOO_DB", args.db),
            ("ODOO_USER", args.user),
            ("ODOO_PASSWORD", args.password),
        ]
        if not v
    ]
    if missing:
        print("Variables manquantes :", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    models, uid, db, pwd = connect(args.url, args.db, args.user, args.password)

    api_report = build_report(
        models,
        db,
        uid,
        pwd,
        args.analytic_id,
        args.date_from,
        args.date_to,
        full_line_balance=args.full_line_balance,
        currency_mode=args.currency,
    )
    api_lines = rows_for_api_export(api_report.get("lines") or [])

    ui_raw: dict[str, Any] | None = None
    if args.capture_json.is_file():
        try:
            ui_raw = json.loads(args.capture_json.read_text(encoding="utf-8"))
        except Exception as e:
            ui_raw = {"error_reading_capture": str(e)}
    else:
        ui_raw = {
            "note": f"fichier absent : {args.capture_json} — lancez capture_odoo_report_view.py d'abord.",
        }

    ui_rows = _flatten_ui_rows(ui_raw) if isinstance(ui_raw, dict) and "error_reading_capture" not in ui_raw else []

    comparison: dict[str, Any] | None = None
    if ui_rows:
        comparison = _compare_api_vs_ui(api_lines, ui_rows)
    else:
        comparison = {
            "skipped": True,
            "reason": "Pas de lignes UI parsées (capture manquante ou vide).",
        }

    bundle: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "analytic_id": args.analytic_id,
            "date_from": args.date_from,
            "date_to": args.date_to,
            "full_line_balance": args.full_line_balance,
            "currency_mode": args.currency,
            "odoo_db": args.db,
            "odoo_host": args.url,
        },
        "api_report_summary": {
            "analytic_account_label": api_report.get("analytic_account_label"),
            "totals": api_report.get("totals"),
            "line_count": len(api_lines),
        },
        "api_lines": api_lines,
        "ui_capture": ui_raw,
        "comparison": comparison,
    }

    args.out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK — bundle écrit : {args.out.resolve()}")
    print("Joignez ce fichier à une conversation (vérifiez qu’il ne part pas sur un dépôt public).")


if __name__ == "__main__":
    main()
