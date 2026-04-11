# -*- coding: utf-8 -*-
"""
Alimente la colonne Budget du rapport CPC toolbox (Odoo 19+ sans moteur ``budget`` sur
``account.report.expression``) via ``account.report.external.value``.

Sources supportées (par priorité à l’injection) :
  - ``account.report.budget.item`` : budgets financiers (sélection d’un ``account.report.budget``) ;
  - ``crossovered.budget.lines`` : budget analytique classique (axe analytique obligatoire).
"""
from __future__ import annotations

import json
from typing import Any

from create_cpc_budget_analytique import (
    CPC_BUDGET_STRUCTURE,
    cpc_account_report_budget_item_available,
    cpc_crossovered_budget_available,
    normalize_cpc_account_codes_formula,
)
from personalize_syscohada_detail import execute_kw
from project_pl_analytic_report import compute_budget_aggregate, get_budget_lines


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


def collect_budget_expression_id_by_line_code(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    *,
    expression_label: str = "budget",
) -> dict[str, int]:
    lines = (
        _ek(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "search_read",
            [[["report_id", "=", report_id], ["code", "!=", False]]],
            {"fields": ["code", "expression_ids"]},
        )
        or []
    )
    all_eids: list[int] = []
    line_exprs: dict[str, list[int]] = {}
    for L in lines:
        code = str(L.get("code") or "")
        eids = [int(x) for x in (L.get("expression_ids") or [])]
        line_exprs[code] = eids
        all_eids.extend(eids)
    if not all_eids:
        return {}
    exprs = (
        _ek(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "read",
            [all_eids],
            {"fields": ["id", "label"]},
        )
        or []
    )
    label_by_id = {int(e["id"]): (e.get("label") or "").strip() for e in exprs}
    out: dict[str, int] = {}
    want = (expression_label or "budget").strip()
    for code, eids in line_exprs.items():
        for eid in eids:
            if label_by_id.get(eid) == want:
                out[code] = eid
                break
    return out


def _budget_sum_for_normalized_formula(
    models: Any,
    db: str,
    uid: int,
    password: str,
    raw_formula: str | None,
    budget_by_account: dict[int, float],
) -> float:
    nf = normalize_cpc_account_codes_formula(raw_formula or "")
    if not nf:
        return 0.0
    parts = [p.strip() for p in nf.split("+") if p.strip()]
    total = 0.0
    counted: set[int] = set()
    for pref in parts:
        dom = [("code", "=like", f"{pref}%")]
        aids = (
            _ek(
                models,
                db,
                uid,
                password,
                "account.account",
                "search",
                [dom],
                {"limit": 8000},
            )
            or []
        )
        for aid in aids:
            ia = int(aid)
            if ia in counted:
                continue
            counted.add(ia)
            total += float(budget_by_account.get(ia, 0.0))
    return total


def _m2o_id(val: Any) -> int | None:
    if val in (False, None, ""):
        return None
    if isinstance(val, (list, tuple)) and val:
        return int(val[0])
    if isinstance(val, int):
        return val
    return None


def _fields_get_safe(
    models: Any, db: str, uid: int, password: str, model: str
) -> dict[str, Any]:
    try:
        fg = _ek(models, db, uid, password, model, "fields_get", [], {"attributes": ["type", "relation"]})
        return fg if isinstance(fg, dict) else {}
    except Exception:
        return {}


def _pick_parent_field_for_budget_item(fg: dict[str, Any]) -> str | None:
    """Champ Many2one sur ``account.report.budget.item`` pointant vers l'en-tête de budget."""
    best: str | None = None
    for fname, spec in fg.items():
        if not isinstance(spec, dict) or spec.get("type") != "many2one":
            continue
        rel = (spec.get("relation") or "").strip()
        if rel == "account.report.budget":
            return fname
        if "budget" in fname.lower() and rel.endswith("budget"):
            best = fname
    return best


def _pick_amount_field(fg: dict[str, Any]) -> str | None:
    for cand in ("amount", "budget_amount", "value", "planned_amount", "theoretical_amount"):
        if cand in fg and fg[cand].get("type") in ("float", "monetary", "integer"):
            return cand
    for fname, spec in fg.items():
        if not isinstance(spec, dict):
            continue
        if fname.startswith("message_") or fname.startswith("activity_"):
            continue
        if spec.get("type") in ("float", "monetary") and "account" not in fname.lower():
            if fname in ("id", "sequence", "company_id"):
                continue
            return fname
    return None


