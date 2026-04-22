#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Outil CLI : budgets **financiers** du reporting Odoo Enterprise (``account.report.budget`` /
``account.report.budget.item``).

Ce périmètre concerne le **budget financier** (montants par compte général pour les rapports
comptables), **pas** le budget analytique classique ``crossovered.budget`` (analytic budget).

Objectifs :
  - analyser une base (champs natifs + Studio / champs manuels, budgets existants) ;
  - **provision-financial-budget** : menus **« Budget Senedoo »** (racine configurable)
    + champs ``x_analytic_account_id`` sur en-tête et lignes — idempotent ;
    + vues formulaire / liste (numéro de compte, analytique), **icône** menu (PNG violet / blanc)
    et **charte** (CSS ``web.assets_backend``, classes ``o_sn_senedoo_financial_budget*``) ;
  - gérer les **noms** de budget et le **lien optionnel** vers un **compte analytique existant**
    (filtrage / cohérence avec le wizard « Budget par projet », sans remplacer un budget analytique) ;
  - importer / exporter des lignes depuis un CSV.

Connexion : variables ``ODOO_URL``, ``ODOO_DB``, ``ODOO_USER``, ``ODOO_PASSWORD``
(fichier ``.env`` à la racine ``odoo-pythonanywhere/`` si python-dotenv est installé),
ou arguments ``--url --db --user --password``.

Exemples (base ``ericfavre-budget``) ::
  python studio_financial_budgets_tool.py remove-studio-financial-budget --dry-run --json
  python studio_financial_budgets_tool.py remove-studio-financial-budget --confirm STUDIO_BUDGET_LEGACY --json
  python studio_financial_budgets_tool.py provision-financial-budget --json
  python studio_financial_budgets_tool.py sync-analytic-to-lines --budget-id 6
  python studio_financial_budgets_tool.py set-budget-analytic --budget-id 6 --analytic-id 42 --propagate-to-lines
  python studio_financial_budgets_tool.py import-items --budget-id 6 --csv lignes.csv --date-from 2026-01-01

Format CSV pour ``import-items`` : ``account_code``, ``amount`` ; optionnel : ``date`` (ou ``--date-from``).
Le compte analytique des lignes est **toujours** celui de l'**en-tête du budget** (ou ``--header-analytic-*``
pour tout le fichier) : une colonne analytique par ligne dans le CSV est **ignorée** (un budget = un axe).
Utilisez ``--no-inherit-header-analytic`` pour créer des lignes **sans** analytique.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from connect_odoo_api import execute_kw, get_connection
from odoo_client import normalize_odoo_base_url


def _connect_cli(args: argparse.Namespace) -> tuple[int, Any, str, str]:
    url = (args.url or os.environ.get("ODOO_URL") or "").strip()
    db = (args.db or os.environ.get("ODOO_DB") or "").strip()
    user = (args.user or os.environ.get("ODOO_USER") or "").strip()
    password = (args.password or os.environ.get("ODOO_PASSWORD") or "").strip()
    if not all([url, db, user, password]):
        print(
            "Connexion incomplète : fournir --url --db --user --password "
            "ou ODOO_URL / ODOO_DB / ODOO_USER / ODOO_PASSWORD.",
            file=sys.stderr,
        )
        sys.exit(2)
    url = normalize_odoo_base_url(url).rstrip("/")
    uid, _common, models = get_connection(url, db, user, password)
    return uid, models, db, password


def _ek(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    model: str,
    method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Appel ``execute_kw`` : ``args`` = liste d'arguments passés à la méthode ORM."""
    return execute_kw(
        models,
        db,
        uid,
        pwd,
        model,
        method,
        list(args or []),
        dict(kwargs or {}),
    )


def _fg(
    models: Any, db: str, uid: int, pwd: str, model: str
) -> dict[str, Any]:
    raw = _ek(
        models,
        db,
        uid,
        pwd,
        model,
        "fields_get",
        args=[],
        kwargs={"attributes": ["type", "relation", "required", "readonly", "string"]},
    )
    return raw if isinstance(raw, dict) else {}


def _pick_budget_item_parent_field(fg: dict[str, Any]) -> str | None:
    for fname, spec in fg.items():
        if not isinstance(spec, dict) or spec.get("type") != "many2one":
            continue
        if (spec.get("relation") or "").strip() == "account.report.budget":
            return fname
    for cand in ("budget_id", "report_budget_id", "account_report_budget_id", "budget"):
        if cand in fg and fg[cand].get("type") == "many2one":
            return cand
    return None


def _pick_amount_field(fg: dict[str, Any]) -> str | None:
    for cand in ("value", "budget_amount", "amount", "planned_amount", "theoretical_amount"):
        if cand in fg and fg[cand].get("type") in ("float", "monetary", "integer"):
            return cand
    return None


def _pick_analytic_field_budget_header(fg: dict[str, Any]) -> str | None:
    if "x_analytic_account_id" in fg:
        return "x_analytic_account_id"
    if "analytic_account_id" in fg:
        return "analytic_account_id"
    return None


def _pick_analytic_field_budget_item(fg: dict[str, Any]) -> str | None:
    for cand in ("x_analytic_account_id", "analytic_account_id"):
        if cand in fg and fg[cand].get("type") == "many2one":
            return cand
    return None


def _m2o_id_from_read(val: Any) -> int | None:
    """Extrait l'id d'un champ many2one renvoyé par ``read`` / ``search_read``."""
    if val in (None, False, ""):
        return None
    if isinstance(val, (list, tuple)) and val:
        try:
            return int(val[0])
        except (TypeError, ValueError):
            return None
    if isinstance(val, int):
        return val
    return None


def _budget_header_analytic_id(budget_row: dict[str, Any], fg_budget: dict[str, Any]) -> int | None:
    """Compte analytique posé sur l'en-tête ``account.report.budget`` (champ reconnu)."""
    for fname in ("x_analytic_account_id", "analytic_account_id"):
        if fname not in fg_budget:
            continue
        aid = _m2o_id_from_read(budget_row.get(fname))
        if aid:
            return aid
    return None


def _resolve_budget_id(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    budget_id: int | None,
    budget_name: str | None,
) -> int:
    if budget_id and budget_id > 0:
        n = _ek(
            models,
            db,
            uid,
            pwd,
            "account.report.budget",
            "search_count",
            args=[[("id", "=", budget_id)]],
        )
        if not int(n or 0):
            raise RuntimeError(f"Budget financier id={budget_id} introuvable.")
        return int(budget_id)
    if budget_name and budget_name.strip():
        q = budget_name.strip()
        bids = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "account.report.budget",
                "search",
                args=[[("name", "=", q)]],
                kwargs={"limit": 2},
            )
            or []
        )
        if not bids:
            bids = (
                _ek(
                    models,
                    db,
                    uid,
                    pwd,
                    "account.report.budget",
                    "search",
                    args=[[("name", "ilike", q)]],
                    kwargs={"limit": 2},
                )
                or []
            )
        if not bids:
            raise RuntimeError(f"Aucun budget financier pour le nom {q!r}.")
        if len(bids) > 1:
            raise RuntimeError(f"Plusieurs budgets pour {q!r} : ids={bids}. Précisez --budget-id.")
        return int(bids[0])
    raise RuntimeError("Indiquez --budget-id ou --budget-name.")


