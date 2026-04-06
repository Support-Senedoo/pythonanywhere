#!/usr/bin/env python3
"""
Rapport financier projet : réalisé (écritures) / budget / pourcentage, via API Odoo (XML-RPC).

Sans module personnalisé : lecture de account.move.line (analytic_distribution) et
crossovered.budget.lines. Odoo SaaS / v17–v19 : adapter les droits utilisateur et les champs
si fields_get diffère.

Variables d'environnement (ou .env à côté du script si python-dotenv est installé) :
  ODOO_URL       URL de base, ex. https://xxx.odoo.com
  ODOO_DB        nom de la base
  ODOO_USER      login
  ODOO_PASSWORD  mot de passe ou clé API

Exemples :
  python project_pl_analytic_report.py --analytic-id 12 --date-from 2025-01-01 --date-to 2025-12-31
  python project_pl_analytic_report.py --analytic-id 12 --date-from 2025-01-01 --date-to 2025-12-31 --json out.json
  python project_pl_analytic_report.py ... --excel rapport.xlsx
  python project_pl_analytic_report.py ... --full-line-balance
  python project_pl_analytic_report.py ... --currency transaction
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import xmlrpc.client

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from odoo_client import normalize_odoo_base_url

# Pagination search_read (évite la mémoire / timeouts sur grosses bases)
_DEFAULT_PAGE_SIZE = 2000


def default_period_ytd() -> tuple[str, str]:
    """Période par défaut : 1er janvier de l’année en cours → aujourd’hui (date locale)."""
    t = date.today()
    start = t.replace(month=1, day=1)
    return start.isoformat(), t.isoformat()


def search_analytic_accounts_for_select(
    models: Any,
    db: str,
    uid: int,
    password: str,
    filter_text: str,
    *,
    limit: int = 400,
) -> list[dict[str, Any]]:
    """Liste pour liste déroulante : id, name, code, label (libellé affiché)."""
    fg = _fields_get(models, db, uid, password, "account.analytic.account")
    q = (filter_text or "").strip()
    domain: list[Any] = []
    if q:
        if "code" in fg:
            domain = ["|", ("name", "ilike", q), ("code", "ilike", q)]
        else:
            domain = [("name", "ilike", q)]
    fields = ["id", "name"]
    if "code" in fg:
        fields.append("code")
    ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.analytic.account",
        "search",
        [domain],
        {"limit": limit, "order": "name asc"},
    )
    if not ids:
        return []
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.analytic.account",
        "read",
        [ids],
        {"fields": fields},
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        raw_name = r.get("name")
        if isinstance(raw_name, dict):
            name = str(next(iter(raw_name.values()), "") or "")
        else:
            name = (str(raw_name) if raw_name is not None else "").strip()
        code = (r.get("code") or "").strip() if "code" in fields else ""
        label = f"{code} — {name}" if code else name
        out.append({"id": int(r["id"]), "name": name, "code": code, "label": label})
    return out


def read_analytic_account_label(
    models: Any,
    db: str,
    uid: int,
    password: str,
    analytic_account_id: int,
) -> str:
    """Libellé lisible pour un compte analytique (nom + code si présent)."""
    fg = _fields_get(models, db, uid, password, "account.analytic.account")
    fields = ["name"]
    if "code" in fg:
        fields.append("code")
    try:
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "account.analytic.account",
            "read",
            [[int(analytic_account_id)]],
            {"fields": fields},
        )
    except Exception:
        return ""
    if not rows:
        return ""
    r = rows[0]
    raw_name = r.get("name")
    if isinstance(raw_name, dict):
        name = str(next(iter(raw_name.values()), "") or "")
    else:
        name = (str(raw_name) if raw_name is not None else "").strip()
    code = (r.get("code") or "").strip() if "code" in fields else ""
    return f"{code} — {name}" if code else name


def execute_kw(
    models: Any,
    db: str,
    uid: int,
    password: str,
    model: str,
    method: str,
    args: list[Any],
    kwargs: dict[str, Any] | None = None,
) -> Any:
    return models.execute_kw(db, uid, password, model, method, args, kwargs or {})


def connect(
    url: str,
    db: str,
    username: str,
    password: str,
) -> tuple[Any, int, str, str]:
    """
    Connexion XML-RPC. Retourne (models, uid, db, password) pour execute_kw.
    Utilise normalize_odoo_base_url (évite les 301 sur les hôtes Odoo SaaS).
    """
    base = normalize_odoo_base_url(url).rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid_ = common.authenticate(db, username, password, {})
    if not uid_:
        raise RuntimeError("Authentification Odoo refusée (base, login ou mot de passe / clé API).")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, int(uid_), db, password


def _fields_get(
    models: Any,
    db: str,
    uid: int,
    password: str,
    model: str,
) -> dict[str, Any]:
    return execute_kw(models, db, uid, password, model, "fields_get", [], {"attributes": ["type"]})


def _model_exists(models: Any, db: str, uid: int, password: str, model: str) -> bool:
    n = execute_kw(
        models,
        db,
        uid,
        password,
        "ir.model",
        "search_count",
        [[("model", "=", model)]],
    )
    return int(n or 0) > 0


def analytic_key_matches(dist_key: str, analytic_account_id: int) -> bool:
    """True si la clé JSON de analytic_distribution correspond au compte analytique (id simple ou clé composite)."""
    if not dist_key:
        return False
    s = str(analytic_account_id)
    if dist_key == s:
        return True
    # Clés multi-plans : "12,34" ou variantes
    parts = {p.strip() for p in str(dist_key).split(",") if p.strip()}
    return s in parts


def realized_amount_for_analytic_line(
    line: dict[str, Any],
    analytic_account_id: int,
    *,
    full_line_balance: bool,
    currency_mode: str,
) -> float | None:
    """
    Montant réalisé alloué au projet pour cette ligne.
    Retourne None si le projet n'apparaît pas dans analytic_distribution.
    """
    raw = line.get("analytic_distribution")
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None

    matched_pct = 0.0
    for key, pct in raw.items():
        if not analytic_key_matches(str(key), analytic_account_id):
            continue
        try:
            matched_pct += float(pct)
        except (TypeError, ValueError):
            continue

    if matched_pct <= 0:
        return None

    if currency_mode == "transaction":
        amt = line.get("amount_currency")
        cur = line.get("currency_id")
        if amt is None or not cur:
            amt = line.get("balance")
    else:
        amt = line.get("balance")
        if amt is None:
            debit = float(line.get("debit") or 0)
            credit = float(line.get("credit") or 0)
            amt = debit - credit

    try:
        base = float(amt)
    except (TypeError, ValueError):
        return None

    if full_line_balance:
        return base
    return base * (matched_pct / 100.0)


def _domain_move_lines_base(
    date_from: str,
    date_to: str,
    aml_fields: dict[str, Any],
) -> list[tuple]:
    domain: list = [
        ("parent_state", "=", "posted"),
        ("date", ">=", date_from),
        ("date", "<=", date_to),
    ]
    if "display_type" in aml_fields:
        domain.append(("display_type", "not in", ("line_section", "line_note")))
    return domain


def _pick_analytic_domain(
    models: Any,
    db: str,
    uid: int,
    password: str,
    analytic_account_id: int,
    base_domain: list,
) -> list:
    """
    Essaie un filtre serveur sur analytic_distribution (clé id en string puis int).
    Si le domaine est refusé par l'ORM, repli sur « distribution renseignée ».
    Un filtre client dans build_report garantit que seules les lignes avec la bonne clé JSON sont agrégées.
    """
    candidates: list[list] = [
        base_domain + [("analytic_distribution", "in", [str(analytic_account_id)])],
        base_domain + [("analytic_distribution", "in", [analytic_account_id])],
    ]
    for d in candidates:
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.move.line",
                "search_count",
                [d],
            )
            return d
        except Exception:
            continue
    return base_domain + [("analytic_distribution", "!=", False)]


def _search_read_paginated(
    models: Any,
    db: str,
    uid: int,
    password: str,
    model: str,
    domain: list,
    fields: list[str],
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
    order: str = "id",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        chunk = execute_kw(
            models,
            db,
            uid,
            password,
            model,
            "search_read",
            [domain],
            {"fields": fields, "limit": page_size, "offset": offset, "order": order},
        )
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return out


def get_move_lines(
    models: Any,
    db: str,
    uid: int,
    password: str,
    analytic_account_id: int,
    date_from: str,
    date_to: str,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """
    Lit les account.move.line pertinentes pour la période.
    Filtre métier : ne conserve (côté calcul réalisé) que les lignes dont analytic_distribution
    contient le compte analytique demandé (voir compute_realized).
    """
    aml_fields = _fields_get(models, db, uid, password, "account.move.line")
    base_domain = _domain_move_lines_base(date_from, date_to, aml_fields)
    domain = _pick_analytic_domain(models, db, uid, password, analytic_account_id, base_domain)

    fields = ["account_id", "debit", "credit", "balance", "analytic_distribution"]
    if "amount_currency" in aml_fields:
        fields.append("amount_currency")
    if "currency_id" in aml_fields:
        fields.append("currency_id")

    return _search_read_paginated(
        models,
        db,
        uid,
        password,
        "account.move.line",
        domain,
        fields,
        page_size=page_size,
    )


@dataclass
class BudgetLineSpec:
    analytic_field: str
    account_field: str
    amount_field: str
    date_from_path: str  # 'line' | 'crossovered_budget_id.date_from'
    date_to_path: str


def _resolve_budget_spec(models: Any, db: str, uid: int, password: str) -> BudgetLineSpec:
    if not _model_exists(models, db, uid, password, "crossovered.budget.lines"):
        raise RuntimeError(
            "Modèle « crossovered.budget.lines » introuvable (droits ou module Budget non installé). "
            "Vérifier l’édition Odoo ou lancer la sonde : python personalize_pl_analytic_budget.py --probe-only"
        )
    fg = _fields_get(models, db, uid, password, "crossovered.budget.lines")

    if "analytic_account_id" in fg:
        analytic_field = "analytic_account_id"
    elif "account_analytic_id" in fg:
        analytic_field = "account_analytic_id"
    else:
        raise RuntimeError(
            "crossovered.budget.lines : aucun champ analytique reconnu (analytic_account_id / account_analytic_id)."
        )

    for cand in ("general_account_id", "account_id"):
        if cand in fg and fg[cand].get("type") in ("many2one",):
            account_field = cand
            break
    else:
        raise RuntimeError("crossovered.budget.lines : champ compte général introuvable (general_account_id).")

    for cand in ("planned_amount", "budget_amount", "planned_amount_in_company_currency"):
        if cand in fg:
            amount_field = cand
            break
    else:
        raise RuntimeError("crossovered.budget.lines : champ montant budgété introuvable (planned_amount).")

    if "date_from" in fg and "date_to" in fg:
        date_from_path = "line"
        date_to_path = "line"
    else:
        date_from_path = "crossovered_budget_id.date_from"
        date_to_path = "crossovered_budget_id.date_to"

    return BudgetLineSpec(
        analytic_field=analytic_field,
        account_field=account_field,
        amount_field=amount_field,
        date_from_path=date_from_path,
        date_to_path=date_to_path,
    )


def resolve_budget_line_spec(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> BudgetLineSpec:
    """Introspection publique des champs sur crossovered.budget.lines (pour compute_budget)."""
    return _resolve_budget_spec(models, db, uid, password)


def _overlap(
    a_from: str,
    a_to: str,
    b_from: str,
    b_to: str,
) -> bool:
    """Intervalles de dates [a_from,a_to] et [b_from,b_to] (strings YYYY-MM-DD)."""
    return a_to >= b_from and a_from <= b_to


def get_budget_lines(
    models: Any,
    db: str,
    uid: int,
    password: str,
    analytic_account_id: int,
    date_from: str,
    date_to: str,
    *,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """
    Lit les lignes de budget croisé pour le compte analytique et la période (chevauchement).
    """
    spec = _resolve_budget_spec(models, db, uid, password)

    domain: list = [(spec.analytic_field, "=", analytic_account_id)]

    if spec.date_from_path.startswith("crossovered_budget_id"):
        domain += [
            (spec.date_from_path, "<=", date_to),
            (spec.date_to_path, ">=", date_from),
        ]

    fields = [
        spec.account_field,
        spec.amount_field,
        spec.analytic_field,
    ]
    if spec.date_from_path == "line":
        fields.extend(["date_from", "date_to"])
    else:
        fields.append("crossovered_budget_id")

    try:
        raw = _search_read_paginated(
            models,
            db,
            uid,
            password,
            "crossovered.budget.lines",
            domain,
            fields,
            page_size=page_size,
        )
    except Exception:
        domain = [(spec.analytic_field, "=", analytic_account_id)]
        raw = _search_read_paginated(
            models,
            db,
            uid,
            password,
            "crossovered.budget.lines",
            domain,
            fields,
            page_size=page_size,
        )

    if spec.date_from_path == "line":
        return [
            row
            for row in raw
            if row.get("date_from")
            and row.get("date_to")
            and _overlap(date_from, date_to, str(row["date_from"]), str(row["date_to"]))
        ]

    out: list[dict[str, Any]] = []
    budget_ids = list(
        {
            int(row["crossovered_budget_id"][0])
            for row in raw
            if row.get("crossovered_budget_id") and isinstance(row["crossovered_budget_id"], (list, tuple))
        }
    )
    if not budget_ids:
        return []

    budgets = execute_kw(
        models,
        db,
        uid,
        password,
        "crossovered.budget",
        "read",
        [budget_ids],
        {"fields": ["date_from", "date_to"]},
    )
    by_id = {b["id"]: b for b in budgets}

    for row in raw:
        bid_tuple = row.get("crossovered_budget_id")
        if not bid_tuple:
            continue
        bid = int(bid_tuple[0])
        b = by_id.get(bid)
        if not b:
            continue
        bf = b.get("date_from")
        bt = b.get("date_to")
        if bf and bt and _overlap(date_from, date_to, str(bf), str(bt)):
            out.append(row)
    return out


def compute_realized(
    move_lines: list[dict[str, Any]],
    analytic_account_id: int,
    *,
    full_line_balance: bool = False,
    currency_mode: str = "company",
) -> dict[int, float]:
    """Agrège le réalisé par account_id (somme des parts analytiques du projet)."""
    acc: dict[int, float] = {}
    for line in move_lines:
        amt = realized_amount_for_analytic_line(
            line,
            analytic_account_id,
            full_line_balance=full_line_balance,
            currency_mode=currency_mode,
        )
        if amt is None:
            continue
        aid_tuple = line.get("account_id")
        if not aid_tuple:
            continue
        aid = int(aid_tuple[0])
        acc[aid] = acc.get(aid, 0.0) + amt
    return acc


def compute_budget(budget_lines: list[dict[str, Any]], spec: BudgetLineSpec) -> dict[int, float]:
    """Agrège le budget par compte général."""
    acc: dict[int, float] = {}
    for row in budget_lines:
        atuple = row.get(spec.account_field)
        if not atuple:
            continue
        aid = int(atuple[0])
        try:
            v = float(row.get(spec.amount_field) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        acc[aid] = acc.get(aid, 0.0) + v
    return acc


def merge_results(
    models: Any,
    db: str,
    uid: int,
    password: str,
    realized: dict[int, float],
    budget: dict[int, float],
) -> list[dict[str, Any]]:
    """Fusionne les montants par compte ; enrichit avec code / nom du compte (un seul read batch)."""
    ids = sorted(set(realized.keys()) | set(budget.keys()))
    if not ids:
        return []

    accounts = execute_kw(
        models,
        db,
        uid,
        password,
        "account.account",
        "read",
        [ids],
        {"fields": ["code", "name"]},
    )
    meta = {a["id"]: a for a in accounts}

    rows: list[dict[str, Any]] = []
    for aid in ids:
        m = meta.get(aid, {})
        rows.append(
            {
                "account_id": aid,
                "account_code": (m.get("code") or "").strip(),
                "account_name": (m.get("name") or "").strip(),
                "realized": realized.get(aid, 0.0),
                "budget": budget.get(aid, 0.0),
            }
        )
    rows.sort(key=lambda r: r["account_code"] or str(r["account_id"]))
    return rows


def compute_percentage(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ajoute percentage = realized / budget si budget != 0, sinon None."""
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        b = d.get("budget")
        rz = d.get("realized")
        try:
            bf = float(b)
            rf = float(rz)
        except (TypeError, ValueError):
            d["percentage"] = None
            out.append(d)
            continue
        if bf == 0:
            d["percentage"] = None
        else:
            d["percentage"] = rf / bf
        out.append(d)
    return out


