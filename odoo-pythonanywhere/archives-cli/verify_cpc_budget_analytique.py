#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Contrôle du rapport « CPC SYSCOHADA — Budget par projet (Senedoo) » sur une base Odoo.

Vérifie :
  - présence du account.report (nom exact ou --report-id) ;
  - filtres utiles (filter_analytic, filter_budgets / filter_budget si le modèle les a) ;
  - 4 colonnes (expression_label balance / budget / ecart / pct) ;
  - nombre de lignes et codes attendus (structure CPC toolbox) ;
  - pour chaque ligne : 4 expressions avec les bons moteurs (account_codes / budget / aggregation).

Variables d'environnement (ou options CLI) : comme personalize_syscohada_detail / .env

Usage :
  python verify_cpc_budget_analytique.py
  python verify_cpc_budget_analytique.py --report-id 42
  python verify_cpc_budget_analytique.py --url https://... --db ma_base -u admin@... -p <clé>
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

from create_cpc_budget_analytique import (
    CPC_BUDGET_ANALYTIQUE_NAME,
    CPC_BUDGET_STRUCTURE,
    _agg_formula_with_suffix,
    cpc_account_report_budget_item_available,
    cpc_budget_pct_aggregation_formula,
    cpc_budget_pct_subformula,
    cpc_crossovered_budget_available,
    company_currency_code,
    expression_engine_keys,
    normalize_cpc_account_codes_formula,
)
from personalize_syscohada_detail import connect, execute_kw

EXPECTED_COLUMN_LABELS = ("balance", "budget", "ecart", "pct")
STRUCT_BY_CODE: dict[str, tuple[str, str, str, str | None, str | None]] = {
    row[0]: row for row in CPC_BUDGET_STRUCTURE
}


def _ek(
    models: Any,
    db: str,
    uid: int,
    password: str,
    model: str,
    method: str,
    args: list | None = None,
    kw: dict | None = None,
) -> Any:
    return execute_kw(models, db, uid, password, model, method, args or [], kw or {})


def _report_fields_available(models: Any, db: str, uid: int, password: str) -> set[str]:
    fg = _ek(models, db, uid, password, "account.report", "fields_get", [], {})
    return set(fg.keys()) if isinstance(fg, dict) else set()


