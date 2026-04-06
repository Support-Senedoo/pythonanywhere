#!/usr/bin/env python3
"""
Réécrit les formules **moteur aggregation** (Odoo « Aggregate Other Formulas ») des
expressions du **compte de résultat** pour que la colonne **%** utilise le **numérateur
de la colonne analytique** (libellé d’expression de cette colonne) au lieu du total
période, tout en gardant le **dénominateur budget** inchangé.

Réf. doc Odoo (v17+ valable pour la syntaxe des formules ; v19 utilise le même modèle
``account.report.expression`` avec ``engine == 'aggregation'``) :
  « To refer to an expression, type its parent line's code followed by a period and the
  expression's label (ex. code.label). »

**Prérequis** : une **copie** du P&L (comme pour les autres scripts toolbox), pas le rapport
standard verrouillé.

**Odoo 19** : testé conceptuellement contre ``addons/account/models/account_report.py`` (branche
19.0) — pas de changement de nom de moteur ``aggregation`` pour ces expressions.

Usage (après avoir listé les colonnes pour connaître les ``expression_label``) :

  python personalize_pl_percent_analytic_budget.py --report-id 42 --list-columns

  python personalize_pl_percent_analytic_budget.py --report-id 42 \\
    --percent-label pct_budget \\
    --numerator-from balance_total \\
    --numerator-to balance_analytic

  python personalize_pl_percent_analytic_budget.py ... --dry-run

Variables : ODOO_* ou .env (comme ``personalize_syscohada_detail.py``).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from personalize_syscohada_detail import connect, execute_kw


def _replace_label_in_aggregation_formula(
    formula: str | bool | None,
    from_label: str,
    to_label: str,
) -> str:
    """Remplace ``.from_label`` par ``.to_label`` (jeton complet après le point)."""
    if not formula or not isinstance(formula, str):
        return ""
    if from_label == to_label:
        return formula
    # Évite de couper un libellé plus long (ex. ne pas matcher .bal dans .balance si from est bal)
    pat = re.compile(r"\." + re.escape(from_label) + r"(?!\w)")
    return pat.sub("." + to_label, formula)


def list_columns(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> list[dict[str, Any]]:
    rep = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["column_ids", "name"]},
    )
    if not rep:
        raise ValueError(f"account.report id={report_id} introuvable.")
    cids = rep[0].get("column_ids") or []
    if not cids:
        return []
    cols = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.column",
        "read",
        [cids],
        {"fields": ["name", "sequence", "expression_label", "figure_type", "sortable"]},
    )
    return sorted(cols, key=lambda c: (c.get("sequence") or 0, c.get("id") or 0))


def all_line_ids_for_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> list[int]:
    return execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("report_id", "=", report_id)]],
    )


def rewrite_percent_expressions(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    *,
    percent_label: str,
    numerator_from: str,
    numerator_to: str,
    dry_run: bool,
) -> tuple[int, int, list[str]]:
    """
    Parcourt toutes les expressions des lignes du rapport dont ``label == percent_label``
    et ``engine == 'aggregation'``, et remplace le jeton de numérateur dans ``formula``.

    Retourne (nombre d'expressions candidates, nombre d'écritures, messages).
    """
    line_ids = all_line_ids_for_report(models, db, uid, password, report_id)
    if not line_ids:
        return 0, 0, ["Aucune ligne de rapport."]

    messages: list[str] = []
    expr_read_fields = ["label", "engine", "formula", "subformula", "report_line_id"]
    candidates = 0
    writes: list[tuple[int, dict[str, Any]]] = []

    chunk = 400
    for i in range(0, len(line_ids), chunk):
        batch = line_ids[i : i + chunk]
        lines = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [batch],
            {"fields": ["expression_ids"]},
        )
        all_eids: list[int] = []
        for ln in lines:
            all_eids.extend(ln.get("expression_ids") or [])

        if not all_eids:
            continue
        exprs = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "read",
            [all_eids],
            {"fields": expr_read_fields},
        )
        for ex in exprs:
            if (ex.get("label") or "") != percent_label:
                continue
            if ex.get("engine") != "aggregation":
                continue
            candidates += 1
            old_f = ex.get("formula") or ""
            new_f = _replace_label_in_aggregation_formula(
                old_f, numerator_from, numerator_to
            )
            if new_f == old_f:
                continue
            writes.append((int(ex["id"]), {"formula": new_f}))
            if len(messages) < 12:
                lid = ex.get("report_line_id")
                lid_s = lid[0] if isinstance(lid, (list, tuple)) else lid
                messages.append(
                    f"expr id={ex['id']} line_id={lid_s} : "
                    f"{old_f!r} -> {new_f!r}"
                )

    if dry_run:
        return candidates, len(writes), messages + [f"[dry-run] {len(writes)} écriture(s) à appliquer."]

    n_ok = 0
    for eid, vals in writes:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "write",
            [[eid], vals],
        )
        n_ok += 1

    return candidates, n_ok, messages + [f"OK — {n_ok} expression(s) mise(s) à jour."]


def _column_name_lower(c: dict[str, Any]) -> str:
    n = c.get("name")
    if isinstance(n, dict):
        return " ".join(str(v) for v in n.values() if v).lower()
    return str(n or "").lower()


def _pick_percent_expression_label(cols: list[dict[str, Any]]) -> str | None:
    """Libellé d’expression de la colonne % (figure_type percentage ou libellé type pct_*)."""
    for c in cols:
        if (c.get("figure_type") or "").lower() == "percentage":
            el = (c.get("expression_label") or "").strip()
            if el:
                return el
    for c in cols:
        el = (c.get("expression_label") or "").strip()
        if el and "pct" in el.lower():
            return el
    return None


def _monetary_columns_except_budget(
    cols: list[dict[str, Any]],
    percent_label: str,
) -> list[dict[str, Any]]:
    """Colonnes montants (hors % et hors budget), triées par séquence."""
    sorted_cols = sorted(cols, key=lambda c: (c.get("sequence") or 0, c.get("id") or 0))
    out: list[dict[str, Any]] = []
    for c in sorted_cols:
        el = (c.get("expression_label") or "").strip()
        if not el or el == percent_label:
            continue
        if "budget" in el.lower():
            continue
        ft = (c.get("figure_type") or "").lower()
        if ft == "percentage":
            continue
        if ft and ft not in ("float", "monetary", "integer", "none", ""):
            continue
        out.append(c)
    return out


def infer_numerator_labels_from_columns(
    cols: list[dict[str, Any]],
    percent_label: str,
) -> tuple[str, str] | None:
    """
    Devine (numerator_from, numerator_to) : total période → colonne analytique.
    Retourne None si impossible.
    """
    monetary = _monetary_columns_except_budget(cols, percent_label)
    if len(monetary) < 2:
        return None

    def el(c: dict[str, Any]) -> str:
        return (c.get("expression_label") or "").strip()

    analytic_c = None
    total_c = None
    for c in monetary:
        e = el(c).lower()
        n = _column_name_lower(c)
        if "analytic" in e or "analytique" in n:
            analytic_c = c
        if total_c is None and (
            "total" in n
            or "période" in n
            or "periode" in n
            or e in ("balance_total", "total")
        ):
            if "analytic" not in e:
                total_c = c

    if analytic_c and total_c and el(analytic_c) != el(total_c):
        return (el(total_c), el(analytic_c))

    if analytic_c:
        for c in monetary:
            if el(c) != el(analytic_c):
                return (el(c), el(analytic_c))

    # Dernier recours : les deux premières colonnes montant (souvent total puis analytique)
    return (el(monetary[0]), el(monetary[1]))


# Libellés fréquents dans les formules Odoo « aggregation » (réalisé total → réalisé analytique)
_COMMON_NUMERATOR_PAIRS: tuple[tuple[str, str], ...] = (
    ("balance_total", "balance_analytic"),
    ("balance_total", "analytic_balance"),
    ("total", "analytic"),
    ("balance", "balance_analytic"),
    ("balance", "analytic"),
)


def apply_percent_analytic_numerator(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> dict[str, Any]:
    """
    Après copie du P&L : réécrit les expressions % (moteur aggregation) pour que le numérateur
    soit la colonne analytique, pas le total de période.

    Retourne un dict avec ok, writes, labels, messages, reason (si échec).
    """
    cols = list_columns(models, db, uid, password, report_id)
    pct = _pick_percent_expression_label(cols)
    if not pct:
        return {
            "ok": False,
            "writes": 0,
            "percent_label": None,
            "numerator_from": None,
            "numerator_to": None,
            "messages": [],
            "reason": "no_percent_column",
        }

    for from_l, to_l in _COMMON_NUMERATOR_PAIRS:
        if from_l == to_l:
            continue
        cand, nwr, msgs = rewrite_percent_expressions(
            models,
            db,
            uid,
            password,
            report_id,
            percent_label=pct,
            numerator_from=from_l,
            numerator_to=to_l,
            dry_run=True,
        )
        if nwr > 0:
            _cand2, nwr2, msgs2 = rewrite_percent_expressions(
                models,
                db,
                uid,
                password,
                report_id,
                percent_label=pct,
                numerator_from=from_l,
                numerator_to=to_l,
                dry_run=False,
            )
            return {
                "ok": True,
                "writes": nwr2,
                "percent_label": pct,
                "numerator_from": from_l,
                "numerator_to": to_l,
                "messages": msgs2,
                "reason": None,
            }

    inferred = infer_numerator_labels_from_columns(cols, pct)
    if not inferred:
        return {
            "ok": False,
            "writes": 0,
            "percent_label": pct,
            "numerator_from": None,
            "numerator_to": None,
            "messages": [],
            "reason": "could_not_infer_columns",
        }

    from_l, to_l = inferred
    if from_l == to_l:
        return {
            "ok": False,
            "writes": 0,
            "percent_label": pct,
            "numerator_from": from_l,
            "numerator_to": to_l,
            "messages": [],
            "reason": "same_inferred_labels",
        }

    cand, nwr, msgs = rewrite_percent_expressions(
        models,
        db,
        uid,
        password,
        report_id,
        percent_label=pct,
        numerator_from=from_l,
        numerator_to=to_l,
        dry_run=True,
    )
    if nwr == 0:
        # Essai inverse (ordre colonnes atypique)
        cand2, nwr2, msgs2 = rewrite_percent_expressions(
            models,
            db,
            uid,
            password,
            report_id,
            percent_label=pct,
            numerator_from=to_l,
            numerator_to=from_l,
            dry_run=True,
        )
        if nwr2 > 0:
            from_l, to_l = to_l, from_l
            nwr, msgs = nwr2, msgs2
        else:
            return {
                "ok": False,
                "writes": 0,
                "percent_label": pct,
                "numerator_from": from_l,
                "numerator_to": to_l,
                "messages": msgs,
                "reason": "no_aggregation_formulas_to_change",
                "candidates_seen": cand,
            }

    _cand3, nwr3, msgs3 = rewrite_percent_expressions(
        models,
        db,
        uid,
        password,
        report_id,
        percent_label=pct,
        numerator_from=from_l,
        numerator_to=to_l,
        dry_run=False,
    )
    return {
        "ok": True,
        "writes": nwr3,
        "percent_label": pct,
        "numerator_from": from_l,
        "numerator_to": to_l,
        "messages": msgs3,
        "reason": None,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="P&L : % budget calculé sur la colonne analytique (formules aggregation, ex. Odoo 19)."
    )
    p.add_argument("--report-id", type=int, required=True)
    p.add_argument(
        "--list-columns",
        action="store_true",
        help="Affiche les colonnes (expression_label, figure_type) et quitte.",
    )
    p.add_argument(
        "--percent-label",
        type=str,
        default="",
        help="Label d'expression de la colonne % (identique au champ expression_label de la colonne).",
    )
    p.add_argument(
        "--numerator-from",
        type=str,
        default="",
        help="Label d'expression actuellement utilisé comme réalisé dans le % (souvent la colonne total période).",
    )
    p.add_argument(
        "--numerator-to",
        type=str,
        default="",
        help="Label d'expression de la colonne analytique à utiliser comme numérateur du %.",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    url = (os.environ.get("ODOO_URL") or "").strip().rstrip("/")
    db = (os.environ.get("ODOO_DB") or "").strip()
    user = (os.environ.get("ODOO_USER") or "").strip()
    password = (os.environ.get("ODOO_PASSWORD") or "").strip()
    if not url or not db or not user:
        print("Variables ODOO_URL, ODOO_DB, ODOO_USER requises (et ODOO_PASSWORD).", file=sys.stderr)
        sys.exit(1)

    models, uid = connect(url, db, user, password)

    if args.list_columns:
        cols = list_columns(models, db, uid, password, args.report_id)
        print(f"Rapport id={args.report_id} — {len(cols)} colonne(s).\n")
        for c in cols:
            el = c.get("expression_label") or "—"
            ft = c.get("figure_type") or "—"
            name = c.get("name")
            if isinstance(name, dict):
                name = name.get("fr_FR") or name.get("en_US") or str(name)
            print(f"  seq={c.get('sequence')}  expression_label={el!r}  figure_type={ft!r}  name={name!r}")
        sys.exit(0)

    if not args.percent_label or not args.numerator_from or not args.numerator_to:
        print(
            "Indiquez --percent-label, --numerator-from et --numerator-to "
            "(ou utilisez --list-columns).",
            file=sys.stderr,
        )
        sys.exit(1)

    cand, nwr, msgs = rewrite_percent_expressions(
        models,
        db,
        uid,
        password,
        args.report_id,
        percent_label=args.percent_label.strip(),
        numerator_from=args.numerator_from.strip(),
        numerator_to=args.numerator_to.strip(),
        dry_run=bool(args.dry_run),
    )
    print(f"Expressions % (label={args.percent_label!r}, moteur aggregation) : {cand} vue(s).")
    for m in msgs:
        print(m)
    if cand == 0:
        print(
            "Aucune expression aggregation avec ce label — vérifiez --percent-label "
            "(voir --list-columns) ou que le % n’est pas sur un autre moteur.",
            file=sys.stderr,
        )
        sys.exit(1)
    if nwr == 0 and not args.dry_run:
        print(
            "Aucune formule modifiée (déjà à jour ou libellés introuvables dans les formules).",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
