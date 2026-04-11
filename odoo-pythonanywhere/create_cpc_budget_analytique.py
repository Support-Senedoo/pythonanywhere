"""
Crée un rapport CPC SYSCOHADA — Budget Analytique (account.report) via l'API Odoo.

4 colonnes : Réalisé / Budget / Écart / % Réalisation.
Structure CPC SYSCOHADA complète (plan comptable OHADA / Sénégal).

Compatible avec les fonctions execute_kw de personalize_syscohada_detail.py.
Utilisé par la toolbox Flask (web_app/blueprints/staff.py).

Stratégie colonne Budget (contournement limitation Odoo SaaS v16-v19) :
  engine='budget' est masqué par Odoo quand le filtre analytique est actif.
  Solution : les expressions Budget des lignes de détail utilisent engine='external',
  lues depuis account.report.external.value (pré-calculées par sync_cpc_budget_analytique.py).
  Les lignes de totaux (X*) utilisent engine='aggregation' sur .budget des lignes de détail.
  → Lancer "Synchroniser le budget" dans la Toolbox pour peupler les valeurs externes.
"""
from __future__ import annotations

import re
from typing import Any

from personalize_syscohada_detail import execute_kw

CPC_BUDGET_ANALYTIQUE_NAME = "CPC SYSCOHADA \u2014 Budget Analytique (Senedoo)"

# Structure CPC SYSCOHADA \u2014 Plan comptable OHADA / S\u00e9n\u00e9gal
# Format : (code, libell\u00e9, nature, formule_account_codes, formule_aggregation)
# nature 'account'   \u2192 engine account_codes (d\u00e9tail par compte)
# nature 'aggregate' \u2192 engine aggregation   (totaux / sous-totaux)
_CPC_STRUCTURE: list[tuple[str, str, str, str | None, str | None]] = [
    # \u2500\u2500 PRODUITS D'EXPLOITATION \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ("TA", "Ventes de marchandises",             "account",   "^701,^7011,^7012,^7013",   None),
    ("RA", "Achats de marchandises",              "account",   "^601,^6011,^6012,^6013",   None),
    ("RB", "Variation de stocks de marchandises", "account",   "^6031",                    None),
    ("XA", "MARGE COMMERCIALE (TA-RA-RB)",        "aggregate", None, "TA - RA - RB"),
    ("TB", "Ventes de produits fabriqu\u00e9s",        "account",   "^702,^703,^7021,^7031",    None),
    ("TC", "Travaux, services vendus",             "account",   "^704,^705,^706,^707,^708", None),
    ("TD", "Produits accessoires",                 "account",   "^709",                     None),
    ("XB", "CHIFFRE D'AFFAIRES (TA+TB+TC+TD)",    "aggregate", None, "TA + TB + TC + TD"),
    ("TE", "Production stock\u00e9e (ou d\u00e9stock\u00e9e)",    "account",   "^6032,^6033",              None),
    ("TF", "Production immobilis\u00e9e",               "account",   "^72",                      None),
    ("TG", "Subventions d'exploitation",           "account",   "^71",                      None),
    ("TH", "Autres produits",                      "account",   "^75",                      None),
    ("TI", "Transferts de charges d'exploitation", "account",   "^781",                     None),
    # \u2500\u2500 CHARGES D'EXPLOITATION \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ("RC", "Achats de mati\u00e8res premi\u00e8res",           "account",   "^602",                     None),
    ("RD", "Variation de stocks mati\u00e8res premi\u00e8res", "account",   "^6032",                    None),
    ("RE", "Autres achats",                        "account",   "^604,^605,^608",            None),
    ("RF", "Variation autres approvisionnements",  "account",   "^6033",                    None),
    ("RG", "Transports",                           "account",   "^61",                      None),
    ("RH", "Services ext\u00e9rieurs",                  "account",   "^62,^63",                  None),
    ("RI", "Imp\u00f4ts et taxes",                      "account",   "^64",                      None),
    ("RJ", "Autres charges",                       "account",   "^65",                      None),
    ("XC", "VALEUR AJOUT\u00c9E",                        "aggregate", None,
     "XB + TE + TF + TG + TH + TI - RC - RD - RE - RF - RG - RH - RI - RJ"),
    ("RK", "Charges de personnel",                 "account",   "^66",                      None),
    ("XD", "EXC\u00c9DENT BRUT D'EXPLOITATION (XC-RK)",  "aggregate", None, "XC - RK"),
    ("TJ", "Reprises d'amortissements, provisions","account",   "^791,^798",                None),
    ("RL", "Dotations amortissements et provisions","account",  "^681,^691",                None),
    ("XE", "R\u00c9SULTAT D'EXPLOITATION (XD+TJ-RL)",   "aggregate", None, "XD + TJ - RL"),
    # \u2500\u2500 OP\u00c9RATIONS FINANCI\u00c8RES \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ("TK", "Revenus financiers",                   "account",   "^77",                      None),
    ("TL", "Reprises provisions financi\u00e8res",       "account",   "^797",                     None),
    ("TM", "Transferts de charges financi\u00e8res",     "account",   "^787",                     None),
    ("RM", "Frais financiers et charges assimil\u00e9es","account",  "^67",                      None),
    ("RN", "Dotations provisions financi\u00e8res",      "account",   "^697",                     None),
    ("XF", "R\u00c9SULTAT FINANCIER",                    "aggregate", None, "TK + TL + TM - RM - RN"),
    ("XG", "R\u00c9SULTAT DES ACTIVIT\u00c9S ORDINAIRES (XE+XF)", "aggregate", None, "XE + XF"),
    # \u2500\u2500 HORS ACTIVIT\u00c9S ORDINAIRES \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ("TN", "Produits HAO",                         "account",   "^88",                      None),
    ("TO", "Reprises HAO",                         "account",   "^798",                     None),
    ("RO", "Charges HAO",                          "account",   "^83,^84,^85,^87",          None),
    ("RP", "Dotations HAO",                        "account",   "^698",                     None),
    ("XH", "R\u00c9SULTAT HAO",                          "aggregate", None, "TN + TO - RO - RP"),
    # \u2500\u2500 R\u00c9SULTAT NET \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    ("RQ", "Participation des travailleurs",        "account",   "^869",                     None),
    ("RS", "Imp\u00f4ts sur le r\u00e9sultat",               "account",   "^89",                      None),
    ("XI", "R\u00c9SULTAT NET (XG+XH-RQ-RS)",             "aggregate", None, "XG + XH - RQ - RS"),
]