def verify_cpc_budget_analytique_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    report_id: int | None = None,
    report_name: str | None = None,
) -> dict[str, Any]:
    """
    Retourne un dict :
      ok, errors (bloquant), warnings, report_id, report_snapshot,
      columns, lines_summary, line_checks, exit_hint
    """
    errors: list[str] = []
    warnings: list[str] = []
    name = (report_name or CPC_BUDGET_ANALYTIQUE_NAME).strip()

    rid = report_id
    if not rid:
        ids = _ek(
            models,
            db,
            uid,
            password,
            "account.report",
            "search",
            [[["name", "=", name]]],
        )
        if not ids:
            ids = _ek(
                models,
                db,
                uid,
                password,
                "account.report",
                "search",
                [[["name", "ilike", "Budget Analytique"]]],
                {"limit": 5},
            )
        if not ids:
            errors.append(
                f"Aucun rapport trouvé pour le nom exact « {name} ». "
                "Créez-le via l’outillage d’intégration (ex. « Créer / recréer le CPC Budget par projet ») "
                "ou passez --report-id."
            )
            return {
                "ok": False,
                "errors": errors,
                "warnings": warnings,
                "report_id": None,
                "report_snapshot": {},
                "columns": [],
                "lines_summary": {},
                "line_checks": [],
                "exit_hint": "Créer le rapport puis relancer ce script.",
            }
        if len(ids) > 1:
            warnings.append(
                f"Plusieurs rapports correspondent ({ids}) ; utilisation du premier : {ids[0]}."
            )
        rid = int(ids[0])

    avail = _report_fields_available(models, db, uid, password)
    read_fields = ["name", "filter_analytic", "filter_date_range", "filter_journals"]
    for f in ("filter_budgets", "filter_budget"):
        if f in avail:
            read_fields.append(f)

    rep_rows = _ek(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[rid]],
        {"fields": read_fields},
    )
    if not rep_rows:
        errors.append(f"account.report id={rid} introuvable (lecture).")
        return {
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "report_id": rid,
            "report_snapshot": {},
            "columns": [],
            "lines_summary": {},
            "line_checks": [],
            "exit_hint": "Vérifier l'id du rapport.",
        }
    snap = rep_rows[0]

    if snap.get("name") and snap["name"] != name:
        warnings.append(
            f"Nom effectif du rapport : « {snap['name']} » (recherche initiale : « {name} »)."
        )

    if not snap.get("filter_analytic"):
        errors.append("filter_analytic devrait être True pour ce rapport analytique.")

    if "filter_budgets" in avail and not snap.get("filter_budgets"):
        warnings.append(
            "filter_budgets est disponible sur ce Odoo mais vaut False — "
            "les colonnes budget peuvent mal se comporter avec le filtre analytique. "
            "Lancer : python personalize_pl_analytic_budget.py --report-id "
            f"{rid}"
        )
    if "filter_budget" in avail and "filter_budgets" not in avail and not snap.get("filter_budget"):
        warnings.append(
            "filter_budget est disponible mais vaut False — "
            f"python personalize_pl_analytic_budget.py --report-id {rid}"
        )
    if "filter_budgets" not in avail and "filter_budget" not in avail:
        warnings.append(
            "Ni filter_budgets ni filter_budget sur account.report — "
            "édition Odoo sans filtre budgets ; comportement budget + analytique à valider manuellement."
        )

    cols = _ek(
        models,
        db,
        uid,
        password,
        "account.report.column",
        "search_read",
        [[["report_id", "=", rid]]],
        {"fields": ["sequence", "name", "expression_label"], "order": "sequence asc"},
    ) or []
    labels = [c.get("expression_label") for c in cols]
    if labels != list(EXPECTED_COLUMN_LABELS):
        errors.append(
            f"Colonnes attendues {list(EXPECTED_COLUMN_LABELS)}, obtenues {labels} "
            f"({len(cols)} colonne(s))."
        )

    lines = _ek(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search_read",
        [[["report_id", "=", rid], ["code", "!=", False]]],
        {"fields": ["id", "code", "name"]},
    ) or []
    codes_db = {str(l["code"]) for l in lines}
    expected_codes = {row[0] for row in CPC_BUDGET_STRUCTURE}
    missing = sorted(expected_codes - codes_db)
    extra = sorted(codes_db - expected_codes)
    if missing:
        errors.append(f"Lignes CPC manquantes ({len(missing)}) : {', '.join(missing[:20])}"
                      + (" …" if len(missing) > 20 else ""))
    if extra:
        errors.append(f"Lignes en trop ou codes inattendus : {', '.join(extra[:15])}"
                      + (" …" if len(extra) > 15 else ""))
    if len(lines) != len(CPC_BUDGET_STRUCTURE):
        errors.append(
            f"Nombre de lignes : attendu {len(CPC_BUDGET_STRUCTURE)}, obtenu {len(lines)}."
        )

    line_ids = [int(l["id"]) for l in lines]
    exprs: list[dict] = []
    if line_ids:
        exprs = (
            _ek(
                models,
                db,
                uid,
                password,
                "account.report.expression",
                "search_read",
                [[["report_line_id", "in", line_ids]]],
                {"fields": ["report_line_id", "label", "engine", "formula", "subformula", "figure_type"]},
            )
            or []
        )

    by_line: dict[int, dict[str, dict]] = {}
    for e in exprs:
        rid_e = e["report_line_id"]
        lid = rid_e[0] if isinstance(rid_e, (list, tuple)) else int(rid_e)
        by_line.setdefault(lid, {})[e.get("label") or ""] = e

    line_checks: list[dict[str, Any]] = []
    fallback_budget_account_codes = False
    eng_keys = expression_engine_keys(models, db, uid, password)
    budget_native = "budget" in eng_keys
    report_budget_item_ok = cpc_account_report_budget_item_available(models, db, uid, password)
    crossovered_ok = cpc_crossovered_budget_available(models, db, uid, password)
    if budget_native:
        expected_budget_mode = "native"
    elif report_budget_item_ok:
        expected_budget_mode = "external"
    elif crossovered_ok:
        expected_budget_mode = "external"
    else:
        expected_budget_mode = "fallback_gl"
    budget_pct_meaningful = expected_budget_mode != "fallback_gl"
    currency_code = company_currency_code(models, db, uid, password)
    for ln in sorted(lines, key=lambda x: str(x.get("code") or "")):
        code = str(ln.get("code") or "")
        lid = int(ln["id"])
        ex = by_line.get(lid, {})
        row_spec = STRUCT_BY_CODE.get(code)
        lc_errors: list[str] = []

        for lab in EXPECTED_COLUMN_LABELS:
            if lab not in ex:
                lc_errors.append(f"expression « {lab} » manquante")

        if not lc_errors:
            if code.startswith("X"):
                for lab in EXPECTED_COLUMN_LABELS:
                    eng = (ex[lab].get("engine") or "").strip()
                    if eng != "aggregation":
                        lc_errors.append(f"{lab}: engine={eng!r}, attendu aggregation")
                if row_spec and row_spec[2] == "aggregate" and row_spec[4]:
                    fa = row_spec[4]
                    _norm = lambda s: (s or "").replace(" ", "")
                    bal_e = _norm(_agg_formula_with_suffix(fa, "balance"))
                    if _norm(ex["balance"].get("formula")) != bal_e:
                        lc_errors.append(
                            f"balance: formule « {_norm(ex['balance'].get('formula'))} » "
                            f"≠ attendue « {bal_e} »"
                        )
                    bud_e = _norm(_agg_formula_with_suffix(fa, "budget"))
                    if _norm(ex["budget"].get("formula")) != bud_e:
                        lc_errors.append(
                            f"budget: formule « {_norm(ex['budget'].get('formula'))} » "
                            f"≠ attendue « {bud_e} »"
                        )
                    ec_e = _norm(f"{code}.budget-{code}.balance")
                    ec_g = _norm(ex["ecart"].get("formula"))
                    if ec_g != ec_e:
                        lc_errors.append(f"ecart: formule « {ec_g} » ≠ attendue « {ec_e} »")
                    pct_e = _norm(
                        cpc_budget_pct_aggregation_formula(
                            code,
                            budget_pct_meaningful=budget_pct_meaningful,
                            currency_code=currency_code,
                        )
                    )
                    pct_g = _norm(ex["pct"].get("formula"))
                    if pct_g != pct_e:
                        lc_errors.append(f"pct: formule « {pct_g} » ≠ attendue « {pct_e} »")
                    sub_g = _norm(str(ex["pct"].get("subformula") or ""))
                    sub_e = (
                        _norm(cpc_budget_pct_subformula(code, currency_code))
                        if budget_pct_meaningful
                        else ""
                    )
                    if sub_g != sub_e:
                        lc_errors.append(
                            f"pct: subformula « {ex['pct'].get('subformula')!r} » ≠ attendue "
                            f"« {sub_e or '(vide)'} » (réparation CPC toolbox si ancien schéma)."
                        )
            else:
                b_eng = (ex["balance"].get("engine") or "").strip()
                if b_eng != "account_codes":
                    lc_errors.append(f"balance: engine={b_eng!r}, attendu account_codes")
                bud_eng = (ex["budget"].get("engine") or "").strip()
                if bud_eng not in ("budget", "account_codes", "external"):
                    lc_errors.append(
                        f"budget: engine={bud_eng!r}, attendu budget, external ou account_codes"
                    )
                if bud_eng == "account_codes" and not code.startswith("X"):
                    fallback_budget_account_codes = True
                if expected_budget_mode == "native" and bud_eng != "budget":
                    lc_errors.append(
                        f"budget: engine={bud_eng!r}, attendu budget (moteur natif sur cette base)"
                    )
                if expected_budget_mode == "external" and bud_eng != "external":
                    lc_errors.append(
                        f"budget: engine={bud_eng!r}, attendu external (recréer le rapport via l’intégration)"
                    )
                if expected_budget_mode == "fallback_gl" and bud_eng != "account_codes":
                    lc_errors.append(
                        f"budget: engine={bud_eng!r}, attendu account_codes (repli GL)"
                    )
                for lab in ("ecart", "pct"):
                    eng = (ex[lab].get("engine") or "").strip()
                    if eng != "aggregation":
                        lc_errors.append(f"{lab}: engine={eng!r}, attendu aggregation")

                pct_got = (ex["pct"].get("formula") or "").replace(" ", "")
                pct_exp = cpc_budget_pct_aggregation_formula(
                    code,
                    budget_pct_meaningful=budget_pct_meaningful,
                    currency_code=currency_code,
                ).replace(" ", "")
                if pct_got != pct_exp:
                    lc_errors.append(f"pct: formule « {pct_got} » ≠ attendue « {pct_exp} »")
                sub_g = (str(ex["pct"].get("subformula") or "")).replace(" ", "")
                sub_e = (
                    cpc_budget_pct_subformula(code, currency_code).replace(" ", "")
                    if budget_pct_meaningful
                    else ""
                )
                if sub_g != sub_e:
                    lc_errors.append(
                        f"pct: subformula « {ex['pct'].get('subformula')!r} » ≠ attendue "
                        f"« {sub_e or '(vide)'} » (réparation CPC toolbox si ancien schéma)."
                    )

                if row_spec and row_spec[2] == "account" and row_spec[3]:
                    f_bal = normalize_cpc_account_codes_formula(ex["balance"].get("formula"))
                    f_exp = normalize_cpc_account_codes_formula(row_spec[3])
                    if f_bal != f_exp:
                        lc_errors.append(
                            f"formule balance « {f_bal} » ≠ attendue (normalisée) « {f_exp} »"
                        )
                    f_bud = normalize_cpc_account_codes_formula(ex["budget"].get("formula"))
                    if bud_eng == "budget" and f_bud != f_exp:
                        lc_errors.append(
                            f"formule budget « {f_bud} » ≠ attendue (normalisée) « {f_exp} »"
                        )
                    if bud_eng == "external":
                        f_raw = (ex["budget"].get("formula") or "").strip()
                        if f_raw != "sum":
                            lc_errors.append(f"budget external: formule « {f_raw!r} » ≠ attendue « sum »")
                        sub = (ex["budget"].get("subformula") or "").strip().lower()
                        if "editable" in sub:
                            lc_errors.append(
                                "budget external: la sous-formule « editable » (crayon) est "
                                f"interdite ; actuel : {ex['budget'].get('subformula')!r}"
                            )
                    if bud_eng == "account_codes" and f_bud != f_bal:
                        lc_errors.append(
                            f"formule budget « {f_bud} » ≠ balance « {f_bal} » (fallback attendu)"
                        )

        line_checks.append(
            {
                "code": code,
                "id": lid,
                "errors": lc_errors,
                "engines": {k: ex[k].get("engine") for k in EXPECTED_COLUMN_LABELS if k in ex},
            }
        )
        for msg in lc_errors:
            errors.append(f"Ligne {code}: {msg}")

    if fallback_budget_account_codes:
        warnings.append(
            "Colonne Budget en repli account_codes (comme le Réalisé) : écart 0 et % inutiles sur "
            "les lignes détail — pas de moteur budget natif ni account.report.budget.item ni crossovered."
        )
    if expected_budget_mode == "external":
        if report_budget_item_ok:
            warnings.append(
                "Budget des lignes détail = moteur external : exécuter l’assistant toolbox "
                "« Budget par projet » (même analytique, période et ``account.report.budget``) pour "
                "remplir les ``account.report.external.value`` ; sinon colonne Budget vide."
            )
        else:
            warnings.append(
                "Budget des lignes détail = moteur external : prévoir une alimentation côté Odoo "
                "(crossovered + analytique) ou phase de test intégrateur ; sinon colonne Budget vide."
            )

    ok = len(errors) == 0
    return {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "report_id": rid,
        "report_snapshot": snap,
        "columns": cols,
        "lines_summary": {
            "count": len(lines),
            "expected_count": len(CPC_BUDGET_STRUCTURE),
            "codes_ok": not missing and not extra,
        },
        "line_checks": line_checks,
        "exit_hint": (
            "Contrôle OK."
            if ok
            else "Corriger les erreurs ci-dessus ou recréer le rapport (outillage d’intégration)."
        ),
    }


