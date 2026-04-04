#!/usr/bin/env python3
"""
Active sur un account.report (typiquement une copie de P&L) les options utiles pour
piloter budget + analytique dans l’UI Odoo : filter_analytic, et filter_budget si présent.

Les champs réellement écrits dépendent de fields_get (Odoo SaaS / Enterprise).

Usage CLI :
  python personalize_pl_analytic_budget.py --report-id 42

Variables : ODOO_* ou .env (voir personalize_syscohada_detail.py)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from personalize_syscohada_detail import connect, execute_kw


def _writable_boolean_filter_fields(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> list[str]:
    fg = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "fields_get",
        [],
        {"attributes": ["type", "readonly"]},
    )
    out: list[str] = []
    for name, meta in fg.items():
        if not name.startswith("filter_"):
            continue
        if meta.get("type") != "boolean":
            continue
        if meta.get("readonly"):
            continue
        out.append(name)
    return sorted(out)


def personalize_pl_analytic_budget_options(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    *,
    enable_budget_filter: bool = True,
) -> dict[str, Any]:
    """
    Écrit filter_analytic=True ; filter_budget=True si le champ existe et est modifiable.
    Retourne {written, writable_boolean_filters} pour message utilisateur / logs.
    """
    filters = _writable_boolean_filter_fields(models, db, uid, password)
    vals: dict[str, Any] = {}
    if "filter_analytic" in filters:
        vals["filter_analytic"] = True
    if enable_budget_filter and "filter_budget" in filters:
        vals["filter_budget"] = True
    if "filter_analytic" not in vals:
        raise ValueError(
            "Le champ modifiable « filter_analytic » est absent sur account.report "
            "(édition comptable / version Odoo ?)."
        )
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], vals],
    )
    return {"written": vals, "writable_boolean_filters": filters}


def probe_financial_budget_analytic_summary(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> str:
    """
    Résumé XML-RPC : lignes de budget avec analytique renseigné (modèles courants Odoo).
    Lecture seule ; ne remplace pas un contrôle métier dans l’interface Odoo.
    """
    parts: list[str] = []
    for model in ("account.budget.line", "crossovered.budget.lines"):
        try:
            mod_ok = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.model",
                "search_count",
                [[("model", "=", model)]],
            )
        except Exception:
            mod_ok = 0
        if not mod_ok:
            continue
        try:
            fg = execute_kw(
                models,
                db,
                uid,
                password,
                model,
                "fields_get",
                [],
                {"attributes": ["type"]},
            )
        except Exception as e:
            parts.append(f"{model}: fields_get impossible ({e!s}).")
            continue
        analytic_domain: list | None = None
        label = ""
        if "analytic_distribution" in fg:
            analytic_domain = [("analytic_distribution", "!=", False)]
            label = "analytic_distribution"
        elif "analytic_account_id" in fg:
            analytic_domain = [("analytic_account_id", "!=", False)]
            label = "analytic_account_id"
        elif "account_analytic_id" in fg:
            analytic_domain = [("account_analytic_id", "!=", False)]
            label = "account_analytic_id"
        if analytic_domain is None:
            parts.append(
                f"{model}: modèle présent ; aucun champ analytique reconnu "
                f"(aperçu champs : {', '.join(sorted(fg)[:12])}…)."
            )
            continue
        try:
            total = int(
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    model,
                    "search_count",
                    [[]],
                )
            )
            with_a = int(
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    model,
                    "search_count",
                    [analytic_domain],
                )
            )
            parts.append(
                f"{model} ({label}) : {with_a}/{total} ligne(s) avec analytique renseigné."
            )
        except Exception as e:
            parts.append(f"{model}: comptage impossible ({e!s}).")

    if not parts:
        return (
            "Aucun modèle « account.budget.line » ni « crossovered.budget.lines » détecté "
            "dans ir.model — budget financier / version différente, ou droits insuffisants."
        )
    return " ".join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description="Active filter_analytic (+ filter_budget si dispo) sur account.report")
    p.add_argument("--report-id", type=int, required=True, help="ID account.report (copie recommandée)")
    p.add_argument("--no-budget-filter", action="store_true", help="Ne pas activer filter_budget")
    p.add_argument("--probe-only", action="store_true", help="Seulement sonder les lignes budget / analytique")
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    args = p.parse_args()

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
        print("Manquant :", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    models, uid = connect(args.url, args.db, args.user, args.password)
    pw = args.password

    if args.probe_only:
        print(probe_financial_budget_analytic_summary(models, args.db, uid, pw))
        return

    try:
        res = personalize_pl_analytic_budget_options(
            models,
            args.db,
            uid,
            pw,
            args.report_id,
            enable_budget_filter=not args.no_budget_filter,
        )
    except Exception as e:
        print(f"Échec : {e}", file=sys.stderr)
        sys.exit(2)
    print("Écrit :", res["written"])
    print("Filtres booléens modifiables sur account.report :", ", ".join(res["writable_boolean_filters"]))


if __name__ == "__main__":
    main()
