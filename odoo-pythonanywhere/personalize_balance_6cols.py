#!/usr/bin/env python3
"""
Transforme une copie de balance (account.report) en 6 colonnes :
  débit initial, crédit initial, débit période, crédit période, débit final, crédit final.

**Interface web :** le bouton staff « copie + 6 colonnes » a été **retiré** ; la toolbox
crée désormais **Balance OHADA** via ``create_toolbox_balance_ohada`` (page staff).
Ce module reste utilisable en **script** pour des cas très spécifiques ; en général
préférez l’API / XML pour un rapport neuf fiable.

Sources supportées (si la base correspond exactement au schéma attendu) :
  - 4 colonnes (solde initial, débit, crédit, solde final) ;
  - 2 colonnes (débit et crédit période uniquement) : expressions dupliquées avec
    ``to_beginning_of_period`` / ``from_beginning``.

**Exclu — balance d’essai Enterprise (handler trial balance)** : si le rapport utilise
``account.trial.balance.report.handler``, la personnalisation est **refusée``. Le post-processeur
``_custom_line_postprocessor`` n’indexe les ajustements « unaffected earnings » que sur les libellés
``debit`` / ``credit`` / ``balance`` pour les blocs initial/période ; les libellés ``sn_*`` de la
toolbox provoquent un ``KeyError`` (ex. ``sn_open_deb``) — ce n’est pas corrigeable par détachement
racine. Utiliser le Grand livre / une balance générale configurée en Studio (voir page staff,
``examples/balance_generale_6_col_studio.example.xml``).

Pour les autres rapports : détachement ``root_report_id`` / ``section_main_report_ids`` en début de
traitement ; duplication autonome ``attach_to_root=False`` côté Flask.
"""
from __future__ import annotations

import re
from typing import Any

from personalize_syscohada_detail import execute_kw

_SN_OPEN_DEB = "sn_open_deb"
_SN_OPEN_CRE = "sn_open_cred"
_SN_END_DEB = "sn_end_deb"
_SN_END_CRE = "sn_end_cre"

# Handler Enterprise : incompatible avec des libellés de colonnes arbitraires (sn_*).
_ENTERPRISE_TRIAL_BALANCE_HANDLER = "account.trial.balance.report.handler"

# Champs account.report recalculés depuis root_report_id (addons/account/models/account_report.py).
_ROOT_MIRROR_OPTION_FIELDS: tuple[str, ...] = (
    "only_tax_exigible",
    "allow_foreign_vat",
    "default_opening_date_filter",
    "currency_translation",
    "filter_multi_company",
    "filter_date_range",
    "filter_show_draft",
    "filter_unreconciled",
    "filter_unfold_all",
    "filter_hide_0_lines",
    "filter_period_comparison",
    "filter_growth_comparison",
    "filter_journals",
    "filter_analytic",
    "filter_hierarchy",
    "filter_account_type",
    "filter_partner",
    "filter_aml_ir_filters",
    "filter_budgets",
)


def _account_report_field_names(models: Any, db: str, uid: int, password: str) -> set[str]:
    fg = execute_kw(models, db, uid, password, "account.report", "fields_get", [], {})
    return set(fg.keys())


def _effective_custom_handler_model_name(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    names: set[str],
) -> str | None:
    """Handler du rapport ou, si variante sans handler propre, celui de la racine."""
    fields: list[str] = []
    if "custom_handler_model_name" in names:
        fields.append("custom_handler_model_name")
    if "root_report_id" in names:
        fields.append("root_report_id")
    if not fields:
        return None
    row = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": fields},
    )[0]
    h = row.get("custom_handler_model_name")
    if h:
        return str(h)
    root = row.get("root_report_id")
    if isinstance(root, (list, tuple)) and root and root[0] and "custom_handler_model_name" in names:
        try:
            root_id = int(root[0])
        except (TypeError, ValueError):
            return None
        r2 = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "read",
            [[root_id]],
            {"fields": ["custom_handler_model_name"]},
        )[0]
        h2 = r2.get("custom_handler_model_name")
        return str(h2) if h2 else None
    return None


def _refuses_enterprise_trial_balance_handler(handler_name: str | None) -> bool:
    if not handler_name:
        return False
    return handler_name == _ENTERPRISE_TRIAL_BALANCE_HANDLER


def _standalone_account_report_write_vals(names: set[str]) -> dict[str, Any]:
    """Coupe variante + lien « Section de » (Many2many) pour un rapport autonome."""
    vals: dict[str, Any] = {"root_report_id": False}
    if "section_main_report_ids" in names:
        vals["section_main_report_ids"] = [(5, 0, 0)]
    return vals