# ---------------------------------------------------------------------------
# Utilitaires internes
# ---------------------------------------------------------------------------

def _ek(models: Any, db: str, uid: int, password: str, model: str, method: str,
        args: list | None = None, kw: dict | None = None) -> Any:
    """Raccourci execute_kw avec defaults."""
    return execute_kw(models, db, uid, password, model, method, args or [], kw)


def _agg_formula_with_suffix(formula_agg: str, suffix: str) -> str:
    """
    Transforme une formule d'agr\u00e9gation pour r\u00e9f\u00e9rencer une expression sp\u00e9cifique.
    Exemple : 'TA - RA - RB'  \u2192  'TA.budget - RA.budget - RB.budget'
    Seuls les codes \u00e0 2 lettres majuscules sont substitu\u00e9s.
    """
    return re.sub(r'\b([A-Z]{2})\b', lambda m: f'{m.group(1)}.{suffix}', formula_agg)


def _create_expression_safe(models: Any, db: str, uid: int, password: str,
                             expr_vals: dict) -> int | None:
    """
    Cr\u00e9e une expression account.report.expression.
    Fallback sur un sous-ensemble de champs si l'API rejette la premi\u00e8re tentative
    (champs non support\u00e9s selon la version Odoo).
    """
    try:
        return _ek(models, db, uid, password, "account.report.expression", "create", [expr_vals])
    except Exception:
        safe = {k: v for k, v in expr_vals.items()
                if k in ("report_line_id", "label", "engine", "formula", "date_scope")}
        try:
            return _ek(models, db, uid, password, "account.report.expression", "create", [safe])
        except Exception:
            return None


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def collect_cpc_budget_report_ids_for_cleanup(
    models: Any, db: str, uid: int, password: str
) -> list[int]:
    """
    Retourne les IDs des rapports toolbox CPC budget analytique existants
    (identifi\u00e9s par le nom exact ``CPC_BUDGET_ANALYTIQUE_NAME``).
    """
    try:
        ids = _ek(models, db, uid, password, "account.report", "search",
                  [[["name", "=", CPC_BUDGET_ANALYTIQUE_NAME]]])
        return [int(i) for i in (ids or [])]
    except Exception:
        return []


def purge_cpc_budget_analytique_instances(
    models: Any, db: str, uid: int, password: str
) -> list[int]:
    """
    Supprime toutes les instances toolbox CPC budget analytique (colonnes, expressions,
    lignes, rapport). Retourne les IDs supprim\u00e9s.
    """
    prior = collect_cpc_budget_report_ids_for_cleanup(models, db, uid, password)
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