def _item_matches_analytic(
    row: dict[str, Any],
    analytic_account_id: int,
    field_names: set[str],
) -> bool:
    """Si un filtre analytique est demandé, ne garder que les lignes d'item qui le portent."""
    if analytic_account_id <= 0:
        return True
    aid = str(analytic_account_id)
    has_aa = "analytic_account_id" in field_names
    has_aas = "analytic_account_ids" in field_names
    has_dist = "analytic_distribution" in field_names
    if not (has_aa or has_aas or has_dist):
        return True

    aa_val = _m2o_id(row.get("analytic_account_id")) if has_aa else None
    dist_raw = row.get("analytic_distribution") if has_dist else None
    aas_raw = row.get("analytic_account_ids") if has_aas else None

    # Ligne « purement financière » : pas de ventilation analytique sur l'item
    if (
        (not aa_val)
        and (not aas_raw)
        and (not dist_raw or dist_raw == {} or dist_raw == [])
    ):
        return True

    if has_aa and aa_val == analytic_account_id:
        return True
    if has_aas and isinstance(aas_raw, (list, tuple)):
        for x in aas_raw:
            if int(x) == analytic_account_id:
                return True
    if has_dist:
        dist = dist_raw
        if isinstance(dist, dict) and aid in dist:
            return True
        if isinstance(dist, str) and dist.strip().startswith("{"):
            try:
                d = json.loads(dist)
                if aid in d or int(aid) in d:
                    return True
            except Exception:
                pass
    return False