def _as_date_str(val: Any) -> str:
    if val in (None, False, ""):
        return ""
    if hasattr(val, "strftime"):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    return s[:10] if s else ""


def _budget_header_read_fields(fg: dict[str, Any]) -> list[str]:
    """Champs sûrs pour ``read`` / ``search_read`` sur ``account.report.budget`` (varie selon versions)."""
    names = ["id", "name", "company_id"]
    for opt in ("date_from", "date_to", "x_analytic_account_id", "analytic_account_id"):
        if opt in fg:
            names.append(opt)
    return names


def _model_ids(
    models: Any, db: str, uid: int, pwd: str, names: list[str]
) -> dict[str, int]:
    rows = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model",
            "search_read",
            args=[[("model", "in", names)]],
            kwargs={"fields": ["id", "model"]},
        )
        or []
    )
    return {str(r["model"]): int(r["id"]) for r in rows if r.get("model")}


def cmd_analyze(
    models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace
) -> None:
    out: dict[str, Any] = {"database": db, "models": {}}
    for mname in ("account.report.budget", "account.report.budget.item"):
        try:
            n = _ek(models, db, uid, pwd, mname, "search_count", args=[[]])
        except Exception as e:
            out["models"][mname] = {"error": str(e)}
            continue
        fg = _fg(models, db, uid, pwd, mname)
        out["models"][mname] = {
            "record_count": int(n or 0),
            "fields": sorted(fg.keys()),
            "field_details": {
                k: {
                    "type": v.get("type"),
                    "relation": v.get("relation"),
                    "required": bool(v.get("required")),
                    "readonly": bool(v.get("readonly")),
                    "string": v.get("string"),
                }
                for k, v in fg.items()
                if isinstance(v, dict)
            },
        }

    mid_by_model = _model_ids(
        models, db, uid, pwd, ["account.report.budget", "account.report.budget.item"]
    )
    manual: list[dict[str, Any]] = []
    if mid_by_model:
        mids = list(mid_by_model.values())
        manual = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.model.fields",
                "search_read",
                args=[[("model_id", "in", mids), ("state", "=", "manual")]],
                kwargs={
                    "fields": ["name", "field_description", "ttype", "relation", "model_id"],
                    "order": "model_id,name",
                    "limit": 500,
                },
            )
            or []
        )
    out["manual_fields_studio_like"] = manual

    # Menus / actions liés aux budgets financiers
    try:
        menus = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.menu",
                "search_read",
                args=[[("name", "ilike", "budget")]],
                kwargs={"fields": ["id", "name", "complete_name", "action"], "limit": 80},
            )
            or []
        )
        budget_menus = [m for m in menus if "account.report.budget" in str(m.get("action") or "")]
        out["menus_budget_financier"] = budget_menus[:40]
    except Exception as e:
        out["menus_budget_financier_error"] = str(e)

    mods = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.module.module",
            "search_read",
            args=[[("name", "ilike", "studio")]],
            kwargs={"fields": ["name", "shortdesc", "state"], "limit": 40},
        )
        or []
    )
    out["modules_studio_name_ilike"] = mods

    if getattr(args, "budget_q", None) and str(args.budget_q).strip():
        q = str(args.budget_q).strip()
        fg_budget_q = _fg(models, db, uid, pwd, "account.report.budget")
        budgets = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "account.report.budget",
                "search_read",
                args=[[("name", "ilike", q)]],
                kwargs={"fields": _budget_header_read_fields(fg_budget_q), "limit": 50},
            )
            or []
        )
        out["budgets_matching"] = budgets

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        return

    print(f"Base : {db}\n")
    for mname, blob in out.get("models", {}).items():
        print(f"=== {mname} ===")
        if "error" in blob:
            print("  Erreur :", blob["error"])
            continue
        print("  Enregistrements :", blob.get("record_count"))
        print("  Champs :", ", ".join(blob.get("fields") or [])[:2000])
        print()
    print("=== Champs manuels (Studio / ir.model.fields state=manual) sur budget + items ===")
    for row in out.get("manual_fields_studio_like") or []:
        mid = row.get("model_id")
        midv = mid[0] if isinstance(mid, (list, tuple)) else mid
        mlabel = {v: k for k, v in mid_by_model.items()}.get(int(midv or 0), "?")
        print(
            f"  - [{mlabel}] {row.get('name')}  ({row.get('ttype')}"
            f"{',' + row['relation'] if row.get('relation') else ''})  {row.get('field_description')!r}"
        )
    print("\n=== Modules dont le nom contient « studio » ===")
    for m in out.get("modules_studio_name_ilike") or []:
        print(f"  - {m.get('name')} [{m.get('state')}] {m.get('shortdesc')!r}")
    if out.get("budgets_matching") is not None:
        print("\n=== Budgets (filtre nom) ===")
        for b in out["budgets_matching"]:
            print(f"  id={b.get('id')}  {b.get('name')!r}  company={b.get('company_id')}")
    if out.get("menus_budget_financier"):
        print("\n=== Menus avec action vers account.report.budget ===")
        for m in out["menus_budget_financier"]:
            print(f"  id={m.get('id')}  {m.get('complete_name') or m.get('name')!r}")