def _ohada_class(account_code: str) -> str | None:
    s = (account_code or "").strip()
    if not s:
        return None
    for ch in s:
        if ch.isdigit():
            return ch
    return None


def _token_looks_like_account_prefix(tok: str) -> bool:
    """Heuristique : préfixe de compte OHADA / plan numérique."""
    t = tok.strip()
    if len(t) < 1 or len(t) > 20:
        return False
    if not t[0].isdigit():
        return False
    return all(c.isdigit() or c in ".-" for c in t)


def collect_account_ids_for_account_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> tuple[set[int] | None, str]:
    """
    Best-effort : ids ``account.account`` couverts par les expressions « account_codes »
    sur les lignes feuilles du rapport (même repère que personalize_syscohada_detail).

    Les moteurs « domain » ou formules d’agrégation entre lignes ne sont pas expansés ici.
    """
    from personalize_syscohada_detail import leaf_line_ids_with_account_codes

    try:
        leaves = leaf_line_ids_with_account_codes(models, db, uid, password, report_id)
    except Exception as e:
        return None, f"Lecture du rapport : {e!s}"

    if not leaves:
        return (
            None,
            "Aucune ligne feuille avec expression « account_codes » — impossible d’aligner le périmètre "
            "sur ce rapport (structure différente ou rapport non P&L détail comptes).",
        )

    account_ids: set[int] = set()
    for lid in leaves:
        line = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [[lid]],
            {"fields": ["expression_ids"]},
        )[0]
        eids = line.get("expression_ids") or []
        if not eids:
            continue
        exprs = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "read",
            [eids],
            {"fields": ["engine", "formula"]},
        )
        for e in exprs:
            if (e.get("engine") or "") != "account_codes":
                continue
            raw = e.get("formula")
            if raw is None:
                continue
            if not isinstance(raw, str):
                raw = str(raw)
            for part in re.split(r"[\s,;|]+", raw):
                tok = part.strip().strip("'\"")
                if not tok or not _token_looks_like_account_prefix(tok):
                    continue
                dom = [("code", "=like", f"{tok}%")]
                found = execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.account",
                    "search",
                    [dom],
                    {"limit": 8000},
                )
                account_ids.update(int(x) for x in found)

    if not account_ids:
        return (
            None,
            "Expressions « account_codes » présentes mais aucun compte général résolu (vérifier les formules / préfixes).",
        )
    return account_ids, ""