def _detach_trial_balance_variant_after_six_columns(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> dict[str, Any]:
    """
    Vide ``root_report_id`` et ``section_main_report_ids`` (si présents), puis réécrit les options
    depuis la racine lorsqu’il y avait une variante. Sans condition sur le handler. Si la racine est
    déjà vide mais le rapport est encore « section de » un composite, supprime ce lien seul.
    Appelé en **début** de ``personalize_balance_six_columns`` (avant les colonnes ``sn_*``).
    """
    names = _account_report_field_names(models, db, uid, password)
    if "root_report_id" not in names:
        return {"detached_from_root": False, "detach_note": "champ root_report_id absent"}
    row = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["root_report_id", "section_main_report_ids"]},
    )[0]
    root = row.get("root_report_id")
    root_id: int | None = None
    if isinstance(root, (list, tuple)) and root and root[0]:
        try:
            root_id = int(root[0])
        except (TypeError, ValueError):
            root_id = None
    section_ids = row.get("section_main_report_ids") or []
    if root_id is None:
        if section_ids and "section_main_report_ids" in names:
            try:
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report",
                    "write",
                    [[report_id], _standalone_account_report_write_vals(names)],
                )
                return {
                    "detached_from_root": False,
                    "detach_note": "lien « Section de » supprimé (root déjà vide)",
                }
            except Exception as e:
                return {"detached_from_root": False, "detach_error": str(e)}
        return {"detached_from_root": False, "detach_note": "déjà autonome (sans root_report_id)"}
    option_fields = [f for f in _ROOT_MIRROR_OPTION_FIELDS if f in names]
    snap_fields = list(option_fields)
    for extra in ("availability_condition", "country_id"):
        if extra in names and extra not in snap_fields:
            snap_fields.append(extra)
    root_snap = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[root_id]],
        {"fields": snap_fields},
    )[0]
    vals = {k: root_snap[k] for k in snap_fields if k in root_snap}
    standalone = _standalone_account_report_write_vals(names)
    merged = {**standalone, **vals}
    try:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[report_id], merged],
        )
    except Exception as e:
        return {"detached_from_root": False, "detach_error": str(e)}
    return {"detached_from_root": True}


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


def _clone_domainish_expr(
    e: dict[str, Any],
    report_line_id: int,
    label: str,
    date_scope: str,
) -> dict[str, Any]:
    """Duplique une expression domain / account_codes avec un autre date_scope."""
    sf = e.get("subformula")
    if sf in (False, None, ""):
        sf = "sum"
    return {
        "report_line_id": report_line_id,
        "label": label,
        "engine": e["engine"],
        "formula": e["formula"],
        "subformula": sf,
        "date_scope": date_scope,
        "figure_type": e.get("figure_type"),
        "blank_if_zero": e.get("blank_if_zero"),
        "green_on_positive": e.get("green_on_positive", True),
    }