def create_toolbox_cpc_budget_analytique(
    models: Any, db: str, uid: int, password: str
) -> dict[str, Any]:
    """
    Cr\u00e9e le rapport CPC SYSCOHADA \u2014 Budget Analytique sur la base Odoo indiqu\u00e9e.

    Op\u00e9rations :
      1. Supprime les instances toolbox pr\u00e9existantes (m\u00eame nom).
      2. Cr\u00e9e l'enregistrement account.report avec filter_analytic=True.
      3. Cr\u00e9e 4 colonnes : R\u00e9alis\u00e9 / Budget / \u00c9cart / % R\u00e9alisation.
      4. Cr\u00e9e toutes les lignes CPC SYSCOHADA avec leurs expressions par colonne.

    Retourne un dict :
      report_id   : ID du rapport cr\u00e9\u00e9
      col_count   : nombre de colonnes cr\u00e9\u00e9es
      line_count  : nombre de lignes CPC cr\u00e9\u00e9es
      prior_ids   : IDs supprim\u00e9s avant cr\u00e9ation

    Limitations :
      Sur Odoo SaaS v16-v19, la colonne « Budget » peut \u00eatre masqu\u00e9e lorsque
      le filtre analytique est actif (engine='budget' incompatible avec analytic_account_ids).
      Contournement complet : account.report.external.value (CLI odoo_cpc_budget_analytique.py).
    """
    # \u00c9tape 1 \u2014 nettoyage
    prior_ids = purge_cpc_budget_analytique_instances(models, db, uid, password)

    # \u00c9tape 2 \u2014 rapport principal
    report_id = int(_ek(models, db, uid, password, "account.report", "create", [{
        "name":                        CPC_BUDGET_ANALYTIQUE_NAME,
        "filter_date_range":           True,
        "filter_analytic":             True,
        "filter_journals":             True,
        "filter_unfold_all":           True,
        "filter_show_draft":           False,
        "default_opening_date_filter": "this_year",
        "search_bar":                  True,
        "load_more_limit":             80,
    }]))

    # \u00c9tape 3 \u2014 4 colonnes
    col_defs = [
        {"name": "R\u00e9alis\u00e9",       "expression_label": "balance", "figure_type": "monetary",
         "report_id": report_id, "sequence": 10, "blank_if_zero": False, "sortable": True},
        {"name": "Budget",        "expression_label": "budget",  "figure_type": "monetary",
         "report_id": report_id, "sequence": 20, "blank_if_zero": False, "sortable": True},
        {"name": "\u00c9cart",          "expression_label": "ecart",   "figure_type": "monetary",
         "report_id": report_id, "sequence": 30, "blank_if_zero": False, "sortable": True},
        {"name": "% R\u00e9alisation", "expression_label": "pct",     "figure_type": "percentage",
         "report_id": report_id, "sequence": 40, "blank_if_zero": False, "sortable": True},
    ]
    col_count = 0
    for col in col_defs:
        try:
            _ek(models, db, uid, password, "account.report.column", "create", [col])
            col_count += 1
        except Exception:
            pass

    # \u00c9tape 4 \u2014 lignes CPC + expressions
    seq = 10
    line_count = 0
    for code, label, nature, formula_ac, formula_agg in _CPC_STRUCTURE:
        is_total = code.startswith("X")
        try:
            line_id = int(_ek(models, db, uid, password, "account.report.line", "create", [{
                "name":            f"{code} \u2014 {label}",
                "report_id":       report_id,
                "code":            code,
                "sequence":        seq,
                "unfoldable":      not is_total,
                "foldable":        not is_total,
                "hide_if_zero":    False,
                "hierarchy_level": 0 if is_total else 1,
            }]))
            seq += 10
            line_count += 1

            if nature == "account":
                # R\u00e9alis\u00e9 : engine account_codes respecte filter_analytic
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "balance",
                    "engine":         "account_codes",
                    "formula":        formula_ac,
                    "date_scope":     "strict_range",
                })
                # Budget : engine external (lit account.report.external.value)
                # \u2192 engine='budget' masqu\u00e9 par Odoo avec filtre analytique actif.
                # \u2192 Peupler via action "Synchroniser le budget" dans la Toolbox.
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "budget",
                    "engine":         "external",
                    "formula":        "",
                    "date_scope":     "strict_range",
                })
                # \u00c9cart : Budget \u2212 R\u00e9alis\u00e9
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "ecart",
                    "engine":         "aggregation",
                    "formula":        f"{code}.budget - {code}.balance",
                    "date_scope":     "strict_range",
                })
                # % R\u00e9alisation
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "pct",
                    "engine":         "aggregation",
                    "formula":        f"if_other_is_zero({code}.budget, 0, {code}.balance / {code}.budget * 100)",
                    "date_scope":     "strict_range",
                })

            elif nature == "aggregate":
                # R\u00e9alis\u00e9 (agr\u00e9gation des lignes de d\u00e9tail \u2014 r\u00e9f\u00e9rence implicite .balance)
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "balance",
                    "engine":         "aggregation",
                    "formula":        formula_agg,
                    "date_scope":     "strict_range",
                })
                # Budget (m\u00eame formule mais sur .budget de chaque code)
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "budget",
                    "engine":         "aggregation",
                    "formula":        _agg_formula_with_suffix(formula_agg, "budget"),
                    "date_scope":     "strict_range",
                })
                # \u00c9cart
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "ecart",
                    "engine":         "aggregation",
                    "formula":        f"{code}.budget - {code}.balance",
                    "date_scope":     "strict_range",
                })
                # % R\u00e9alisation
                _create_expression_safe(models, db, uid, password, {
                    "report_line_id": line_id,
                    "label":          "pct",
                    "engine":         "aggregation",
                    "formula":        f"if_other_is_zero({code}.budget, 0, {code}.balance / {code}.budget * 100)",
                    "date_scope":     "strict_range",
                })

        except Exception:
            pass

    return {
        "report_id":  report_id,
        "col_count":  col_count,
        "line_count": line_count,
        "prior_ids":  prior_ids,
    }