def cmd_ensure_analytic(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    from create_cpc_odoo_wizard import ensure_budget_report_analytic_fields

    res = ensure_budget_report_analytic_fields(models, db, uid, pwd)
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


def _default_company_id(models: Any, db: str, uid: int, pwd: str) -> int:
    cids = _ek(
        models,
        db,
        uid,
        pwd,
        "res.company",
        "search",
        args=[[]],
        kwargs={"limit": 1, "order": "id asc"},
    )
    if not cids:
        raise RuntimeError("Aucune société (res.company) — impossible de créer le budget.")
    return int(cids[0])


def _resolve_analytic_id(
    models: Any, db: str, uid: int, pwd: str, *, analytic_id: int | None, analytic_name: str | None
) -> int:
    if analytic_id and analytic_id > 0:
        ok = _ek(
            models,
            db,
            uid,
            pwd,
            "account.analytic.account",
            "search_count",
            args=[[("id", "=", analytic_id)]],
        )
        if not int(ok or 0):
            raise RuntimeError(f"Compte analytique id={analytic_id} introuvable.")
        return analytic_id
    if analytic_name:
        aids = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "account.analytic.account",
                "search",
                args=[[("name", "ilike", analytic_name.strip())]],
                kwargs={"limit": 2},
            )
            or []
        )
        if not aids:
            raise RuntimeError(f"Aucun compte analytique pour la recherche {analytic_name!r}.")
        if len(aids) > 1:
            raise RuntimeError(
                f"Plusieurs comptes analytiques pour {analytic_name!r} : ids={aids}. Précisez --analytic-id."
            )
        return int(aids[0])
    raise RuntimeError("Indiquez --analytic-id ou --analytic-name.")


