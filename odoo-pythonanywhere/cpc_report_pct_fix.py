"""
Correction des expressions « pct » des rapports CPC SYSCOHADA sur Odoo SaaS.

Les rapports créés hors toolbox (ou versions anciennes) peuvent avoir une formule
``{code}.balance/{code}.budget*100`` sans ``subformula`` : dès que le budget vaut 0,
Odoo lève « division par zéro ». La sous-formule standard
``if_other_expr_above(code.budget, DEVISE(epsilon))`` évite l'évaluation de la
division lorsque le dénominateur n'est pas strictement positif.
"""
from __future__ import annotations

from typing import Any

from personalize_syscohada_detail import execute_kw


def company_currency_code(models: Any, db: str, uid: int, password: str) -> str:
    """Code ISO 4217 (3 lettres) de la société de l'utilisateur API."""
    try:
        users = execute_kw(
            models, db, uid, password, "res.users", "read", [[uid]], {"fields": ["company_id"]}
        )
        if not users or not users[0].get("company_id"):
            return "XOF"
        cid = users[0]["company_id"][0]
        comps = execute_kw(
            models,
            db,
            uid,
            password,
            "res.company",
            "read",
            [[cid]],
            {"fields": ["currency_id"]},
        )
        if not comps or not comps[0].get("currency_id"):
            return "XOF"
        cur_id = comps[0]["currency_id"][0]
        cur = execute_kw(
            models,
            db,
            uid,
            password,
            "res.currency",
            "read",
            [[cur_id]],
            {"fields": ["name"]},
        )
        if not cur:
            return "XOF"
        name = (cur[0].get("name") or "").strip().upper()
        if len(name) == 3 and name.isalpha():
            return name
    except Exception:
        pass
    return "XOF"


def cpc_budget_pct_subformula(line_code: str, currency_code: str) -> str:
    """Sous-formule aggregation : ne calcule le % que si le budget est > 0."""
    c = (line_code or "").strip()
    cur = (currency_code or "XOF").strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        cur = "XOF"
    # Epsilon > 0 : certains moteurs traitent « above 0 » de façon stricte.
    return f"if_other_expr_above({c}.budget, {cur}(0.0001))"


def fix_pct_expressions_on_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> int:
    """
    Met à jour les expressions ``label=pct`` en ``aggregation`` dont la formule
    divise par ``.budget`` : ajoute ou corrige ``subformula`` (anti division par zéro).

    Retourne le nombre d'expressions modifiées.
    """
    currency_code = company_currency_code(models, db, uid, password)
    expr_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.expression",
        "search",
        [[("report_line_id.report_id", "=", int(report_id)), ("label", "=", "pct")]],
    )
    if not expr_ids:
        return 0
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.expression",
        "read",
        [expr_ids],
        {"fields": ["engine", "formula", "subformula", "report_line_id"]},
    )
    nwrites = 0
    for row in rows or []:
        engine = (row.get("engine") or "").strip()
        formula = (row.get("formula") or "").replace(" ", "")
        if engine != "aggregation":
            continue
        if not formula or formula == "0":
            continue
        if ".budget" not in formula or ".balance" not in formula:
            continue
        if "/" not in formula:
            continue
        rl = row.get("report_line_id")
        if not rl or not isinstance(rl, (list, tuple)):
            continue
        line_id = int(rl[0])
        lines = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [[line_id]],
            {"fields": ["code"]},
        )
        if not lines:
            continue
        code = (lines[0].get("code") or "").strip()
        if not code:
            continue
        sub_expected = cpc_budget_pct_subformula(code, currency_code)
        current_sub = (row.get("subformula") or "").strip()
        if current_sub.replace(" ", "") == sub_expected.replace(" ", ""):
            continue
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "write",
            [[int(row["id"])], {"subformula": sub_expected}],
        )
        nwrites += 1
    return nwrites


def fix_pct_on_cpc_syscohada_reports(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    name_ilike: str = "CPC SYSCOHADA",
    limit: int = 8,
) -> tuple[int, list[int]]:
    """
    Applique :func:`fix_pct_expressions_on_report` sur chaque rapport dont le nom
    correspond (ilike). Retourne ``(nombre d'expressions modifiées, ids de rapports traités)``.
    """
    report_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [[("name", "ilike", name_ilike)]],
        {"limit": limit},
    )
    if not report_ids:
        return 0, []
    total = 0
    touched: list[int] = []
    for rid in report_ids:
        rid_i = int(rid)
        n = fix_pct_expressions_on_report(models, db, uid, password, rid_i)
        if n:
            touched.append(rid_i)
        total += n
    return total, touched