def _print_report(result: dict[str, Any], base_url: str, *, verbose: bool = False) -> None:
    print("=" * 72)
    print("  Contrôle — CPC SYSCOHADA — Budget par projet (Senedoo)")
    print("=" * 72)

    rid = result.get("report_id")
    if rid:
        print(f"\n  Rapport id : {rid}")
        snap = result.get("report_snapshot") or {}
        for k in sorted(snap.keys()):
            if k == "name":
                print(f"  {k:22} : {snap[k]}")
            else:
                print(f"  {k:22} : {snap[k]!r}")

        bu = (base_url or "").rstrip("/")
        if bu:
            print(f"\n  Fiche technique : {bu}/web#id={rid}&model=account.report&view_type=form")

    cols = result.get("columns") or []
    print(f"\n  Colonnes ({len(cols)}) :")
    for c in cols:
        seq = c.get("sequence", "")
        print(
            f"    [{seq:>3}] {c.get('expression_label', '?'):12} — {c.get('name', '')}"
        )

    ls = result.get("lines_summary") or {}
    print(
        f"\n  Lignes CPC : {ls.get('count', '?')} / attendu {ls.get('expected_count', '?')} "
        f"({'codes OK' if ls.get('codes_ok') else 'écart'})"
    )

    checks = result.get("line_checks") or []
    bad = [c for c in checks if c.get("errors")]
    good = [c for c in checks if not c.get("errors")]
    for chk in bad:
        print(f"\n  ❌ {chk['code']} (id={chk['id']})")
        for e in chk["errors"]:
            print(f"      - {e}")
    if good:
        if verbose:
            for chk in good:
                eng = chk.get("engines") or {}
                print(f"  ✓ {chk['code']:4}  engines: {eng}")
        else:
            print(f"\n  ✓ {len(good)} ligne(s) sans erreur (détail : --verbose).")

    warns = result.get("warnings") or []
    if warns:
        print("\n  Avertissements :")
        for w in warns:
            print(f"    ⚠ {w}")

    errs = result.get("errors") or []
    if errs:
        print("\n  Erreurs :")
        for e in errs:
            print(f"    ✗ {e}")
    else:
        if result.get("ok"):
            print("\n  Aucune erreur bloquante.")

    print(f"\n  → {result.get('exit_hint', '')}\n")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Vérifie que le rapport CPC Budget par projet (toolbox) est bien créé."
    )
    p.add_argument("--report-id", type=int, default=None, help="ID account.report (sinon recherche par nom)")
    p.add_argument(
        "--name",
        default=CPC_BUDGET_ANALYTIQUE_NAME,
        help="Nom exact du rapport si recherche par nom",
    )
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    p.add_argument("-q", "--quiet", action="store_true", help="Sortie minimale (code retour seulement)")
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Afficher chaque ligne CPC OK (engines) ; sinon seulement le résumé",
    )
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
        print("Renseigner .env ou options --url --db -u -p.", file=sys.stderr)
        return 2

    try:
        models, uid = connect(args.url, args.db, args.user, args.password)
    except Exception as e:
        print(f"Connexion : {e}", file=sys.stderr)
        return 2

    result = verify_cpc_budget_analytique_report(
        models,
        args.db,
        uid,
        args.password,
        report_id=args.report_id,
        report_name=args.name.strip() if args.name else None,
    )

    if not args.quiet:
        _print_report(result, args.url, verbose=args.verbose)

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