def cmd_create_budget(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    fg = _fg(models, db, uid, pwd, "account.report.budget")
    if not fg:
        raise RuntimeError("Modèle account.report.budget introuvable ou illisible.")

    company_id = int(args.company_id) if args.company_id else _default_company_id(models, db, uid, pwd)
    analytic_id = _resolve_analytic_id(
        models,
        db,
        uid,
        pwd,
        analytic_id=args.analytic_id,
        analytic_name=args.analytic_name,
    )

    vals: dict[str, Any] = {"name": args.name.strip()}
    if "company_id" in fg and not fg["company_id"].get("readonly"):
        vals["company_id"] = company_id
    for df, arg in (("date_from", args.date_from), ("date_to", args.date_to)):
        if df in fg and arg:
            vals[df] = arg.strip()

    af = _pick_analytic_field_budget_header(fg)
    if af:
        vals[af] = analytic_id

    bid = _ek(models, db, uid, pwd, "account.report.budget", "create", args=[vals])
    bid = int(bid)
    if args.json:
        print(json.dumps({"id": bid, "values": vals}, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Budget créé : id={bid}  valeurs={vals}")


def _parse_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    sample = text[:4096]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    f = io.StringIO(text)
    reader = csv.DictReader(f, delimiter=delim)
    if not reader.fieldnames:
        raise ValueError("CSV sans en-tête.")
    fields = [h.strip() for h in reader.fieldnames if h]
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        if not any(row.values()):
            continue
        rows.append(row)
    return fields, rows


def _account_id_for_code(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    code: str,
    company_id: int,
) -> int:
    code = (code or "").strip()
    if not code:
        raise ValueError("Code compte vide.")
    dom: list[Any] = ["|", ("company_ids", "in", [company_id]), ("company_id", "=", company_id)]
    # Odoo : souvent code + société
    dom = ["&", ("code", "=", code)] + dom
    aids = _ek(
        models,
        db,
        uid,
        pwd,
        "account.account",
        "search",
        args=[dom],
        kwargs={"limit": 2},
    )
    if not aids:
        dom2 = [("code", "=", code)]
        aids = _ek(
            models,
            db,
            uid,
            pwd,
            "account.account",
            "search",
            args=[dom2],
            kwargs={"limit": 5},
        )
    if not aids:
        raise RuntimeError(f"Aucun compte account.account avec le code {code!r} pour la société {company_id}.")
    if len(aids) > 1:
        raise RuntimeError(
            f"Plusieurs comptes pour le code {code!r} : ids={aids}. Affinez le plan ou la société."
        )
    return int(aids[0])


def cmd_import_items(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    budget_id = int(args.budget_id)
    fg_b_hdr = _fg(models, db, uid, pwd, "account.report.budget")
    rows_b = _ek(
        models,
        db,
        uid,
        pwd,
        "account.report.budget",
        "read",
        args=[[budget_id]],
        kwargs={"fields": _budget_header_read_fields(fg_b_hdr)},
    )
    if not rows_b:
        raise RuntimeError(f"Budget id={budget_id} introuvable.")
    b0 = rows_b[0]
    company_tuple = b0.get("company_id")
    company_id = int(company_tuple[0]) if isinstance(company_tuple, (list, tuple)) else _default_company_id(models, db, uid, pwd)

    fg_item = _fg(models, db, uid, pwd, "account.report.budget.item")
    parent_f = _pick_budget_item_parent_field(fg_item)
    amt_f = _pick_amount_field(fg_item)
    if not parent_f or not amt_f:
        raise RuntimeError(
            f"Impossible de deviner les champs parent ({parent_f!r}) ou montant ({amt_f!r}) "
            f"sur account.report.budget.item — lancez « analyze »."
        )
    analytic_item_f = _pick_analytic_field_budget_item(fg_item)

    if args.replace_all:
        item_ids = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "account.report.budget.item",
                "search",
                args=[[(parent_f, "=", budget_id)]],
            )
            or []
        )
        if item_ids:
            _ek(
                models,
                db,
                uid,
                pwd,
                "account.report.budget.item",
                "unlink",
                args=[item_ids],
            )

    path = Path(args.csv)
    text = path.read_text(encoding="utf-8-sig")
    headers, data = _parse_csv(text)
    key_code = next(
        (h for h in headers if h.lower().replace(" ", "_") in ("account_code", "code", "compte")),
        None,
    )
    key_amt = next(
        (h for h in headers if h.lower().replace(" ", "_") in ("amount", "montant", "value", "budget")),
        None,
    )
    if not key_code or not key_amt:
        raise RuntimeError(
            f"CSV : colonnes compte / montant introuvables. En-têtes : {headers}. "
            "Attendu : account_code (ou code) et amount (ou montant)."
        )

    d_from_hdr = _as_date_str(b0.get("date_from"))
    d_to_hdr = _as_date_str(b0.get("date_to"))

    created = 0
    errors: list[str] = []
    batch: list[dict[str, Any]] = []
    batch_size = max(1, int(args.batch_size or 80))

    def flush() -> None:
        nonlocal created, batch
        if not batch:
            return
        _ek(models, db, uid, pwd, "account.report.budget.item", "create", args=[batch])
        created += len(batch)
        batch = []

    header_analytic_cli: int | None = None
    if getattr(args, "header_analytic_id", None) or getattr(args, "header_analytic_name", None):
        header_analytic_cli = _resolve_analytic_id(
            models,
            db,
            uid,
            pwd,
            analytic_id=getattr(args, "header_analytic_id", None),
            analytic_name=getattr(args, "header_analytic_name", None),
        )
    header_analytic_from_budget = _budget_header_analytic_id(b0, fg_b_hdr)
    default_line_analytic: int | None = header_analytic_cli or header_analytic_from_budget
    skip_inherit = bool(getattr(args, "no_inherit_header_analytic", False))

    for i, row in enumerate(data, start=2):
        code = row.get(key_code, "").strip()
        amt_raw = row.get(key_amt, "").replace(" ", "").replace(",", ".")
        try:
            amt = float(amt_raw) if amt_raw else 0.0
        except ValueError:
            errors.append(f"Ligne {i}: montant invalide {amt_raw!r}")
            continue
        try:
            acc_id = _account_id_for_code(models, db, uid, pwd, code, company_id)
        except Exception as e:
            errors.append(f"Ligne {i} ({code}): {e}")
            continue

        vals: dict[str, Any] = {parent_f: budget_id, amt_f: amt}
        if "account_id" in fg_item:
            vals["account_id"] = acc_id

        if "date" in fg_item:
            d_cell = (row.get("date") or "").strip()
            d_line = d_cell or (args.date_from or "").strip()
            if not d_line:
                errors.append(
                    f"Ligne {i}: champ « date » sur la ligne budget ; "
                    "ajoutez une colonne date au CSV ou passez --date-from (ex. période mensuelle)."
                )
                continue
            vals["date"] = d_line
        else:
            df = row.get("date_from") or row.get("date_from".upper())
            dt = row.get("date_to") or row.get("date_to".upper())
            if "date_from" in fg_item:
                vals["date_from"] = _as_date_str(df or d_from_hdr or args.date_from) or False
            if "date_to" in fg_item:
                vals["date_to"] = _as_date_str(dt or d_to_hdr or args.date_to) or False
            if "date_from" in fg_item and "date_to" in fg_item:
                if vals.get("date_from") is False or vals.get("date_to") is False:
                    errors.append(
                        f"Ligne {i}: date_from/date_to obligatoires sur ce modèle ; "
                        "CSV, en-tête budget, ou --date-from / --date-to."
                    )
                    continue

        # Analytique : uniquement l'en-tête du budget (ou --header-analytic-*), jamais par ligne CSV.
        if analytic_item_f and default_line_analytic and not skip_inherit:
            vals[analytic_item_f] = default_line_analytic

        batch.append(vals)
        if len(batch) >= batch_size:
            flush()

    flush()

    out = {"created": created, "errors": errors}
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Lignes créées : {created}")
        if errors:
            print("Avertissements / erreurs :")
            for e in errors[:50]:
                print(" ", e)
            if len(errors) > 50:
                print(f"  ... ({len(errors) - 50} de plus)")


def run_sync_analytic_to_lines(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    budget_id: int | None,
    budget_name: str | None,
    force_all: bool = False,
    dry_run: bool = False,
    chunk: int = 200,
) -> dict[str, Any]:
    """
    Recopie le compte analytique de l'en-tête ``account.report.budget`` sur les lignes
    ``account.report.budget.item`` sans analytique (ou toutes si ``force_all``).
    Retourne un dict (pour CLI JSON ou composition avec ``set-budget-analytic``).
    """
    bid = _resolve_budget_id(
        models,
        db,
        uid,
        pwd,
        budget_id=budget_id,
        budget_name=budget_name,
    )
    fg_b = _fg(models, db, uid, pwd, "account.report.budget")
    hdr_field = _pick_analytic_field_budget_header(fg_b)
    if not hdr_field:
        raise RuntimeError(
            "Aucun champ analytique sur l'en-tête budget (x_analytic_account_id / analytic_account_id). "
            "Lancez « ensure-analytic-fields » d'abord."
        )
    rows_b = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "account.report.budget",
            "read",
            args=[[bid]],
            kwargs={"fields": [hdr_field, "name"]},
        )
        or []
    )
    if not rows_b:
        raise RuntimeError(f"Budget id={bid} introuvable.")
    analytic_hdr = _m2o_id_from_read(rows_b[0].get(hdr_field))
    if not analytic_hdr:
        raise RuntimeError(
            "Le budget n'a pas de compte analytique sur l'en-tête. "
            "Éditez-le dans Odoo ou : ``set-budget-analytic --budget-id … --analytic-id …``."
        )

    fg_item = _fg(models, db, uid, pwd, "account.report.budget.item")
    parent_f = _pick_budget_item_parent_field(fg_item)
    af_line = _pick_analytic_field_budget_item(fg_item)
    if not parent_f or not af_line:
        raise RuntimeError("Modèle ligne budget : champs parent ou analytique non reconnus.")

    dom: list[Any] = [(parent_f, "=", bid)]
    if not force_all:
        dom.append((af_line, "=", False))

    item_ids = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "account.report.budget.item",
            "search",
            args=[dom],
        )
        or []
    )
    if dry_run:
        return {
            "budget_id": bid,
            "budget_name": rows_b[0].get("name"),
            "analytic_header_id": analytic_hdr,
            "line_ids_would_update": len(item_ids),
            "dry_run": True,
        }

    ch = max(50, min(500, int(chunk or 200)))
    updated = 0
    for i in range(0, len(item_ids), ch):
        part = item_ids[i : i + ch]
        _ek(
            models,
            db,
            uid,
            pwd,
            "account.report.budget.item",
            "write",
            args=[part, {af_line: analytic_hdr}],
        )
        updated += len(part)

    return {
        "budget_id": bid,
        "budget_name": rows_b[0].get("name"),
        "analytic_header_id": analytic_hdr,
        "lines_updated": updated,
    }


