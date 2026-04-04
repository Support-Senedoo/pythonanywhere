#!/usr/bin/env python3
"""
Transforme une copie de balance (account.report, 4 colonnes) en 6 colonnes :
  débit initial, crédit initial, débit période, crédit période, débit final, crédit final.

Voir docstring du module (version précédente) pour les hypothèses et limites.
"""
from __future__ import annotations

import re
from typing import Any

from personalize_syscohada_detail import execute_kw

_SN_OPEN_DEB = "sn_open_deb"
_SN_OPEN_CRE = "sn_open_cred"
_SN_END_DEB = "sn_end_deb"
_SN_END_CRE = "sn_end_cre"


def _split_sum_subformula(subformula: str | bool | None) -> tuple[str, str]:
    s = (subformula or "sum") if subformula not in (False, None) else "sum"
    s = str(s).strip()
    if s == "sum":
        return "sum_if_pos", "sum_if_neg"
    if s in ("sum_if_pos", "sum_if_neg"):
        raise ValueError(
            f"Subformule déjà partagée ({s!r}) : rapport non reconnu comme balance 4 colonnes standard."
        )
    raise ValueError(
        f"Subformule non prise en charge pour le débit/crédit initial ou final : {s!r}. "
        "Contactez Senedoo pour une adaptation manuelle."
    )


def _replace_agg_labels(text: str, old_lbl: str, deb_lbl: str, cre_lbl: str) -> str:
    if not text or old_lbl not in text:
        return text
    pat = re.compile(rf"(\b[a-zA-Z][a-zA-Z0-9_]*)\.{re.escape(old_lbl)}\b")

    def repl(m: re.Match[str]) -> str:
        code = m.group(1)
        return f"({code}.{deb_lbl} + {code}.{cre_lbl})"

    return pat.sub(repl, text)


