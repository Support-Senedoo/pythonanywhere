#!/usr/bin/env python3
"""
Crée sur la base Odoo un rapport « balance générale 6 colonnes » via XML-RPC.

**Découpage solde → débit / crédit (positifs affichés)** : uniquement sur les **quatre
colonnes extérieures** — **Débit initial**, **Crédit initial**, **Débit final**, **Crédit
final** (solde net : partie ≥ 0 en débit, partie ≤ 0 en valeur absolue en crédit). Les **deux
colonnes centrales de période** (**Débit** / **Crédit**) restent des **cumuls bruts** de
mouvement sur la période ; ne pas les remplacer par un solde net.

Un ``root_report_id`` vers le Grand livre faisait par le passé se comporter le rapport comme une
**variante** (solde signé) : la création toolbox reste **sans** racine ni handler métier.

**Odoo v19+** : sur la ligne feuille ``groupby = account_id``, le moteur **``aggregation``**
avec ``initial_debit`` / ``debit`` / ``subformula: positive``, etc. est **essayé en premier**
(sonde RPC). En repli : moteur ``domain`` (cumuls bruts sur les colonnes extérieures).

**Odoo 18 et séries strictement inférieures à 19** (détection via ``ir.module.module`` module ``base``, champ ``latest_version``) :
la toolbox **ne tente pas** ``aggregation`` à la création et applique **directement** l’ancienne
voie API **``domain``** (même logique qu’avant le basculement v19) — **sans intervention**
utilisateur (pas d’import XML requis pour le bouton « Créer Balance OHADA »). C’est en général
plus stable sur ces versions que ``aggregation`` + ``groupby``.

**Option** : ``TOOLBOX_OHADA6_AGGREGATION_FIRST=1`` pour forcer la tentative ``aggregation``
même sur une série inférieure à 19 (tests / alignement v19). ``TOOLBOX_OHADA6_FORCE_DOMAIN=1`` force
``domain`` sur **toutes** les séries. ``TOOLBOX_OHADA6_OUTER_NET=1`` : en mode domain uniquement,
colonnes extérieures en ``sum_if_pos`` / ``-sum_if_neg``.

**Stratégie** : rapport **autonome**, recopie **uniquement** des options depuis le Grand livre
si trouvé ; en repli ``domain`` uniquement, réécriture XML-RPC des quatre expressions extérieures.

**Rapport déjà déployé** : bouton staff « Colonnes extérieures → brut » ou
``python create_balance_6cols_via_api.py --rewrite-outer-gross`` met à jour les quatre
expressions sans supprimer le rapport ni les menus.

**Libellés d’expressions** : préfixe ``ohada6_`` (ex. ``ohada6_open_deb``) pour les colonnes,
au lieu de ``debit`` / ``debit_initial``, afin d’éviter les collisions avec le moteur standard
des rapports comptables Odoo qui peut réinjecter un solde signé dans une colonne « débit ».

**Balance OHADA (toolbox)** : constantes ``BALANCE_OHADA_*`` + ``create_toolbox_balance_ohada`` /
``find_balance_ohada_report_id`` (ligne feuille ``code = bal_ohada``).

Prototype alternatif (classes 1–9, colonnes aux libellés moteur « standard ») :
``odoo_balance_6colonnes_claude.py`` — utile pour expérimenter ; ne pas substituer à la prod
toolbox (risque de collision avec le moteur Odoo, voir préfixe ``ohada6_*`` ci-dessus).

**Rapport déjà créé avec des en-têtes ``{'fr_FR': ...}`` en clair :** anciennes versions
passaient un dict via XML-RPC → Odoo stockait une chaîne. Supprimer le rapport depuis la
toolbox et le recréer (ou réécrire les ``name`` des colonnes/lignes avec deux ``write``
contexte ``fr_FR`` / ``en_US``, comme ``apply_record_field_translations``).

Prérequis : comptabilité + rapports configurables (account_reports), droits de
création sur ``account.report`` et sous-modèles.

Variables : ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD (ou .env à côté du script)

Usage :
  python create_balance_6cols_via_api.py
  python create_balance_6cols_via_api.py --rewrite-outer-gross
  python create_balance_6cols_via_api.py --rewrite-aggregation
  python create_balance_6cols_via_api.py --name-fr "Autre libellé"
  python create_balance_6cols_via_api.py --line-code bal6_client_x

Après exécution : activer sur le rapport l’option « inclure le solde initial »
(ou équivalent) dans l’interface si les colonnes initiales restent à 0 — comme
pour le gabarit XML.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from account_report_portable import (
    apply_record_field_translations,
    apply_report_name_translations,
    execute_kw,
)
from odoo_client import OdooClient
from web_app.odoo_account_reports import (
    copy_account_report_options_from_source,
    find_general_ledger_account_report_id,
    unlink_all_account_report_client_actions_for_report_ids,
)

# Rapport créé par la toolbox web (repère : account.report.line.code)
BALANCE_OHADA_NAME_FR = "Balance OHADA"
BALANCE_OHADA_NAME_EN = "Balance OHADA"
BALANCE_OHADA_LINE_CODE = "bal_ohada"

# Colonnes : ``expression_label`` = ``label`` des expressions (identiques). Préfixe ohada6_
# pour ne pas utiliser debit / credit / debit_initial, souvent traités à part par Odoo.
OHADA6_OPEN_DEB = "ohada6_open_deb"
OHADA6_OPEN_CRE = "ohada6_open_cre"
OHADA6_MOV_DEB = "ohada6_mov_deb"
OHADA6_MOV_CRE = "ohada6_mov_cre"
OHADA6_CLOSE_DEB = "ohada6_close_deb"
OHADA6_CLOSE_CRE = "ohada6_close_cre"


def _fields(models: Any, db: str, uid: int, password: str, model: str) -> set[str]:
    fg = execute_kw(models, db, uid, password, model, "fields_get", [], {})
    return set(fg.keys())


def _detect_odoo_major_from_db(models: Any, db: str, uid: int, password: str) -> int | None:
    """
    Série majeure Odoo (16, 17, 18, 19…) à partir du module ``base`` installé.

    Utilisé pour choisir la stratégie d’expressions (domain d’abord si série inférieure à 19).
    """
    try:
        bids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "search",
            [[("name", "=", "base"), ("state", "=", "installed")]],
            {"limit": 1},
        )
        if not bids:
            return None
        br = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "read",
            [bids],
            {"fields": ["latest_version", "published_version"]},
        )
        if not br:
            return None
        lv = (br[0].get("latest_version") or br[0].get("published_version") or "").strip()
        if not lv:
            return None
        m = re.search(r"(?:^|~)(\d{1,2})\.", lv)
        if m:
            return int(m.group(1))
        m2 = re.match(r"^(\d{1,2})", lv)
        if m2:
            return int(m2.group(1))
    except Exception:
        pass
    return None


def _report_create_vals(
    field_names: set[str],
    *,
    root_report_id: int | None = None,
) -> dict[str, Any]:
    """``root_report_id`` explicite ; pour Balance OHADA on passe ``None`` (rapport autonome)."""
    vals: dict[str, Any] = {}
    if "root_report_id" in field_names:
        vals["root_report_id"] = int(root_report_id) if root_report_id else False
    if "section_main_report_ids" in field_names:
        vals["section_main_report_ids"] = [(5, 0, 0)]
    return vals


def _column_vals(
    sequence: int,
    fr: str,
    expression_label: str,
) -> dict[str, Any]:
    """Libellé FR seul à la création ; EN appliqué via ``apply_record_field_translations``."""
    return {
        "sequence": sequence,
        "name": fr,
        "expression_label": expression_label,
        "figure_type": "monetary",
    }


def _section_line_code(leaf_code: str) -> str:
    return f"{leaf_code}_section"


def _expressions_domain_grouped_line_outer_gross() -> list[dict[str, Any]]:
    """
    Colonnes extérieures = **cumuls bruts** débit / crédit (même portées que le mode net).

    Mode **par défaut** de la toolbox pour les colonnes extérieures. Les deux colonnes centrales
    restent inchangées.
    """
    mid = _expressions_domain_grouped_line()
    out: list[dict[str, Any]] = []
    for e in mid:
        lbl = e.get("label")
        if lbl == OHADA6_OPEN_DEB:
            out.append(
                {
                    "label": OHADA6_OPEN_DEB,
                    "engine": "domain",
                    "formula": "[('debit', '>', 0)]",
                    "subformula": "sum",
                    "date_scope": "to_beginning_of_period",
                }
            )
        elif lbl == OHADA6_OPEN_CRE:
            out.append(
                {
                    "label": OHADA6_OPEN_CRE,
                    "engine": "domain",
                    "formula": "[('credit', '>', 0)]",
                    "subformula": "-sum",
                    "date_scope": "to_beginning_of_period",
                }
            )
        elif lbl == OHADA6_CLOSE_DEB:
            out.append(
                {
                    "label": OHADA6_CLOSE_DEB,
                    "engine": "domain",
                    "formula": "[('debit', '>', 0)]",
                    "subformula": "sum",
                    "date_scope": "from_beginning",
                }
            )
        elif lbl == OHADA6_CLOSE_CRE:
            out.append(
                {
                    "label": OHADA6_CLOSE_CRE,
                    "engine": "domain",
                    "formula": "[('credit', '>', 0)]",
                    "subformula": "-sum",
                    "date_scope": "from_beginning",
                }
            )
        else:
            out.append(dict(e))
    return out


def _expressions_domain_grouped_line() -> list[dict[str, Any]]:
    """
    Expressions moteur « domain » compatibles avec groupby (Odoo 19+).

    - **Initial / final** : ``[]`` + ``sum_if_pos`` / ``-sum_if_neg`` — découpage du **solde
      net** (ne pas appliquer ce schéma aux colonnes de période).
    - **Période (2 colonnes du milieu)** : **inchangé** — filtres ``debit > 0`` / ``credit > 0``
      + ``sum`` / ``-sum`` (cumuls **bruts** des écritures sur la période).
    """
    return [
        {
            "label": OHADA6_OPEN_DEB,
            "engine": "domain",
            "formula": "[]",
            "subformula": "sum_if_pos",
            "date_scope": "to_beginning_of_period",
        },
        {
            "label": OHADA6_OPEN_CRE,
            "engine": "domain",
            "formula": "[]",
            "subformula": "-sum_if_neg",
            "date_scope": "to_beginning_of_period",
        },
        # Période : mouvements bruts (ne pas remplacer par un solde net débit − crédit).
        {
            "label": OHADA6_MOV_DEB,
            "engine": "domain",
            "formula": "[('debit', '>', 0)]",
            "subformula": "sum",
            "date_scope": "strict_range",
        },
        {
            "label": OHADA6_MOV_CRE,
            "engine": "domain",
            "formula": "[('credit', '>', 0)]",
            "subformula": "-sum",
            "date_scope": "strict_range",
        },
        # Finaux : solde net décomposé (comme les initiaux).
        {
            "label": OHADA6_CLOSE_DEB,
            "engine": "domain",
            "formula": "[]",
            "subformula": "sum_if_pos",
            "date_scope": "from_beginning",
        },
        {
            "label": OHADA6_CLOSE_CRE,
            "engine": "domain",
            "formula": "[]",
            "subformula": "-sum_if_neg",
            "date_scope": "from_beginning",
        },
    ]


def _expressions_aggregation_ohada_line() -> list[dict[str, Any]]:
    """
    Balance OHADA 6 colonnes — moteur ``aggregation`` (Odoo v19 / API).

    Les colonnes initiales / finales utilisent ``subformula: positive`` pour ne garder que la
    partie ≥ 0 du solde net (côté débit ou crédit affiché). Les mouvements de période sont les
    cumuls bruts ``debit`` et ``credit`` (pas de ``-sum``).

    Portées : initiaux = ``to_beginning_of_period`` ; période et soldes finaux décomposés =
    ``strict_range`` (avec solde initial inclus via les options du rapport).
    """
    return [
        {
            "label": OHADA6_OPEN_DEB,
            "engine": "aggregation",
            "formula": "initial_debit - initial_credit",
            "subformula": "positive",
            "date_scope": "to_beginning_of_period",
        },
        {
            "label": OHADA6_OPEN_CRE,
            "engine": "aggregation",
            "formula": "initial_credit - initial_debit",
            "subformula": "positive",
            "date_scope": "to_beginning_of_period",
        },
        {
            "label": OHADA6_MOV_DEB,
            "engine": "aggregation",
            "formula": "debit",
            "date_scope": "strict_range",
        },
        {
            "label": OHADA6_MOV_CRE,
            "engine": "aggregation",
            "formula": "credit",
            "date_scope": "strict_range",
        },
        {
            "label": OHADA6_CLOSE_DEB,
            "engine": "aggregation",
            "formula": "(initial_debit + debit) - (initial_credit + credit)",
            "subformula": "positive",
            "date_scope": "strict_range",
        },
        {
            "label": OHADA6_CLOSE_CRE,
            "engine": "aggregation",
            "formula": "(initial_credit + credit) - (initial_debit + debit)",
            "subformula": "positive",
            "date_scope": "strict_range",
        },
    ]


def _strip_variant_root_and_handlers(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    rep_field_names: set[str],
) -> None:
    """Rapport 100 % autonome : pas de racine ni handler métier (évite soldes signés type variante)."""
    vals: dict[str, Any] = {}
    if "root_report_id" in rep_field_names:
        vals["root_report_id"] = False
    if "section_main_report_ids" in rep_field_names:
        vals["section_main_report_ids"] = [(5, 0, 0)]
    if "custom_handler_model_name" in rep_field_names:
        vals["custom_handler_model_name"] = False
    if vals:
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "write",
                [[int(report_id)], vals],
            )
        except Exception:
            pass


def _force_ohada_outer_domain_expressions(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    line_code: str,
    *,
    outer_mode: str = "net",
) -> None:
    """
    Réécrit les expressions des colonnes extérieures (initiaux / finaux).

    ``outer_mode`` : ``net`` (défaut) = ``sum_if_pos`` / ``-sum_if_neg`` sur ``[]`` ;
    ``gross`` = mouvements bruts ``debit`` / ``credit`` comme
    ``_expressions_domain_grouped_line_outer_gross``.
    """
    line_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("report_id", "=", int(report_id)), ("code", "=", line_code)]],
        {"limit": 2},
    )
    if not line_ids:
        return
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "read",
        [line_ids[:1]],
        {"fields": ["expression_ids"]},
    )
    expr_ids = (rows[0] or {}).get("expression_ids") or []
    if not expr_ids:
        return
    expr_rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.expression",
        "read",
        [expr_ids],
        {"fields": ["id", "label"]},
    )
    if (outer_mode or "net").strip().lower() == "gross":
        targets: dict[str, dict[str, Any]] = {
            OHADA6_OPEN_DEB: {
                "engine": "domain",
                "formula": "[('debit', '>', 0)]",
                "subformula": "sum",
                "date_scope": "to_beginning_of_period",
            },
            OHADA6_OPEN_CRE: {
                "engine": "domain",
                "formula": "[('credit', '>', 0)]",
                "subformula": "-sum",
                "date_scope": "to_beginning_of_period",
            },
            OHADA6_CLOSE_DEB: {
                "engine": "domain",
                "formula": "[('debit', '>', 0)]",
                "subformula": "sum",
                "date_scope": "from_beginning",
            },
            OHADA6_CLOSE_CRE: {
                "engine": "domain",
                "formula": "[('credit', '>', 0)]",
                "subformula": "-sum",
                "date_scope": "from_beginning",
            },
        }
    else:
        targets = {
            OHADA6_OPEN_DEB: {
                "engine": "domain",
                "formula": "[]",
                "subformula": "sum_if_pos",
                "date_scope": "to_beginning_of_period",
            },
            OHADA6_OPEN_CRE: {
                "engine": "domain",
                "formula": "[]",
                "subformula": "-sum_if_neg",
                "date_scope": "to_beginning_of_period",
            },
            OHADA6_CLOSE_DEB: {
                "engine": "domain",
                "formula": "[]",
                "subformula": "sum_if_pos",
                "date_scope": "from_beginning",
            },
            OHADA6_CLOSE_CRE: {
                "engine": "domain",
                "formula": "[]",
                "subformula": "-sum_if_neg",
                "date_scope": "from_beginning",
            },
        }
    for er in expr_rows:
        lbl = er.get("label")
        if lbl not in targets:
            continue
        eid = er.get("id")
        if not eid:
            continue
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.expression",
                "write",
                [[int(eid)], dict(targets[str(lbl)])],
            )
        except Exception:
            continue


_SN_AGG_GROUPBY_PROBE = "_sn_agg_groupby_probe"


def _unlink_all_expressions_on_line(
    models: Any,
    db: str,
    uid: int,
    password: str,
    line_id: int,
) -> None:
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "read",
        [[int(line_id)]],
        {"fields": ["expression_ids"]},
    )
    if not rows:
        return
    eids = (rows[0] or {}).get("expression_ids") or []
    if not eids:
        return
    try:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "unlink",
            [eids],
        )
    except Exception:
        pass


def _line_accepts_aggregation_with_groupby(
    models: Any,
    db: str,
    uid: int,
    password: str,
    line_id: int,
) -> bool:
    """True si le serveur accepte une expression ``aggregation`` sur une ligne déjà ``groupby``."""
    ctx_fr = {"context": {"lang": "fr_FR"}}
    try:
        eid = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "create",
            [
                {
                    "report_line_id": int(line_id),
                    "label": _SN_AGG_GROUPBY_PROBE,
                    "engine": "aggregation",
                    "formula": "0",
                    "date_scope": "strict_range",
                }
            ],
            ctx_fr,
        )
    except Exception:
        return False
    try:
        probe_id = int(eid)
    except (TypeError, ValueError):
        return False
    try:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "unlink",
            [[probe_id]],
        )
    except Exception:
        pass
    return True


def _leaf_line_id_for_report_code(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    line_code: str,
) -> int | None:
    line_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("report_id", "=", int(report_id)), ("code", "=", line_code)]],
        {"limit": 1},
    )
    if not line_ids:
        return None
    return int(line_ids[0])


def _populate_line_expressions(
    models: Any,
    db: str,
    uid: int,
    password: str,
    line_id: int,
    exprs: list[dict[str, Any]],
) -> None:
    """Attache les expressions à une ligne existante : ``write`` en lot, repli création unitaire."""
    ctx_fr = {"context": {"lang": "fr_FR"}}
    cmds = [(0, 0, dict(e)) for e in exprs]
    try:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "write",
            [[int(line_id)], {"expression_ids": cmds}],
            ctx_fr,
        )
        return
    except Exception:
        pass
    for e in exprs:
        ev = dict(e)
        ev["report_line_id"] = int(line_id)
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "create",
            [ev],
            ctx_fr,
        )


def create_balance_six_columns_rpc(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    name_fr: str,
    name_en: str,
    line_code: str,
) -> int:
    rep_fields = _fields(models, db, uid, password, "account.report")

    cols_spec = [
        (10, "Débit initial", "Opening debit", OHADA6_OPEN_DEB),
        (20, "Crédit initial", "Opening credit", OHADA6_OPEN_CRE),
        (30, "Débit", "Debit", OHADA6_MOV_DEB),
        (40, "Crédit", "Credit", OHADA6_MOV_CRE),
        (50, "Débit final", "Closing debit", OHADA6_CLOSE_DEB),
        (60, "Crédit final", "Closing credit", OHADA6_CLOSE_CRE),
    ]

    gl_id = find_general_ledger_account_report_id(models, db, uid, password)
    rep_vals = _report_create_vals(rep_fields, root_report_id=None)
    rep_vals["name"] = name_fr

    report_id = int(
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "create",
            [rep_vals],
            {"context": {"lang": "fr_FR"}},
        )
    )

    _strip_variant_root_and_handlers(
        models, db, uid, password, report_id, rep_fields
    )

    apply_report_name_translations(
        models,
        db,
        uid,
        password,
        report_id,
        name_fr,
        name_en,
    )

    col_fields = _fields(models, db, uid, password, "account.report.column")
    for seq, fr_lbl, en_lbl, expr_lbl in cols_spec:
        cv = _column_vals(seq, fr_lbl, expr_lbl)
        if "blank_if_zero" in col_fields:
            cv["blank_if_zero"] = True
        cv["report_id"] = report_id
        col_id = int(
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.column",
                "create",
                [cv],
                {"context": {"lang": "fr_FR"}},
            )
        )
        apply_record_field_translations(
            models,
            db,
            uid,
            password,
            "account.report.column",
            col_id,
            "name",
            fr_lbl,
            en_lbl,
        )

    # Ligne parente sans groupby (la feuille groupée est l’enfant).
    section_code = _section_line_code(line_code)
    parent_vals: dict[str, Any] = {
        "report_id": report_id,
        "name": "Balance",
        "code": section_code,
        "sequence": 10,
    }
    parent_id = int(
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "create",
            [parent_vals],
            {"context": {"lang": "fr_FR"}},
        )
    )
    apply_record_field_translations(
        models,
        db,
        uid,
        password,
        "account.report.line",
        parent_id,
        "name",
        "Balance",
        "Balance",
    )

    line_field_names = _fields(models, db, uid, password, "account.report.line")
    child_vals_base: dict[str, Any] = {
        "report_id": report_id,
        "parent_id": parent_id,
        "name": "Comptes",
        "code": line_code,
        "groupby": "account_id",
        "sequence": 20,
    }
    if "foldable" in line_field_names:
        child_vals_base["foldable"] = True

    if gl_id:
        try:
            copy_account_report_options_from_source(
                models, db, uid, password, gl_id, report_id
            )
        except Exception:
            pass

    # Séries avant 19 (ex. 18) : ancienne voie API « domain » uniquement — sans import XML utilisateur.
    # Série 19+ : tentative aggregation si le serveur l’accepte ; sinon domain.
    force_domain = (
        os.environ.get("TOOLBOX_OHADA6_FORCE_DOMAIN") or ""
    ).strip().lower() in ("1", "true", "yes", "on")
    aggregation_first_env = (
        os.environ.get("TOOLBOX_OHADA6_AGGREGATION_FIRST") or ""
    ).strip().lower() in ("1", "true", "yes", "on")
    use_net_outer_domain = (
        os.environ.get("TOOLBOX_OHADA6_OUTER_NET") or ""
    ).strip().lower() in ("1", "true", "yes", "on")

    odoo_major = _detect_odoo_major_from_db(models, db, uid, password)
    prefer_domain_api = (
        odoo_major is not None
        and odoo_major < 19
        and not aggregation_first_env
    )

    ctx_fr_line = {"context": {"lang": "fr_FR"}}
    child_id = int(
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "create",
            [child_vals_base],
            ctx_fr_line,
        )
    )

    use_aggregation = (
        not force_domain
        and not prefer_domain_api
        and _line_accepts_aggregation_with_groupby(
            models, db, uid, password, child_id
        )
    )

    if use_aggregation:
        _populate_line_expressions(
            models,
            db,
            uid,
            password,
            child_id,
            _expressions_aggregation_ohada_line(),
        )
    else:
        dom_exprs = (
            _expressions_domain_grouped_line()
            if use_net_outer_domain
            else _expressions_domain_grouped_line_outer_gross()
        )
        _populate_line_expressions(
            models, db, uid, password, child_id, dom_exprs
        )
        _force_ohada_outer_domain_expressions(
            models,
            db,
            uid,
            password,
            report_id,
            line_code,
            outer_mode="net" if use_net_outer_domain else "gross",
        )

    apply_record_field_translations(
        models,
        db,
        uid,
        password,
        "account.report.line",
        child_id,
        "name",
        "Comptes",
        "Accounts",
    )

    return report_id


def create_balance_six_columns(
    client: OdooClient,
    *,
    name_fr: str,
    name_en: str,
    line_code: str,
) -> int:
    uid = client.authenticate()
    return create_balance_six_columns_rpc(
        client._object,
        client.db,
        uid,
        client.password,
        name_fr=name_fr,
        name_en=name_en,
        line_code=line_code,
    )


def _report_ids_from_line_codes(
    models: Any,
    db: str,
    uid: int,
    password: str,
    line_codes: tuple[str, ...],
) -> set[int]:
    out: set[int] = set()
    for code in line_codes:
        line_ids = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "search",
            [[("code", "=", code)]],
        )
        if not line_ids:
            continue
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [line_ids],
            {"fields": ["report_id"]},
        )
        for row in rows:
            r = row.get("report_id")
            if isinstance(r, (list, tuple)) and r and r[0]:
                try:
                    out.add(int(r[0]))
                except (TypeError, ValueError):
                    pass
    return out


def collect_balance_ohada_report_ids_for_cleanup(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> set[int]:
    """
    Identifiants des ``account.report`` créés par **cette** toolbox : uniquement ceux qui
    portent une ligne ``account.report.line`` avec le code feuille ``bal_ohada`` ou la ligne
    section ``bal_ohada_section`` (constantes toolbox). Aucune recherche par libellé : un
    rapport Studio nommé « Balance OHADA » sans ces codes n’est **pas** touché.
    """
    section = _section_line_code(BALANCE_OHADA_LINE_CODE)
    return _report_ids_from_line_codes(
        models,
        db,
        uid,
        password,
        (BALANCE_OHADA_LINE_CODE, section),
    )


def purge_balance_ohada_instances(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> set[int]:
    """
    Supprime menus + actions client + ``account.report`` pour tout ce qui est reconnu comme
    Balance OHADA (voir ``collect_balance_ohada_report_ids_for_cleanup``). Retourne l’ensemble
    d’ids qui étaient ciblés (même si certains ``unlink`` ont échoué).
    """
    from web_app.odoo_account_reports import (
        unlink_all_account_report_client_actions_for_report_ids,
    )

    to_remove = collect_balance_ohada_report_ids_for_cleanup(models, db, uid, password)
    unlink_all_account_report_client_actions_for_report_ids(
        models, db, uid, password, to_remove
    )
    for rid in sorted(to_remove, reverse=True):
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "unlink",
                [[rid]],
            )
        except Exception:
            continue
    return to_remove


def find_all_balance_ohada_report_ids(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    line_code: str = BALANCE_OHADA_LINE_CODE,
) -> list[int]:
    """
    Tous les ``account.report`` qui contiennent une ligne feuille avec ce ``code``
    (défaut ``bal_ohada``), triés par id croissant.
    """
    return sorted(
        _report_ids_from_line_codes(
            models, db, uid, password, (line_code,)
        )
    )


def find_balance_ohada_report_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    line_code: str = BALANCE_OHADA_LINE_CODE,
) -> int | None:
    """
    Retourne un id ``account.report`` toolbox OHADA (repère : ligne ``bal_ohada``).
    S’il y en a plusieurs, retourne le plus petit id (affichage / liens).
    """
    ids = find_all_balance_ohada_report_ids(
        models, db, uid, password, line_code=line_code
    )
    if not ids:
        return None
    return min(ids) if len(ids) > 1 else ids[0]


def rewrite_toolbox_balance_ohada_outer_gross_all_rpc(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    line_code: str = BALANCE_OHADA_LINE_CODE,
) -> list[tuple[int, bool]]:
    """
    Pour chaque ``account.report`` repéré par la ligne feuille ``line_code``, réécrit les quatre
    expressions ``ohada6_*`` extérieures en moteur **domain** « brut » (sans supprimer le rapport).
    """
    lc = (line_code or "").strip() or BALANCE_OHADA_LINE_CODE
    rids = find_all_balance_ohada_report_ids(
        models, db, uid, password, line_code=lc
    )
    out: list[tuple[int, bool]] = []
    for rid in rids:
        ok = True
        try:
            _force_ohada_outer_domain_expressions(
                models,
                db,
                uid,
                password,
                int(rid),
                lc,
                outer_mode="gross",
            )
        except Exception:
            ok = False
        out.append((int(rid), ok))
    return out


def rewrite_toolbox_balance_ohada_aggregation_all_rpc(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    line_code: str = BALANCE_OHADA_LINE_CODE,
) -> list[tuple[int, bool, str]]:
    """
    Remplace **toutes** les expressions de la ligne feuille par le schéma **aggregation** +
    ``positive`` (découpage **net** visé OHADA sur les colonnes extérieures).

    Échoue avec raison ``aggregation_interdit_avec_groupby`` si l’ORM refuse ``aggregation`` sur
    une ligne ``groupby`` (schéma communautaire strict). Sinon, en cas de succès, rouvrir le rapport
    dans Odoo : si l’affichage est incohérent, repasser au mode **brut** (bouton staff ou
    ``--rewrite-outer-gross``).
    """
    lc = (line_code or "").strip() or BALANCE_OHADA_LINE_CODE
    rids = find_all_balance_ohada_report_ids(
        models, db, uid, password, line_code=lc
    )
    out: list[tuple[int, bool, str]] = []
    agg = _expressions_aggregation_ohada_line()
    for rid in rids:
        lid = _leaf_line_id_for_report_code(
            models, db, uid, password, int(rid), lc
        )
        if lid is None:
            out.append((int(rid), False, "ligne_introuvable"))
            continue
        if not _line_accepts_aggregation_with_groupby(
            models, db, uid, password, lid
        ):
            out.append((int(rid), False, "aggregation_interdit_avec_groupby"))
            continue
        try:
            _unlink_all_expressions_on_line(models, db, uid, password, lid)
            _populate_line_expressions(
                models, db, uid, password, lid, agg
            )
            out.append((int(rid), True, "ok"))
        except Exception as e:
            out.append((int(rid), False, f"erreur:{e!s}"))
    return out


def create_toolbox_balance_ohada(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> int:
    """
    Retire toute instance existante (rapport, menus et actions client liés), puis crée
    « Balance OHADA » à neuf.

    Nettoyage : voir ``purge_balance_ohada_instances``.
    """
    purge_balance_ohada_instances(models, db, uid, password)
    return create_balance_six_columns_rpc(
        models,
        db,
        uid,
        password,
        name_fr=BALANCE_OHADA_NAME_FR,
        name_en=BALANCE_OHADA_NAME_EN,
        line_code=BALANCE_OHADA_LINE_CODE,
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Crée une balance 6 colonnes (account.report) via API Odoo."
    )
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument(
        "--password",
        default=os.environ.get("ODOO_PASSWORD", "").strip() or None,
    )
    p.add_argument(
        "--name-fr",
        default=BALANCE_OHADA_NAME_FR,
        help="Libellé du rapport (FR)",
    )
    p.add_argument(
        "--name-en",
        default="",
        help="Libellé du rapport (EN) ; défaut = même texte que --name-fr",
    )
    p.add_argument(
        "--line-code",
        default=BALANCE_OHADA_LINE_CODE,
        help="Code unique de la ligne feuille (account.report.line.code)",
    )
    p.add_argument(
        "--rewrite-outer-gross",
        action="store_true",
        help="Ne pas créer : réécrit les 4 colonnes extérieures en « brut » pour chaque rapport bal_ohada.",
    )
    p.add_argument(
        "--rewrite-aggregation",
        action="store_true",
        help="Ne pas créer : remplace les 6 expressions par aggregation+positive (net OHADA si Odoo l’affiche).",
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
        print("Paramètres manquants :", ", ".join(missing), file=sys.stderr)
        return 1
    if args.rewrite_outer_gross and args.rewrite_aggregation:
        print(
            "Utilisez soit --rewrite-outer-gross soit --rewrite-aggregation, pas les deux.",
            file=sys.stderr,
        )
        return 1

    name_en = (args.name_en or "").strip() or args.name_fr
    line_code = (args.line_code or "").strip() or BALANCE_OHADA_LINE_CODE

    client = OdooClient(args.url, args.db, args.user, args.password)
    if args.rewrite_outer_gross:
        try:
            uid = client.authenticate()
            pairs = rewrite_toolbox_balance_ohada_outer_gross_all_rpc(
                client._object,
                client.db,
                uid,
                client.password,
                line_code=line_code,
            )
        except Exception as e:
            print("Échec :", e, file=sys.stderr)
            return 1
        if not pairs:
            print(
                f"Aucun account.report avec une ligne code={line_code!r}.",
                file=sys.stderr,
            )
            return 2
        for rid, ok in pairs:
            print(f"account.report id={rid} : {'OK' if ok else 'ÉCHEC'}")
        return 0 if all(p[1] for p in pairs) else 1

    if args.rewrite_aggregation:
        try:
            uid = client.authenticate()
            triples = rewrite_toolbox_balance_ohada_aggregation_all_rpc(
                client._object,
                client.db,
                uid,
                client.password,
                line_code=line_code,
            )
        except Exception as e:
            print("Échec :", e, file=sys.stderr)
            return 1
        if not triples:
            print(
                f"Aucun account.report avec une ligne code={line_code!r}.",
                file=sys.stderr,
            )
            return 2
        for rid, ok, reason in triples:
            print(
                f"account.report id={rid} : "
                f"{'OK' if ok else 'ÉCHEC'} ({reason})"
            )
        return 0 if all(t[1] for t in triples) else 1

    try:
        rid = create_balance_six_columns(
            client,
            name_fr=args.name_fr,
            name_en=name_en,
            line_code=line_code,
        )
    except Exception as e:
        print("Échec :", e, file=sys.stderr)
        return 1

    print(f"OK — rapport account.report id={rid} (ligne code={line_code!r}).")
    print(
        "Vérifiez dans Odoo l’option « solde initial » sur le rapport si besoin "
        "(colonnes initiales à 0 sinon)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