def cmd_sync_analytic_to_lines(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    out = run_sync_analytic_to_lines(
        models,
        db,
        uid,
        pwd,
        budget_id=getattr(args, "budget_id", None),
        budget_name=getattr(args, "budget_name", None),
        force_all=bool(getattr(args, "force_all", False)),
        dry_run=bool(getattr(args, "dry_run", False)),
        chunk=int(getattr(args, "chunk", 200) or 200),
    )
    if getattr(args, "json", False):
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    elif not out.get("dry_run"):
        print(
            f"Compte analytique en-tête id={out['analytic_header_id']} recopié sur {out['lines_updated']} "
            f"ligne(s) (budget id={out['budget_id']})."
        )
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


def cmd_set_budget_analytic(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    """Écrit le compte analytique sur l'en-tête ``account.report.budget`` ; optionnellement recopie sur les lignes."""
    budget_id = _resolve_budget_id(
        models,
        db,
        uid,
        pwd,
        budget_id=getattr(args, "budget_id", None),
        budget_name=getattr(args, "budget_name", None),
    )
    analytic_id = _resolve_analytic_id(
        models,
        db,
        uid,
        pwd,
        analytic_id=getattr(args, "analytic_id", None),
        analytic_name=getattr(args, "analytic_name", None),
    )
    fg_b = _fg(models, db, uid, pwd, "account.report.budget")
    hdr_field = _pick_analytic_field_budget_header(fg_b)
    if not hdr_field:
        raise RuntimeError(
            "Aucun champ analytique sur l'en-tête budget. Exécutez « ensure-analytic-fields » d'abord."
        )
    _ek(
        models,
        db,
        uid,
        pwd,
        "account.report.budget",
        "write",
        args=[[budget_id], {hdr_field: analytic_id}],
    )
    out: dict[str, Any] = {
        "budget_id": budget_id,
        "header_field": hdr_field,
        "analytic_id": analytic_id,
    }
    if getattr(args, "propagate_to_lines", False):
        out["sync_lines"] = run_sync_analytic_to_lines(
            models,
            db,
            uid,
            pwd,
            budget_id=budget_id,
            budget_name=None,
            force_all=bool(getattr(args, "propagate_force_all", False)),
            dry_run=False,
            chunk=int(getattr(args, "chunk", 200) or 200),
        )
    if getattr(args, "json", False):
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        msg = f"Budget id={budget_id} : {hdr_field} = compte analytique id {analytic_id}."
        if out.get("sync_lines"):
            msg += f" Lignes mises à jour : {out['sync_lines'].get('lines_updated', 0)}."
        print(msg)


# --- Provision « Budget Senedoo » : champs analytiques + menus Reporting (budgets financiers) ---

DEFAULT_MENU_ROOT = "Budget Senedoo"


def _menu_res_id_from_xmlid(
    models: Any, db: str, uid: int, pwd: str, module: str, xml_name: str
) -> int | None:
    rows = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            args=[[("module", "=", module), ("name", "=", xml_name), ("model", "=", "ir.ui.menu")]],
            kwargs={"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if not rows:
        return None
    rid = rows[0].get("res_id")
    return int(rid) if rid else None


def _reporting_parent_menu_id(models: Any, db: str, uid: int, pwd: str) -> tuple[int | None, str]:
    """Parent menu Comptabilité > Reporting (ou équivalent)."""
    try:
        from create_cpc_odoo_wizard import _resolve_wizard_parent_menu

        pid, src = _resolve_wizard_parent_menu(models, db, uid, pwd)
        if pid:
            return int(pid), src
    except Exception:
        pass
    for mod, xname in (
        ("account", "menu_finance_reports"),
        ("account_accountant", "account_reports_menu"),
    ):
        rid = _menu_res_id_from_xmlid(models, db, uid, pwd, mod, xname)
        if rid:
            return rid, f"{mod}.{xname}"
    rid = _menu_res_id_from_xmlid(models, db, uid, pwd, "account", "menu_finance")
    if rid:
        return rid, "account.menu_finance"
    return None, "none"


def _find_or_create_act_window(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    name: str,
    res_model: str,
    view_mode: str,
) -> tuple[int, str]:
    """Retourne (id, status) status=found|created."""
    found = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.actions.act_window",
            "search",
            args=[[("name", "=", name), ("res_model", "=", res_model)]],
            kwargs={"limit": 1},
        )
        or []
    )
    if found:
        return int(found[0]), "found"
    aid = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.actions.act_window",
        "create",
        args=[
            {
                "name": name,
                "res_model": res_model,
                "view_mode": view_mode,
                "target": "current",
            }
        ],
    )
    return int(aid), "created"


