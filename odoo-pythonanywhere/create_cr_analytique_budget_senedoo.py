# -*- coding: utf-8 -*-
"""
Rapport Odoo « CR analytique budgété » (account.report) — usage 100 % interface Odoo.

Objectif :
  - **Réalisé** : soldes sur la période choisie, ventilés sur le **compte analytique** sélectionné
    dans les filtres du rapport (``filter_analytic`` + moteur ``account_codes``).
  - **Budget analytique** : montants issus des lignes **crossovered** (``crossovered.budget.lines``)
    pour le même axe analytique ; moteur ``external`` + valeurs injectées (API / action serveur),
    car l’utilisateur final n’a pas accès à la toolbox.
  - **Budget financier** (optionnel) : si la base expose le moteur ``budget`` sur les expressions,
    une colonne supplémentaire ``budget`` permet le choix du **budget financier** via le filtre
    natif ``filter_budgets`` / ``filter_budget`` du rapport (comme sur le compte de résultat).
  - **Écart** / **%** : comparent réalisé et **budget analytique**.

La structure des lignes reprend le plan CPC SYSCOHADA (``CPC_BUDGET_STRUCTURE``).

Note : restreindre le réalisé aux « seuls comptes budgétés » au sens strict exige un domaine
dynamique par budget ; ce n’est pas portable en pur ``account.report.expression`` sans module
Odoo dédié. Le réalisé respecte l’analytique ; alignez les préfixes de comptes du rapport sur
votre budget analytique pour un périmètre cohérent.
"""
from __future__ import annotations

from typing import Any

from create_cpc_budget_analytique import (
    CPC_BUDGET_STRUCTURE,
    _agg_formula_with_suffix,
    _create_column_safe,
    _create_expression_safe,
    _create_report_line_safe,
    _expr_formula_for_engine,
    cpc_crossovered_budget_available,
    expression_engine_keys,
)
from personalize_pl_analytic_budget import personalize_pl_analytic_budget_options
from personalize_syscohada_detail import execute_kw

CR_ANALYTIQUE_BUDGET_REPORT_NAME = (
    "CR analytique budgété — Réalisé / Budget analytique (Senedoo)"
)


def _ek(
    models: Any, db: str, uid: int, password: str, model: str, method: str,
    args: list | None = None, kw: dict | None = None,
) -> Any:
    return execute_kw(models, db, uid, password, model, method, args or [], kw or {})


def cr_analytique_budget_pct_formula(line_code: str, *, budget_pct_meaningful: bool) -> str:
    if not budget_pct_meaningful:
        return "0"
    c = line_code
    return f"{c}.balance/{c}.budget_analytic*100"


def collect_cr_analytique_budget_report_ids_for_cleanup(
    models: Any, db: str, uid: int, password: str,
) -> list[int]:
    try:
        ids = _ek(
            models, db, uid, password, "account.report", "search",
            [[["name", "=", CR_ANALYTIQUE_BUDGET_REPORT_NAME]]],
        )
        return [int(i) for i in (ids or [])]
    except Exception:
        return []


def purge_cr_analytique_budget_report_instances(
    models: Any, db: str, uid: int, password: str,
) -> list[int]:
    prior = collect_cr_analytique_budget_report_ids_for_cleanup(models, db, uid, password)
    for rid in prior:
        try:
            cols = _ek(models, db, uid, password, "account.report.column", "search",
                       [[["report_id", "=", rid]]])
            if cols:
                _ek(models, db, uid, password, "account.report.column", "unlink", [cols])
            lines = _ek(models, db, uid, password, "account.report.line", "search",
                        [[["report_id", "=", rid]]])
            if lines:
                exprs = _ek(models, db, uid, password, "account.report.expression", "search",
                            [[["report_line_id", "in", lines]]])
                if exprs:
                    _ek(models, db, uid, password, "account.report.expression", "unlink", [exprs])
                _ek(models, db, uid, password, "account.report.line", "unlink", [lines])
            _ek(models, db, uid, password, "account.report", "unlink", [[rid]])
        except Exception:
            pass
    return prior


