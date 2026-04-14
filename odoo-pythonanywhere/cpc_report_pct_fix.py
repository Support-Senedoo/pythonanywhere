"""
Réparation des rapports « CPC » sur Odoo SaaS (toolbox).

1) Colonne % (moteur aggregation, label ``pct``) : remplace les formules du type
   ``TA.balance/TA.budget*100`` par ``TA.balance*100/(TA.budget+0.0001)`` — seuls les
   nombres et les références ``code.label`` sont valides dans la formule Odoo (pas
   ``XOF(…)`` dans l’agrégation) ; l’epsilon évite la division par zéro au dépliage compte.

2) Détail par compte : sur les lignes feuilles avec moteur ``account_codes``, active
   ``user_groupby=account_id`` et ``foldable`` (comme ``personalize_syscohada_detail``),
   et désactive ``filter_unfold_all`` sur le rapport pour permettre le dépliage.
"""
from __future__ import annotations

from typing import Any

from personalize_syscohada_detail import execute_kw, leaf_line_ids_with_account_codes


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


def pct_formula_ratio(line_code: str, currency_code: str) -> str:
    """
    Formule % = balance*100/budget (agrégation). L’affichage n’a lieu que si le budget
    dépasse 1 unité de devise — voir :func:`pct_subformula_budget_gate`.
    """
    _ = currency_code
    c = (line_code or "").strip()
    return f"{c}.balance*100/{c}.budget"


def pct_subformula_budget_gate(line_code: str, currency_code: str) -> str:
    """N’évalue le % que lorsque ``budget`` est strictement supérieur à 1 unité monétaire."""
    c = (line_code or "").strip()
    cur = (currency_code or "XOF").strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        cur = "XOF"
    return f"if_other_expr_above({c}.budget, {cur}(1))"


def pct_formula_epsilon(line_code: str, currency_code: str) -> str:
    """Rétrocompat : utilise :func:`pct_formula_ratio` (l’ancien epsilon +0.0001 est abandonné)."""
    return pct_formula_ratio(line_code, currency_code)


def cpc_budget_pct_subformula(line_code: str, currency_code: str) -> str:
    """Alias de :func:`pct_subformula_budget_gate` (même logique que ``create_cpc_budget_analytique``)."""
    return pct_subformula_budget_gate(line_code, currency_code)


def search_cpc_like_report_ids(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    limit: int = 40,
) -> list[int]:
    """Rapports dont le nom contient « cpc » (large, pour bases renommées)."""
    return (
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "search",
            [[("name", "ilike", "cpc")]],
            {"limit": limit},
        )
        or []
    )


def rewrite_pct_formulas_safe_denominator(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    currency_code: str,
) -> int:
    """
    Réécrit chaque expression ``pct`` en agrégation : ``balance*100/budget`` avec
    ``subformula`` ``if_other_expr_above(..., devise(1))`` pour masquer le % sans budget.
    """
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
        {"fields": ["engine", "formula", "subformula", "report_line_id", "id"]},
    )
    nwrites = 0
    for row in rows or []:
        if (row.get("engine") or "").strip() != "aggregation":
            continue
        old_raw = (row.get("formula") or "").strip()
        if not old_raw or old_raw == "0":
            continue
        rl = row.get("report_line_id")
        if not rl or not isinstance(rl, (list, tuple)):
            continue
        lines = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [[int(rl[0])]],
            {"fields": ["code"]},
        )
        if not lines:
            continue
        code = (lines[0].get("code") or "").strip()
        if not code:
            continue
        new_f = pct_formula_ratio(code, currency_code)
        new_sub = pct_subformula_budget_gate(code, currency_code)
        if old_raw.replace(" ", "") == new_f.replace(" ", ""):
            sub_old = (row.get("subformula") or "").strip()
            if sub_old.replace(" ", "") == new_sub.replace(" ", ""):
                continue
        wvals: dict[str, Any] = {"formula": new_f, "subformula": new_sub}
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "write",
            [[int(row["id"])], wvals],
        )
        nwrites += 1
    return nwrites


def apply_cpc_leaf_account_groupby(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> int:
    """
    Sur les lignes feuilles « account_codes », active le regroupement par compte et le dépliage.
    """
    line_fg = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "fields_get",
        [],
        {"attributes": ["type"]},
    )
    vals: dict[str, Any] = {}
    if "user_groupby" in line_fg:
        vals["user_groupby"] = "account_id"
    elif "groupby" in line_fg:
        vals["groupby"] = "account_id"
    if "foldable" in line_fg:
        vals["foldable"] = True
    if not vals:
        return 0
    leaves = leaf_line_ids_with_account_codes(
        models, db, uid, password, int(report_id)
    )
    for lid in leaves:
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.line",
                "write",
                [[int(lid)], vals],
            )
        except Exception:
            continue
    rep_fg = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "fields_get",
        [],
        {"attributes": ["type"]},
    )
    if "filter_unfold_all" in rep_fg:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[int(report_id)], {"filter_unfold_all": False}],
        )
    return len(leaves)


def repair_cpc_budget_reports_on_odoo(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    limit: int = 40,
) -> dict[str, Any]:
    """
    Applique réécriture % + groupby compte sur chaque rapport « cpc » (ilike).

    Retourne ``formula_writes``, ``groupby_leaf_lines``, ``report_ids`` (rapports modifiés).
    """
    cur = company_currency_code(models, db, uid, password)
    rids = search_cpc_like_report_ids(models, db, uid, password, limit=limit)
    formula_writes = 0
    groupby_leaf_lines = 0
    touched: list[int] = []
    for rid in rids:
        rid_i = int(rid)
        nf = rewrite_pct_formulas_safe_denominator(
            models, db, uid, password, rid_i, cur
        )
        ng = apply_cpc_leaf_account_groupby(models, db, uid, password, rid_i)
        if nf or ng:
            touched.append(rid_i)
        formula_writes += nf
        groupby_leaf_lines += ng
    return {
        "formula_writes": formula_writes,
        "groupby_leaf_lines": groupby_leaf_lines,
        "report_ids": touched,
        "currency_code": cur,
    }


# Ancienne API (install wizard) — déléguer vers la réparation complète
def fix_pct_on_cpc_syscohada_reports(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    name_ilike: str = "CPC SYSCOHADA",
    limit: int = 8,
) -> tuple[int, list[int]]:
    """Rétrocompat : utilise :func:`repair_cpc_budget_reports_on_odoo` (recherche élargie « cpc »)."""
    _ = name_ilike
    rep = repair_cpc_budget_reports_on_odoo(models, db, uid, password, limit=max(limit, 40))
    return rep["formula_writes"], rep["report_ids"]


def fix_pct_expressions_on_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> int:
    """Réécrit uniquement les % sur un rapport (id connu)."""
    cur = company_currency_code(models, db, uid, password)
    return rewrite_pct_formulas_safe_denominator(
        models, db, uid, password, int(report_id), cur
    )