def provision_financial_budget_toolbox(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    menu_root: str | None = None,
    placement: str = "top",
) -> dict[str, Any]:
    """
    Idempotent : champs ``x_analytic_account_id`` (toolbox) + menus pour
    ``account.report.budget`` et ``account.report.budget.item``.

    ``placement`` :
      - ``top`` (défaut) : menu racine **sans parent**, visible comme l’ancien Studio
        (barre principale Odoo, au même niveau que « Budget Financier »).
      - ``reporting`` : menu sous **Comptabilité > Reporting** (moins visible).
    """
    from create_cpc_odoo_wizard import (
        ensure_budget_report_analytic_fields,
        ensure_budget_report_item_account_code_field,
        ensure_budget_report_item_account_name_field,
        ensure_budget_report_senedoo_budget_views,
        ensure_senedoo_financial_budget_toolbox_branding,
    )

    root_label = (menu_root or "").strip() or DEFAULT_MENU_ROOT
    place = (placement or "top").strip().lower()
    if place not in ("top", "reporting"):
        raise ValueError("placement doit être « top » ou « reporting ».")

    out: dict[str, Any] = {
        "menu_root": root_label,
        "placement": place,
        "analytic_fields": {},
        "budget_item_account_code": {},
        "budget_item_account_name": {},
        "budget_views": {},
        "branding": {},
        "actions": {},
        "menus": {},
    }

    out["analytic_fields"] = ensure_budget_report_analytic_fields(models, db, uid, pwd)
    out["budget_item_account_code"] = ensure_budget_report_item_account_code_field(
        models, db, uid, pwd
    )
    out["budget_item_account_name"] = ensure_budget_report_item_account_name_field(
        models, db, uid, pwd
    )
    out["budget_views"] = ensure_budget_report_senedoo_budget_views(models, db, uid, pwd)

    parent_id: int | bool | None = False
    parent_src = "root_bar_parent_false"
    if place == "reporting":
        pid, parent_src = _reporting_parent_menu_id(models, db, uid, pwd)
        if not pid:
            raise RuntimeError(
                "Impossible de trouver le menu parent Reporting (comptabilité). "
                "Vérifiez les droits et les modules comptables installés."
            )
        parent_id = int(pid)
    out["menu_parent_id"] = parent_id if parent_id is not False else None
    out["menu_parent_source"] = parent_src

    act_header_name = f"{root_label} — En-têtes"
    act_lines_name = f"{root_label} — Lignes"
    view_hdr = "list,form"
    view_lines = "list,form"

    ah_id, ah_st = _find_or_create_act_window(
        models,
        db,
        uid,
        pwd,
        name=act_header_name,
        res_model="account.report.budget",
        view_mode=view_hdr,
    )
    al_id, al_st = _find_or_create_act_window(
        models,
        db,
        uid,
        pwd,
        name=act_lines_name,
        res_model="account.report.budget.item",
        view_mode=view_lines,
    )
    out["actions"] = {
        "headers": {"id": ah_id, "status": ah_st},
        "lines": {"id": al_id, "status": al_st},
    }

    parent_domain_val: int | bool = parent_id if parent_id is not False else False
    existing_root = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.menu",
            "search",
            args=[[("name", "=", root_label), ("parent_id", "=", parent_domain_val)]],
            kwargs={"limit": 5},
        )
        or []
    )
    if len(existing_root) > 1:
        raise RuntimeError(f"Plusieurs menus {root_label!r} sous le même parent : {existing_root}.")
    if existing_root:
        root_menu_id = int(existing_root[0])
        out["menus"]["root"] = {"id": root_menu_id, "status": "found"}
    else:
        loose = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.menu",
                "search",
                args=[[("name", "=", root_label)]],
                kwargs={"limit": 8},
            )
            or []
        )
        if len(loose) == 1:
            root_menu_id = int(loose[0])
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.menu",
                "write",
                args=[[root_menu_id], {"parent_id": parent_domain_val, "sequence": 24}],
            )
            out["menus"]["root"] = {"id": root_menu_id, "status": "moved", "parent_set_to": parent_domain_val}
        elif not loose:
            root_menu_id = int(
                _ek(
                    models,
                    db,
                    uid,
                    pwd,
                    "ir.ui.menu",
                    "create",
                    args=[
                        {
                            "name": root_label,
                            "parent_id": parent_domain_val,
                            "sequence": 24,
                        }
                    ],
                )
            )
            out["menus"]["root"] = {"id": root_menu_id, "status": "created"}
        else:
            raise RuntimeError(
                f"Plusieurs menus nommés {root_label!r} (ids={loose}) : renommez-les dans Odoo ou changez --menu-root."
            )

    def _child_menu(name: str, action_id: int, sequence: int) -> dict[str, Any]:
        found = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.menu",
                "search",
                args=[[("name", "=", name), ("parent_id", "=", root_menu_id)]],
                kwargs={"limit": 2},
            )
            or []
        )
        action_str = f"ir.actions.act_window,{int(action_id)}"
        if len(found) > 1:
            raise RuntimeError(f"Menus doublons {name!r} sous {root_label}: {found}.")
        if found:
            mid = int(found[0])
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.menu",
                "write",
                args=[[mid], {"action": action_str, "sequence": sequence}],
            )
            return {"id": mid, "status": "updated"}
        mid = int(
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.menu",
                "create",
                args=[
                    {
                        "name": name,
                        "parent_id": root_menu_id,
                        "action": action_str,
                        "sequence": sequence,
                    }
                ],
            )
        )
        return {"id": mid, "status": "created"}

    out["menus"]["headers"] = _child_menu("En-têtes de budget", ah_id, 10)
    out["menus"]["lines"] = _child_menu("Lignes de budget", al_id, 20)

    root_mid = (out.get("menus") or {}).get("root") or {}
    rid = root_mid.get("id")
    out["branding"] = ensure_senedoo_financial_budget_toolbox_branding(
        models,
        db,
        uid,
        pwd,
        root_menu_id=int(rid) if rid is not None else None,
    )

    out["ok"] = True
    return out