def aggregate_budget_by_account_from_report_budget_items(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    budget_id: int,
    date_from: str,
    date_to: str,
    company_id: int | None,
    analytic_account_id: int,
) -> tuple[dict[int, float], str | None]:
    """
    Agrège les montants budgétés par ``account.account`` à partir de ``account.report.budget.item``.

    Retourne (dict account_id -> somme, message d'erreur ou None).
    """
    if budget_id <= 0:
        return {}, "Budget financier (account.report.budget) non indiqué."

    fg_item = _fields_get_safe(models, db, uid, password, "account.report.budget.item")
    if not fg_item:
        return {}, "Impossible de lire les champs de account.report.budget.item."

    parent_fk = _pick_parent_field_for_budget_item(fg_item)
    if not parent_fk:
        return {}, "Aucun champ Many2one vers le budget parent sur account.report.budget.item."

    if "account_id" not in fg_item:
        return {}, "Champ account_id introuvable sur account.report.budget.item."

    amount_f = _pick_amount_field(fg_item)
    if not amount_f:
        return {}, "Aucun champ montant (amount, …) détecté sur account.report.budget.item."

    field_names = set(fg_item.keys())

    parent_model = (fg_item[parent_fk].get("relation") or "account.report.budget").strip()
    parent_dates_ok = True
    p_from = p_to = ""
    if parent_model:
        try:
            prow = _ek(
                models,
                db,
                uid,
                password,
                parent_model,
                "read",
                [[budget_id]],
                {"fields": [f for f in ("date_from", "date_to", "name", "company_id") if f in _fields_get_safe(models, db, uid, password, parent_model)]},
            )
            if prow:
                p0 = prow[0]
                p_from = str(p0.get("date_from") or "")
                p_to = str(p0.get("date_to") or "")
                if p_from and p_to:
                    parent_dates_ok = not (p_to < date_from or p_from > date_to)
        except Exception:
            parent_dates_ok = True

    if not parent_dates_ok:
        return {}, (
            f"Le budget financier id={budget_id} ({p_from} → {p_to}) ne recoupe pas "
            f"la période toolbox ({date_from} → {date_to})."
        )

    domain: list[Any] = [(parent_fk, "=", budget_id)]
    comp = company_id
    if comp and "company_id" in field_names:
        domain.append(("company_id", "=", int(comp)))

    item_ids = (
        _ek(
            models,
            db,
            uid,
            password,
            "account.report.budget.item",
            "search",
            [domain],
            {"limit": 50000},
        )
        or []
    )

    read_fields = ["account_id", amount_f, parent_fk]
    for extra in ("analytic_account_id", "analytic_account_ids", "analytic_distribution", "date", "company_id"):
        if extra in field_names and extra not in read_fields:
            read_fields.append(extra)

    rows = (
        _ek(
            models,
            db,
            uid,
            password,
            "account.report.budget.item",
            "read",
            [item_ids],
            {"fields": read_fields},
        )
        if item_ids
        else []
    )

    out: dict[int, float] = {}
    for row in rows or []:
        if not _item_matches_analytic(row, analytic_account_id, field_names):
            continue
        acc_id = _m2o_id(row.get("account_id"))
        if not acc_id:
            continue
        if "date" in row and row.get("date"):
            d = str(row["date"])
            if d and (d > date_to or d < date_from):
                continue
        try:
            amt = float(row.get(amount_f) or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        out[acc_id] = out.get(acc_id, 0.0) + amt

    return out, None


def _default_company_id(models: Any, db: str, uid: int, password: str) -> int:
    rows = _ek(
        models,
        db,
        uid,
        password,
        "res.users",
        "read",
        [[uid]],
        {"fields": ["company_id"]},
    )
    if not rows:
        return 1
    cid = rows[0].get("company_id")
    if isinstance(cid, (list, tuple)) and cid:
        return int(cid[0])
    return 1


def sync_cpc_budget_external_values(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    report_id: int,
    analytic_account_id: int = 0,
    date_from: str,
    date_to: str,
    company_id: int | None = None,
    account_report_budget_id: int | None = None,
    expression_label: str = "budget",
) -> dict[str, Any]:
    """
    Écrit des ``account.report.external.value`` pour chaque ligne détail CPC (expression
    ``budget`` moteur ``external``).

    Priorité des sources :
      1. ``account_report_budget_id`` + modèle ``account.report.budget.item`` ;
      2. sinon ``crossovered.budget.lines`` pour ``analytic_account_id`` (obligatoire dans ce cas).

    Supprime d’abord les anciennes valeurs externes ciblant ces expressions (toutes dates).
    """
    if report_id <= 0:
        return {"ok": False, "reason": "Rapport invalide.", "written": 0, "source": None}

    expr_lab = (expression_label or "budget").strip()
    # Colonne « budget analytique » : uniquement crossovered (pas de budget financier item).
    if expr_lab == "budget_analytic":
        account_report_budget_id = None

    item_ok = cpc_account_report_budget_item_available(models, db, uid, password)
    cross_ok = cpc_crossovered_budget_available(models, db, uid, password)
    use_items = (
        bool(account_report_budget_id and int(account_report_budget_id) > 0 and item_ok)
        and expr_lab != "budget_analytic"
    )

    if not use_items:
        if analytic_account_id <= 0:
            return {
                "ok": False,
                "reason": "Indiquez un budget financier (account.report.budget) ou un compte analytique pour le mode crossovered.",
                "written": 0,
                "source": None,
            }
        if not cross_ok:
            return {
                "ok": False,
                "reason": "Modèle crossovered.budget.lines introuvable et pas de budget financier utilisable.",
                "written": 0,
                "source": None,
            }

    expr_by_code = collect_budget_expression_id_by_line_code(
        models, db, uid, password, report_id, expression_label=expression_label
    )
    if not expr_by_code:
        return {
            "ok": False,
            "reason": f"Aucune expression « {expr_lab} » sur ce rapport.",
            "written": 0,
            "source": None,
        }

    comp = int(company_id or _default_company_id(models, db, uid, password))
    budget_by_account: dict[int, float] = {}
    source: str | None = None
    meta_extra: dict[str, Any] = {}

    if use_items:
        bid = int(account_report_budget_id or 0)
        budget_by_account, err = aggregate_budget_by_account_from_report_budget_items(
            models,
            db,
            uid,
            password,
            budget_id=bid,
            date_from=date_from,
            date_to=date_to,
            company_id=comp,
            analytic_account_id=int(analytic_account_id or 0),
        )
        if err:
            return {"ok": False, "reason": err, "written": 0, "source": None}
        source = "report_budget_item"
        meta_extra["account_report_budget_id"] = bid
        meta_extra["budget_items_accounts"] = len(budget_by_account)
    else:
        blines = get_budget_lines(
            models,
            db,
            uid,
            password,
            analytic_account_id,
            date_from,
            date_to,
        )
        budget_by_account = compute_budget_aggregate(models, db, uid, password, blines)
        source = "crossovered"
        meta_extra["budget_lines_read"] = len(blines)

    expr_ids = list(expr_by_code.values())
    existing = (
        _ek(
            models,
            db,
            uid,
            password,
            "account.report.external.value",
            "search",
            [[["target_report_expression_id", "in", expr_ids]]],
        )
        or []
    )
    if existing:
        _ek(
            models,
            db,
            uid,
            password,
            "account.report.external.value",
            "unlink",
            [existing],
        )

    written = 0
    details: list[dict[str, Any]] = []
    for code, _label, nature, formula_ac, _fa in CPC_BUDGET_STRUCTURE:
        if nature != "account" or not formula_ac:
            continue
        eid = expr_by_code.get(code)
        if not eid:
            continue
        amt = _budget_sum_for_normalized_formula(
            models, db, uid, password, formula_ac, budget_by_account
        )
        _ek(
            models,
            db,
            uid,
            password,
            "account.report.external.value",
            "create",
            [
                {
                    "name":             f"CPC Senedoo {code}",
                    "value":            float(amt),
                    "date":             date_to,
                    "target_report_expression_id": eid,
                    "company_id":       comp,
                }
            ],
        )
        written += 1
        details.append({"code": code, "value": amt})

    out: dict[str, Any] = {
        "ok": True,
        "written": written,
        "details": details,
        "date_from": date_from,
        "date_to": date_to,
        "analytic_account_id": analytic_account_id,
        "source": source,
    }
    out.update(meta_extra)
    return out