def personalize_balance_six_columns(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> None:
    rep_rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["column_ids"]},
    )
    if not rep_rows:
        raise ValueError(f"Rapport id={report_id} introuvable.")
    col_ids = rep_rows[0].get("column_ids") or []
    if len(col_ids) != 4:
        raise ValueError(
            f"Ce rapport a {len(col_ids)} colonne(s), pas 4. "
            "Choisissez une balance standard (solde initial, débit, crédit, solde final)."
        )
    cols = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.column",
        "read",
        [col_ids],
        {"fields": ["name", "expression_label", "sequence", "figure_type", "sortable", "blank_if_zero"]},
    )
    cols.sort(key=lambda c: (c.get("sequence") or 0, c.get("id") or 0))
    lbl_open = cols[0]["expression_label"]
    lbl_deb = cols[1]["expression_label"]
    lbl_cred = cols[2]["expression_label"]
    lbl_end = cols[3]["expression_label"]
    if not all((lbl_open, lbl_deb, lbl_cred, lbl_end)):
        raise ValueError("Colonne sans expression_label : rapport invalide.")

    line_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("report_id", "=", report_id)]],
    )
    expr_read_fields = [
        "id",
        "report_line_id",
        "label",
        "engine",
        "formula",
        "subformula",
        "date_scope",
        "figure_type",
        "blank_if_zero",
        "green_on_positive",
    ]

    all_expr_ids: list[int] = []
    for lid in line_ids:
        row = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [[lid]],
            {"fields": ["expression_ids"]},
        )[0]
        all_expr_ids.extend(row.get("expression_ids") or [])

    if all_expr_ids:
        all_exprs = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "read",
            [all_expr_ids],
            {"fields": expr_read_fields},
        )
    else:
        all_exprs = []

    for e in all_exprs:
        if e.get("engine") != "aggregation":
            continue
        nf = _replace_agg_labels(str(e.get("formula") or ""), lbl_open, _SN_OPEN_DEB, _SN_OPEN_CRE)
        nf = _replace_agg_labels(nf, lbl_end, _SN_END_DEB, _SN_END_CRE)
        nsf = e.get("subformula") or ""
        nsf = _replace_agg_labels(str(nsf), lbl_open, _SN_OPEN_DEB, _SN_OPEN_CRE)
        nsf = _replace_agg_labels(nsf, lbl_end, _SN_END_DEB, _SN_END_CRE)
        old_f, old_sf = e.get("formula"), e.get("subformula") or ""
        if nf != old_f or nsf != old_sf:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.expression",
                "write",
                [[e["id"]], {"formula": nf, "subformula": nsf or False}],
            )

    for lid in line_ids:
        ex_ids = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [[lid]],
            {"fields": ["expression_ids"]},
        )[0].get("expression_ids") or []
        if not ex_ids:
            continue
        exprs = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "read",
            [ex_ids],
            {"fields": expr_read_fields},
        )
        for e in exprs:
            eng = e.get("engine")
            if eng not in ("domain", "account_codes"):
                continue
            lab = e.get("label")
            if lab == lbl_open:
                sd, sc = _split_sum_subformula(e.get("subformula"))
                execute_kw(models, db, uid, password, "account.report.expression", "unlink", [[e["id"]]])
                base = {
                    "report_line_id": lid,
                    "engine": eng,
                    "formula": e["formula"],
                    "date_scope": e.get("date_scope") or "strict_range",
                    "figure_type": e.get("figure_type"),
                    "blank_if_zero": e.get("blank_if_zero"),
                    "green_on_positive": e.get("green_on_positive", True),
                }
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report.expression",
                    "create",
                    [{**base, "label": _SN_OPEN_DEB, "subformula": sd}],
                )
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report.expression",
                    "create",
                    [{**base, "label": _SN_OPEN_CRE, "subformula": sc}],
                )
            elif lab == lbl_end:
                sd, sc = _split_sum_subformula(e.get("subformula"))
                execute_kw(models, db, uid, password, "account.report.expression", "unlink", [[e["id"]]])
                base = {
                    "report_line_id": lid,
                    "engine": eng,
                    "formula": e["formula"],
                    "date_scope": e.get("date_scope") or "strict_range",
                    "figure_type": e.get("figure_type"),
                    "blank_if_zero": e.get("blank_if_zero"),
                    "green_on_positive": e.get("green_on_positive", True),
                }
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report.expression",
                    "create",
                    [{**base, "label": _SN_END_DEB, "subformula": sd}],
                )
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report.expression",
                    "create",
                    [{**base, "label": _SN_END_CRE, "subformula": sc}],
                )

    execute_kw(models, db, uid, password, "account.report.column", "unlink", [col_ids])

    fig_open = cols[0].get("figure_type") or "monetary"

    def _norm_col_name(raw: Any, fr: str, en: str) -> Any:
        if isinstance(raw, dict) and raw:
            return raw
        if isinstance(raw, str) and raw.strip():
            return raw
        return {"fr_FR": fr, "en_US": en}

    def _c(seq: int, name: Any, expr_lbl: str, fig: str) -> dict[str, Any]:
        return {
            "report_id": report_id,
            "sequence": seq,
            "name": name,
            "expression_label": expr_lbl,
            "figure_type": fig,
            "sortable": False,
            "blank_if_zero": False,
        }

    to_create = [
        _c(10, {"fr_FR": "Débit initial", "en_US": "Opening debit"}, _SN_OPEN_DEB, fig_open),
        _c(20, {"fr_FR": "Crédit initial", "en_US": "Opening credit"}, _SN_OPEN_CRE, fig_open),
        _c(
            30,
            _norm_col_name(cols[1].get("name"), "Débit", "Debit"),
            lbl_deb,
            cols[1].get("figure_type") or "monetary",
        ),
        _c(
            40,
            _norm_col_name(cols[2].get("name"), "Crédit", "Credit"),
            lbl_cred,
            cols[2].get("figure_type") or "monetary",
        ),
        _c(50, {"fr_FR": "Débit final", "en_US": "Closing debit"}, _SN_END_DEB, fig_open),
        _c(60, {"fr_FR": "Crédit final", "en_US": "Closing credit"}, _SN_END_CRE, fig_open),
    ]
    for cv in to_create:
        execute_kw(models, db, uid, password, "account.report.column", "create", [cv])