def run_remove_studio_financial_budget_legacy(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Supprime le petit « app » Studio **Budget Financier** (menus + actions liés dans
    ``studio_customization`` — motifs ``budget_financier%`` et ``budgets_%`` sur action).

    Ne supprime **pas** les enregistrements ``account.report.budget`` / ``.item``.
    """
    dom: list[Any] = [
        ("module", "=", "studio_customization"),
        "|",
        ("name", "ilike", "budget_financier%"),
        "&",
        ("name", "ilike", "budgets_%"),
        ("model", "=", "ir.actions.act_window"),
    ]
    imd = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            args=[dom],
            kwargs={"fields": ["id", "name", "model", "res_id"], "limit": 200},
        )
        or []
    )
    menu_ids: list[int] = []
    action_ids: list[int] = []
    imd_ids: list[int] = []
    for row in imd:
        imd_ids.append(int(row["id"]))
        m = (row.get("model") or "").strip()
        rid = row.get("res_id")
        if not rid:
            continue
        iid = int(rid)
        if m == "ir.ui.menu":
            menu_ids.append(iid)
        elif m == "ir.actions.act_window":
            action_ids.append(iid)

    out: dict[str, Any] = {
        "ir_model_data_ids": imd_ids,
        "menu_ids": menu_ids,
        "action_ids": action_ids,
        "dry_run": dry_run,
    }

    if dry_run or not imd_ids:
        return out

    # Profondeur : supprimer les menus feuilles avant les parents
    if menu_ids:
        parent_by_id: dict[int, int | None] = {}
        for mid in menu_ids:
            rows = (
                _ek(
                    models,
                    db,
                    uid,
                    pwd,
                    "ir.ui.menu",
                    "read",
                    args=[[mid]],
                    kwargs={"fields": ["parent_id"]},
                )
                or []
            )
            if not rows:
                parent_by_id[mid] = None
                continue
            p = rows[0].get("parent_id")
            if isinstance(p, (list, tuple)) and p:
                parent_by_id[mid] = int(p[0])
            else:
                parent_by_id[mid] = None

        menu_id_set = set(menu_ids)

        def _depth(mid: int) -> int:
            d = 0
            cur = parent_by_id.get(mid)
            seen: set[int] = set()
            while cur is not None and cur in menu_id_set and cur not in seen:
                seen.add(cur)
                d += 1
                cur = parent_by_id.get(cur)
            return d

        ordered = sorted(menu_ids, key=_depth, reverse=True)
        for mid in ordered:
            try:
                _ek(models, db, uid, pwd, "ir.ui.menu", "unlink", args=[[mid]])
            except Exception as e:
                out.setdefault("unlink_menu_errors", []).append({"id": mid, "error": str(e)})

    for aid in action_ids:
        try:
            _ek(models, db, uid, pwd, "ir.actions.act_window", "unlink", args=[[aid]])
        except Exception as e:
            out.setdefault("unlink_action_errors", []).append({"id": aid, "error": str(e)})

    for iid in imd_ids:
        try:
            _ek(models, db, uid, pwd, "ir.model.data", "unlink", args=[[iid]])
        except Exception:
            pass

    return out


def cmd_remove_studio_financial_budget(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    confirm = (getattr(args, "confirm", None) or "").strip()
    if confirm != "STUDIO_BUDGET_LEGACY" and not getattr(args, "dry_run", False):
        raise RuntimeError(
            "Confirmation requise : ajoutez --confirm STUDIO_BUDGET_LEGACY "
            "(ou --dry-run pour simuler)."
        )
    res = run_remove_studio_financial_budget_legacy(
        models, db, uid, pwd, dry_run=bool(getattr(args, "dry_run", False))
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


def cmd_provision_financial_budget(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    root = (getattr(args, "menu_root", None) or "").strip() or DEFAULT_MENU_ROOT
    place = "reporting" if getattr(args, "under_reporting", False) else "top"
    res = provision_financial_budget_toolbox(
        models, db, uid, pwd, menu_root=root, placement=place
    )
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    else:
        print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


def cmd_export_items(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    budget_id = int(args.budget_id)
    fg_item = _fg(models, db, uid, pwd, "account.report.budget.item")
    parent_f = _pick_budget_item_parent_field(fg_item)
    amt_f = _pick_amount_field(fg_item)
    if not parent_f or not amt_f:
        raise RuntimeError("Structure account.report.budget.item non reconnue (analyze).")
    fields = ["id", parent_f, amt_f]
    if "account_id" in fg_item:
        fields.append("account_id")
    for opt in ("date", "date_from", "date_to", "x_analytic_account_id", "analytic_account_id"):
        if opt in fg_item:
            fields.append(opt)
    items = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "account.report.budget.item",
            "search_read",
            args=[[(parent_f, "=", budget_id)]],
            kwargs={"fields": fields, "limit": 20000},
        )
        or []
    )
    acc_ids = [int(x["account_id"][0]) for x in items if x.get("account_id")]
    codes_by_id: dict[int, str] = {}
    if acc_ids:
        accs = _ek(
            models,
            db,
            uid,
            pwd,
            "account.account",
            "read",
            args=[list(set(acc_ids))],
            kwargs={"fields": ["id", "code"]},
        )
        codes_by_id = {int(a["id"]): (a.get("code") or "").strip() for a in (accs or [])}

    out_lines = []
    for it in items:
        aid = it.get("account_id")
        acc_id = int(aid[0]) if isinstance(aid, (list, tuple)) else None
        code = codes_by_id.get(acc_id or 0, "")
        out_lines.append(
            {
                "account_code": code,
                "amount": it.get(amt_f),
                "date": it.get("date"),
                "date_from": it.get("date_from"),
                "date_to": it.get("date_to"),
            }
        )
    cols = ["account_code", "amount"]
    if "date" in fg_item:
        cols.append("date")
    if "date_from" in fg_item:
        cols.append("date_from")
    if "date_to" in fg_item:
        cols.append("date_to")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in out_lines:
        w.writerow({k: r.get(k) or "" for k in cols})
    Path(args.out).write_text(buf.getvalue(), encoding="utf-8")
    print(f"Exporté {len(out_lines)} ligne(s) vers {args.out}")


def cmd_list_budgets(models: Any, db: str, uid: int, pwd: str, args: argparse.Namespace) -> None:
    lim = max(1, min(500, int(args.limit or 200)))
    fg_b = _fg(models, db, uid, pwd, "account.report.budget")
    rows = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "account.report.budget",
            "search_read",
            args=[[]],
            kwargs={
                "fields": _budget_header_read_fields(fg_b),
                "order": "id desc",
                "limit": lim,
            },
        )
        or []
    )
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
        return
    for r in rows:
        print(f"id={r.get('id')}\t{r.get('name')!r}\t{r.get('company_id')}\t{r.get('date_from')} → {r.get('date_to')}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Budgets financiers account.report.budget (CLI).")
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)

    sub = p.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("analyze", help="Champs, champs manuels, menus, option budgets filtrés.")
    pa.add_argument("--budget-q", default="", help="Filtre ilike sur le nom du budget.")
    pa.add_argument("--json", action="store_true")
    pa.set_defaults(func=cmd_analyze)

    pe = sub.add_parser("ensure-analytic-fields", help="Crée x_analytic_account_id (toolbox) si absent.")
    pe.add_argument("--json", action="store_true")
    pe.set_defaults(func=cmd_ensure_analytic)

    pp = sub.add_parser(
        "provision-financial-budget",
        help="Champs analytiques + menus Reporting « Budget Senedoo » (budgets financiers).",
    )
    pp.add_argument(
        "--menu-root",
        dest="menu_root",
        default=DEFAULT_MENU_ROOT,
        help=f"Libellé du menu racine (défaut : {DEFAULT_MENU_ROOT!r}).",
    )
    pp.add_argument(
        "--under-reporting",
        dest="under_reporting",
        action="store_true",
        help="Placer le menu sous Comptabilité > Reporting au lieu de la barre principale.",
    )
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_provision_financial_budget)

    prm = sub.add_parser(
        "remove-studio-financial-budget",
        help="Supprime l'ancien menu Studio « Budget Financier » (sans toucher aux données budget).",
    )
    prm.add_argument("--dry-run", dest="dry_run", action="store_true")
    prm.add_argument(
        "--confirm",
        default="",
        help="Saisir exactement STUDIO_BUDGET_LEGACY pour exécuter la suppression.",
    )
    prm.add_argument("--json", action="store_true")
    prm.set_defaults(func=cmd_remove_studio_financial_budget)

    pl = sub.add_parser("list-budgets", help="Liste les budgets financiers.")
    pl.add_argument("--limit", type=int, default=200)
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_list_budgets)

    pc = sub.add_parser("create-budget", help="Crée un account.report.budget.")
    pc.add_argument("--name", required=True)
    pc.add_argument("--date-from", dest="date_from", default="")
    pc.add_argument("--date-to", dest="date_to", default="")
    pc.add_argument("--company-id", dest="company_id", type=int, default=None)
    pc.add_argument("--analytic-id", dest="analytic_id", type=int, default=None)
    pc.add_argument("--analytic-name", dest="analytic_name", default=None)
    pc.add_argument("--json", action="store_true")
    pc.set_defaults(func=cmd_create_budget)

    pi = sub.add_parser("import-items", help="Importe des lignes budget depuis un CSV.")
    pi.add_argument("--budget-id", dest="budget_id", type=int, required=True)
    pi.add_argument("--csv", dest="csv", required=True)
    pi.add_argument("--replace-all", action="store_true", help="Supprime toutes les lignes existantes du budget.")
    pi.add_argument(
        "--date-from",
        dest="date_from",
        default="",
        help="Si les lignes ont un champ date unique (Odoo 18.3+), valeur par défaut si le CSV n'a pas de colonne date.",
    )
    pi.add_argument("--date-to", dest="date_to", default="")
    pi.add_argument(
        "--header-analytic-id",
        dest="header_analytic_id",
        type=int,
        default=None,
        help="Compte analytique commun à toutes les lignes créées (prioritaire sur l'en-tête budget).",
    )
    pi.add_argument(
        "--header-analytic-name",
        dest="header_analytic_name",
        default=None,
        help="Idem par nom (recherche ilike) ; une seule valeur pour tout l'import.",
    )
    pi.add_argument(
        "--no-inherit-header-analytic",
        dest="no_inherit_header_analytic",
        action="store_true",
        help="Ne pas remplir l'analytique sur les lignes (par défaut : copie de l'en-tête ou de --header-analytic-*).",
    )
    pi.add_argument("--batch-size", dest="batch_size", type=int, default=80)
    pi.add_argument("--json", action="store_true")
    pi.set_defaults(func=cmd_import_items)

    ps = sub.add_parser(
        "sync-analytic-to-lines",
        help="Recopie l'analytique de l'en-tête budget sur les lignes sans analytique.",
    )
    ps.add_argument("--budget-id", dest="budget_id", type=int, default=None)
    ps.add_argument("--budget-name", dest="budget_name", default=None)
    ps.add_argument(
        "--force-all",
        dest="force_all",
        action="store_true",
        help="Réécrire l'analytique sur toutes les lignes du budget (pas seulement les vides).",
    )
    ps.add_argument("--dry-run", dest="dry_run", action="store_true")
    ps.add_argument("--chunk", type=int, default=200)
    ps.add_argument("--json", action="store_true")
    ps.set_defaults(func=cmd_sync_analytic_to_lines)

    pset = sub.add_parser(
        "set-budget-analytic",
        help="Pose le compte analytique sur l'en-tête du budget financier.",
    )
    pset.add_argument("--budget-id", dest="budget_id", type=int, default=None)
    pset.add_argument("--budget-name", dest="budget_name", default=None)
    pset.add_argument("--analytic-id", dest="analytic_id", type=int, default=None)
    pset.add_argument("--analytic-name", dest="analytic_name", default=None)
    pset.add_argument(
        "--propagate-to-lines",
        dest="propagate_to_lines",
        action="store_true",
        help="Après l'en-tête, même recopie que « sync-analytic-to-lines ».",
    )
    pset.add_argument(
        "--propagate-force-all",
        dest="propagate_force_all",
        action="store_true",
        help="Avec --propagate-to-lines : forcer la réécriture sur toutes les lignes.",
    )
    pset.add_argument("--chunk", type=int, default=200)
    pset.add_argument("--json", action="store_true")
    pset.set_defaults(func=cmd_set_budget_analytic)

    px = sub.add_parser("export-items", help="Exporte les lignes d'un budget en CSV.")
    px.add_argument("--budget-id", dest="budget_id", type=int, required=True)
    px.add_argument("--out", required=True)
    px.set_defaults(func=cmd_export_items)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    uid, models, db, pwd = _connect_cli(args)
    func = args.func
    del args.func  # type: ignore
    try:
        func(models, db, uid, pwd, args)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