def create_toolbox_cr_analytique_budget_report(
    models: Any, db: str, uid: int, password: str,
) -> dict[str, Any]:
    """
    Crée ou recrée le rapport « CR analytique budgété » (même nom = purge puis création).

    Retour : dict analogue à ``create_toolbox_cpc_budget_analytique`` (sans vérification auto CPC).
    """
    prior_ids = purge_cr_analytique_budget_report_instances(models, db, uid, password)

    report_id = int(_ek(models, db, uid, password, "account.report", "create", [{
        "name":                        CR_ANALYTIQUE_BUDGET_REPORT_NAME,
        "filter_date_range":           True,
        "filter_analytic":             True,
        "filter_journals":             True,
        "filter_unfold_all":           True,
        "filter_show_draft":           False,
        "default_opening_date_filter": "this_year",
        "search_bar":                  True,
        "load_more_limit":             80,
    }]))

    filter_written: dict[str, Any] = {}
    filter_personalization_error: str | None = None
    try:
        opt = personalize_pl_analytic_budget_options(
            models, db, uid, password, report_id, enable_budget_filter=True
        )
        filter_written = dict(opt.get("written") or {})
    except Exception as e:
        filter_personalization_error = str(e)

    eng_keys = expression_engine_keys(models, db, uid, password)
    native_financial_budget = "budget" in eng_keys
    crossovered_ok = cpc_crossovered_budget_available(models, db, uid, password)

    if crossovered_ok:
        analytic_budget_mode = "external"
        budget_analytic_meaningful = True
    else:
        analytic_budget_mode = "fallback_gl"
        budget_analytic_meaningful = False

    creation_warnings: list[str] = []
    if not crossovered_ok:
        creation_warnings.append(
            "Modèle crossovered.budget.lines introuvable : la colonne « Budget analytique » "
            "reprend le réalisé (injection impossible). Installez le budget analytique classique."
        )
    if native_financial_budget:
        creation_warnings.append(
            "Colonne « Budget financier » disponible : dans Odoo, utilisez le filtre budgets du "
            "rapport (comme sur le compte de résultat) pour choisir le budget financier."
        )
    else:
        creation_warnings.append(
            "Pas de moteur « budget » sur les expressions : pas de colonne « Budget financier » "
            "native ; seuls réalisé, budget analytique (si crossovered) et écarts sont proposés."
        )

    col_defs: list[dict[str, Any]] = [
        {"name": "Réalisé", "expression_label": "balance", "figure_type": "monetary",
         "report_id": report_id, "sequence": 10, "blank_if_zero": False, "sortable": True},
        {"name": "Budget analytique", "expression_label": "budget_analytic", "figure_type": "monetary",
         "report_id": report_id, "sequence": 20, "blank_if_zero": False, "sortable": True},
    ]
    seq_col = 30
    if native_financial_budget:
        col_defs.append({
            "name": "Budget financier", "expression_label": "budget", "figure_type": "monetary",
            "report_id": report_id, "sequence": seq_col, "blank_if_zero": False, "sortable": True,
        })
        seq_col += 10
    col_defs.extend([
        {"name": "Écart (analytique)", "expression_label": "ecart", "figure_type": "monetary",
         "report_id": report_id, "sequence": seq_col, "blank_if_zero": False, "sortable": True},
        {"name": "% Réalisation (analytique)", "expression_label": "pct", "figure_type": "percentage",
         "report_id": report_id, "sequence": seq_col + 10, "blank_if_zero": False, "sortable": True},
    ])

    col_count = 0
    column_errors: list[str] = []
    for col in col_defs:
        cid, warn = _create_column_safe(models, db, uid, password, col)
        if cid is not None:
            col_count += 1
            if warn:
                column_errors.append(warn)
        else:
            column_errors.append(warn or "colonne inconnue")

    seq = 10
    line_count = 0
    line_errors: list[str] = []
    expression_errors: list[str] = []

    def _push_expr(expr_vals: dict) -> None:
        c = expr_vals.get("_line_code") or "?"
        base = {k: v for k, v in expr_vals.items() if k != "_line_code"}
        vals = _expr_formula_for_engine(base)
        _eid, eerr = _create_expression_safe(models, db, uid, password, vals)
        if eerr:
            expression_errors.append(f"{c} / {vals.get('label')!s} : {eerr}")

    for code, label, nature, formula_ac, formula_agg in CPC_BUDGET_STRUCTURE:
        is_total = code.startswith("X")
        line_id, lwarn = _create_report_line_safe(
            models, db, uid, password,
            code=code, label=label, report_id=report_id, sequence=seq, is_total=is_total,
        )
        seq += 10
        if line_id is None:
            line_errors.append(lwarn or f"{code}: ligne non créée")
            continue
        if lwarn:
            line_errors.append(lwarn)
        line_count += 1

        if nature == "account":
            _push_expr({
                "_line_code": code, "report_line_id": line_id,
                "label": "balance", "engine": "account_codes",
                "formula": formula_ac, "date_scope": "strict_range",
            })
            if analytic_budget_mode == "external":
                _push_expr({
                    "_line_code": code, "report_line_id": line_id,
                    "label": "budget_analytic", "engine": "external",
                    "formula": "sum", "subformula": "editable", "figure_type": "monetary",
                    "date_scope": "strict_range",
                })
            else:
                _push_expr({
                    "_line_code": code, "report_line_id": line_id,
                    "label": "budget_analytic", "engine": "account_codes",
                    "formula": formula_ac, "date_scope": "strict_range",
                })
            if native_financial_budget:
                _push_expr({
                    "_line_code": code, "report_line_id": line_id,
                    "label": "budget", "engine": "budget",
                    "formula": formula_ac, "date_scope": "strict_range",
                })
            _push_expr({
                "_line_code": code, "report_line_id": line_id,
                "label": "ecart", "engine": "aggregation",
                "formula": f"{code}.budget_analytic - {code}.balance",
                "date_scope": "strict_range",
            })
            _push_expr({
                "_line_code": code, "report_line_id": line_id,
                "label": "pct", "engine": "aggregation",
                "formula": cr_analytique_budget_pct_formula(
                    code, budget_pct_meaningful=budget_analytic_meaningful,
                ),
                "date_scope": "strict_range",
            })

        elif nature == "aggregate":
            _push_expr({
                "_line_code": code, "report_line_id": line_id,
                "label": "balance", "engine": "aggregation",
                "formula": _agg_formula_with_suffix(formula_agg, "balance"),
                "date_scope": "strict_range",
            })
            _push_expr({
                "_line_code": code, "report_line_id": line_id,
                "label": "budget_analytic", "engine": "aggregation",
                "formula": _agg_formula_with_suffix(formula_agg, "budget_analytic"),
                "date_scope": "strict_range",
            })
            if native_financial_budget:
                _push_expr({
                    "_line_code": code, "report_line_id": line_id,
                    "label": "budget", "engine": "aggregation",
                    "formula": _agg_formula_with_suffix(formula_agg, "budget"),
                    "date_scope": "strict_range",
                })
            _push_expr({
                "_line_code": code, "report_line_id": line_id,
                "label": "ecart", "engine": "aggregation",
                "formula": f"{code}.budget_analytic - {code}.balance",
                "date_scope": "strict_range",
            })
            _push_expr({
                "_line_code": code, "report_line_id": line_id,
                "label": "pct", "engine": "aggregation",
                "formula": cr_analytique_budget_pct_formula(
                    code, budget_pct_meaningful=budget_analytic_meaningful,
                ),
                "date_scope": "strict_range",
            })

    min_cols = 4 if not native_financial_budget else 5
    return {
        "report_id": report_id,
        "col_count": col_count,
        "line_count": line_count,
        "prior_ids": prior_ids,
        "filter_written": filter_written,
        "filter_personalization_error": filter_personalization_error,
        "column_errors": column_errors,
        "line_errors": line_errors,
        "expression_errors": expression_errors,
        "native_financial_budget": native_financial_budget,
        "analytic_budget_mode": analytic_budget_mode,
        "creation_warnings": creation_warnings,
        "min_columns_expected": min_cols,
    }