def add_ohada_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Totaux classe 6, classe 7, globaux, pourcentage global."""
    tot6_r = tot6_b = 0.0
    tot7_r = tot7_b = 0.0
    for r in rows:
        cls = _ohada_class(r.get("account_code", ""))
        rz = float(r.get("realized") or 0.0)
        bz = float(r.get("budget") or 0.0)
        if cls == "6":
            tot6_r += rz
            tot6_b += bz
        elif cls == "7":
            tot7_r += rz
            tot7_b += bz

    tr = sum(float(r.get("realized") or 0.0) for r in rows)
    tb = sum(float(r.get("budget") or 0.0) for r in rows)

    def _pct(a: float, b: float) -> float | None:
        if b == 0:
            return None
        return a / b

    return {
        "class_6": {"realized": tot6_r, "budget": tot6_b, "percentage": _pct(tot6_r, tot6_b)},
        "class_7": {"realized": tot7_r, "budget": tot7_b, "percentage": _pct(tot7_r, tot7_b)},
        "global": {"realized": tr, "budget": tb, "percentage": _pct(tr, tb)},
    }


def build_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    analytic_account_id: int,
    date_from: str,
    date_to: str,
    *,
    full_line_balance: bool = False,
    currency_mode: str = "company",
    page_size: int = _DEFAULT_PAGE_SIZE,
    account_report_id: int | None = None,
) -> dict[str, Any]:
    """Pipeline complet : lignes, agrégats, fusion, pourcentages, totaux OHADA."""
    spec = _resolve_budget_spec(models, db, uid, password)
    move_lines = get_move_lines(
        models,
        db,
        uid,
        password,
        analytic_account_id,
        date_from,
        date_to,
        page_size=page_size,
    )
    # Filtre client : ne garder que les lignes où le projet est bien présent dans la distribution
    move_lines = [
        line
        for line in move_lines
        if realized_amount_for_analytic_line(
            line,
            analytic_account_id,
            full_line_balance=full_line_balance,
            currency_mode=currency_mode,
        )
        is not None
    ]

    budget_lines = get_budget_lines(
        models,
        db,
        uid,
        password,
        analytic_account_id,
        date_from,
        date_to,
        page_size=page_size,
    )

    realized = compute_realized(
        move_lines,
        analytic_account_id,
        full_line_balance=full_line_balance,
        currency_mode=currency_mode,
    )
    budget = compute_budget(budget_lines, spec)
    merged = merge_results(models, db, uid, password, realized, budget)

    scope_meta: dict[str, Any] = {
        "account_report_id": account_report_id,
        "account_report_name": None,
        "scope_filter_applied": False,
        "scope_note": None,
    }
    if account_report_id and account_report_id > 0:
        ar = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "read",
            [[int(account_report_id)]],
            {"fields": ["name"]},
        )
        if ar:
            raw_name = ar[0].get("name")
            scope_meta["account_report_name"] = (
                raw_name if isinstance(raw_name, str) else str(raw_name or "")
            )
        allowed, note = collect_account_ids_for_account_report(
            models, db, uid, password, int(account_report_id)
        )
        if allowed:
            merged = [r for r in merged if int(r["account_id"]) in allowed]
            scope_meta["scope_filter_applied"] = True
        else:
            scope_meta["scope_note"] = note

    with_pct = compute_percentage(merged)
    totals = add_ohada_totals(with_pct)
    return {
        "analytic_account_id": analytic_account_id,
        "analytic_account_label": read_analytic_account_label(
            models, db, uid, password, analytic_account_id
        ),
        "date_from": date_from,
        "date_to": date_to,
        "options": {
            "full_line_balance": full_line_balance,
            "currency_mode": currency_mode,
        },
        "lines": with_pct,
        "totals": totals,
        "scope": scope_meta,
    }


def _dataframes_for_excel(report: dict[str, Any]) -> tuple[Any, Any]:
    """Construit les DataFrames pandas pour l’export Excel."""
    try:
        import pandas as pd
    except ImportError as e:
        raise RuntimeError("Export Excel : installer pandas (pip install pandas openpyxl).") from e

    lines = report.get("lines") or []
    df = pd.DataFrame(lines)
    if not df.empty and "account_id" in df.columns:
        df = df.drop(columns=["account_id"], errors="ignore")

    totals = report.get("totals") or {}
    rows_summary = []
    for key, label in (("class_6", "Classe 6"), ("class_7", "Classe 7"), ("global", "Total global")):
        block = totals.get(key) or {}
        rows_summary.append(
            {
                "section": label,
                "realized": block.get("realized"),
                "budget": block.get("budget"),
                "percentage": block.get("percentage"),
            }
        )
    df_sum = pd.DataFrame(rows_summary)
    return df, df_sum


def report_to_excel_bytes(report: dict[str, Any]) -> bytes:
    """Retourne un classeur .xlsx en mémoire (pandas + openpyxl)."""
    import io

    df, df_sum = _dataframes_for_excel(report)
    import pandas as pd

    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Lignes", index=False)
        df_sum.to_excel(writer, sheet_name="Totaux", index=False)
    bio.seek(0)
    return bio.read()


def export_excel(path: str, report: dict[str, Any]) -> None:
    """Export Excel (pandas + openpyxl)."""
    data = report_to_excel_bytes(report)
    with open(path, "wb") as f:
        f.write(data)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Rapport projet : réalisé / budget / % (API Odoo XML-RPC)."
    )
    p.add_argument("--analytic-id", type=int, required=True, help="ID account.analytic.account")
    p.add_argument("--date-from", required=True, help="Date début (YYYY-MM-DD)")
    p.add_argument("--date-to", required=True, help="Date fin (YYYY-MM-DD)")
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    p.add_argument("--json", metavar="FILE", help="Écrire le rapport JSON dans ce fichier")
    p.add_argument("--excel", metavar="FILE", help="Exporter vers Excel (.xlsx)")
    p.add_argument(
        "--full-line-balance",
        action="store_true",
        help="Compte la balance entière de la ligne si le projet apparaît (sans prorata %).",
    )
    p.add_argument(
        "--currency",
        choices=("company", "transaction"),
        default="company",
        help="company = balance (devise société) ; transaction = amount_currency si dispo.",
    )
    p.add_argument("--page-size", type=int, default=_DEFAULT_PAGE_SIZE, help="Taille des pages search_read")
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
        print("Paramètres manquants :", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    models, uid, db, password = connect(args.url, args.db, args.user, args.password)

    report = build_report(
        models,
        db,
        uid,
        password,
        args.analytic_id,
        args.date_from,
        args.date_to,
        full_line_balance=args.full_line_balance,
        currency_mode=args.currency,
        page_size=max(100, args.page_size),
    )

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)

    if args.excel:
        try:
            export_excel(args.excel, report)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