def _inject_opening_closing_from_two_period_columns(
    models: Any,
    db: str,
    uid: int,
    password: str,
    line_ids: list[int],
    lbl_deb: str,
    lbl_cred: str,
    expr_read_fields: list[str],
) -> None:
    """Pour une balance à 2 colonnes (débit / crédit période), crée 4 expressions par ligne feuille."""
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
        labels_present = {e.get("label") for e in exprs}
        if _SN_OPEN_DEB in labels_present:
            continue

        def _pick(lab: str) -> dict[str, Any] | None:
            for e in exprs:
                if e.get("label") != lab:
                    continue
                if e.get("engine") not in ("domain", "account_codes"):
                    continue
                return e
            return None

        ed = _pick(lbl_deb)
        ec = _pick(lbl_cred)
        if not ed and not ec:
            continue
        if not ed or not ec:
            raise ValueError(
                f"Ligne comptable id={lid} : il faut deux expressions moteur « domain » ou "
                f"« account_codes » avec les libellés de colonnes {lbl_deb!r} et {lbl_cred!r}. "
                "Une seule est présente : rapport partiellement configuré ou ligne de regroupement "
                "à ignorer — en cas de doute, dupliquez d’abord le rapport ou utilisez une balance "
                "4 colonnes si Odoo en propose une."
            )
        for payload in (
            _clone_domainish_expr(ed, lid, _SN_OPEN_DEB, "to_beginning_of_period"),
            _clone_domainish_expr(ec, lid, _SN_OPEN_CRE, "to_beginning_of_period"),
            _clone_domainish_expr(ed, lid, _SN_END_DEB, "from_beginning"),
            _clone_domainish_expr(ec, lid, _SN_END_CRE, "from_beginning"),
        ):
            execute_kw(models, db, uid, password, "account.report.expression", "create", [payload])


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
) -> dict[str, Any]:
    """Retourne entre autres ``detached_from_root`` / ``detach_error`` après détachement racine éventuel."""
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
    names_f = _account_report_field_names(models, db, uid, password)
    eff_handler = _effective_custom_handler_model_name(models, db, uid, password, report_id, names_f)
    if _refuses_enterprise_trial_balance_handler(eff_handler):
        raise ValueError(
            "Cette balance utilise le handler Enterprise « balance d’essai » "
            f"({_ENTERPRISE_TRIAL_BALANCE_HANDLER}). La toolbox ne peut pas la passer en 6 colonnes : "
            "Odoo lèverait KeyError: sn_open_deb (ou équivalent) dans le post-processeur unaffected earnings, "
            "qui ne gère que les libellés debit / credit / balance pour les colonnes initiales/période. "
            "Créez une balance 6 colonnes via le Grand livre / rapports configurables (Studio, v19 : moteur "
            "aggregation, subformula positive), ou importez le gabarit "
            "odoo-pythonanywhere/examples/balance_generale_6_col_studio.example.xml — voir l’aide « Alternative "
            "manuelle » sur la page utilitaire balance."
        )
    col_ids = rep_rows[0].get("column_ids") or []
    ncols = len(col_ids)
    if ncols not in (2, 4):
        raise ValueError(
            f"Ce rapport a {ncols} colonne(s). Seules les balances à "
            "**4 colonnes** (solde initial, débit, crédit, solde final) ou à **2 colonnes** "
            "(débit et crédit sur la période) sont prises en charge pour la transformation en 6 colonnes."
        )
    detach_meta = _detach_trial_balance_variant_after_six_columns(
        models, db, uid, password, report_id
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
    if ncols == 4:
        lbl_open = cols[0]["expression_label"]
        lbl_deb = cols[1]["expression_label"]
        lbl_cred = cols[2]["expression_label"]
        lbl_end = cols[3]["expression_label"]
        if not all((lbl_open, lbl_deb, lbl_cred, lbl_end)):
            raise ValueError("Colonne sans expression_label : rapport invalide.")
    else:
        lbl_open = ""
        lbl_end = ""
        lbl_deb = cols[0]["expression_label"]
        lbl_cred = cols[1]["expression_label"]
        if not lbl_deb or not lbl_cred:
            raise ValueError("Colonne sans expression_label : rapport invalide (2 colonnes).")

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
        nf = str(e.get("formula") or "")
        nsf = e.get("subformula") or ""
        nsf = str(nsf)
        if lbl_open:
            nf = _replace_agg_labels(nf, lbl_open, _SN_OPEN_DEB, _SN_OPEN_CRE)
            nsf = _replace_agg_labels(nsf, lbl_open, _SN_OPEN_DEB, _SN_OPEN_CRE)
        if lbl_end:
            nf = _replace_agg_labels(nf, lbl_end, _SN_END_DEB, _SN_END_CRE)
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

    if ncols == 4:
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
    else:
        _inject_opening_closing_from_two_period_columns(
            models,
            db,
            uid,
            password,
            line_ids,
            lbl_deb,
            lbl_cred,
            expr_read_fields,
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
            _norm_col_name(cols[1].get("name"), "Débit", "Debit")
            if ncols == 4
            else _norm_col_name(cols[0].get("name"), "Débit", "Debit"),
            lbl_deb,
            (cols[1].get("figure_type") or "monetary")
            if ncols == 4
            else (cols[0].get("figure_type") or "monetary"),
        ),
        _c(
            40,
            _norm_col_name(cols[2].get("name"), "Crédit", "Credit")
            if ncols == 4
            else _norm_col_name(cols[1].get("name"), "Crédit", "Credit"),
            lbl_cred,
            (cols[2].get("figure_type") or "monetary")
            if ncols == 4
            else (cols[1].get("figure_type") or "monetary"),
        ),
        _c(50, {"fr_FR": "Débit final", "en_US": "Closing debit"}, _SN_END_DEB, fig_open),
        _c(60, {"fr_FR": "Crédit final", "en_US": "Closing credit"}, _SN_END_CRE, fig_open),
    ]
    for cv in to_create:
        execute_kw(models, db, uid, password, "account.report.column", "create", [cv])
    try:
        names_end = _account_report_field_names(models, db, uid, password)
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[report_id], _standalone_account_report_write_vals(names_end)],
        )
    except Exception:
        pass
    return detach_meta
