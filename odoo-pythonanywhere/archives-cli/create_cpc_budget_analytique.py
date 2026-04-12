"""
Crée un rapport CPC SYSCOHADA — Budget Analytique (account.report) via l'API Odoo.

4 colonnes : Réalisé / Budget / Écart / % Réalisation.
Structure CPC SYSCOHADA complète (plan comptable OHADA / Sénégal).

Compatible avec les fonctions execute_kw de personalize_syscohada_detail.py.
Utilisé par la toolbox Flask (web_app/blueprints/staff.py).

Stratégie colonne Budget (données 100 % Odoo pour les utilisateurs qui filtrent dans l’UI) :
  - Engine ``budget`` si la sélection ``engine`` l’expose (filtre budgets natif Odoo).
  - Sinon ``account.report.budget.item`` ou ``crossovered.budget.lines`` : engine ``external`` ;
    les ``account.report.external.value`` doivent être **écrits côté Odoo** (cron, module, serveur)
    ou en phase de **test** via l’outillage d’intégration — ce n’est pas une action des utilisateurs
    finaux dans le rapport.
  - Sinon repli ``account_codes`` (même formule que le réalisé — peu utile).
  - Après création du rapport : activation de ``filter_budgets`` ou ``filter_budget`` sur la
    fiche ``account.report`` lorsque le modèle les expose (même logique que le P&L analytique
    Senedoo), en plus de ``filter_analytic``. Sans ce filtre budgets, Odoo peut masquer ou
    ne plus piloter correctement les colonnes budget / % avec l’analytique.
  - Les totaux (codes X*) : engine ``aggregation`` sur les .budget des lignes de détail.
  - Formules ``account_codes`` / ``budget`` : normalisation Odoo 19 (``^601,^6011`` → ``601+6011``).
"""
from __future__ import annotations

import re
from typing import Any

from personalize_pl_analytic_budget import personalize_pl_analytic_budget_options
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

# Tuple public (même contenu que _CPC_STRUCTURE) pour scripts externes ex. verify_cpc_budget_analytique.py
CPC_BUDGET_STRUCTURE: tuple[tuple[str, str, str, str | None, str | None], ...] = tuple(_CPC_STRUCTURE)


# ---------------------------------------------------------------------------
# Utilitaires internes
# ---------------------------------------------------------------------------

def _ek(models: Any, db: str, uid: int, password: str, model: str, method: str,
        args: list | None = None, kw: dict | None = None) -> Any:
    """Raccourci execute_kw avec defaults."""
    return execute_kw(models, db, uid, password, model, method, args or [], kw)


def normalize_cpc_account_codes_formula(formula: str | None) -> str:
    """
    Adapte les formules style SYSCOHADA / ancien XML-RPC (``^601,^6011``) au moteur
    ``account_codes`` d'Odoo 19+ : termes additionnés avec ``+``, sans ``^`` devant les préfixes
    (le ``^`` n'est pas un caractère autorisé dans le jeton ``prefix`` de la validation serveur).
    """
    if not formula:
        return ""
    raw = str(formula).strip()
    compact = raw.replace(" ", "")
    if "tag(" in compact:
        return compact
    parts = [p.strip().replace(" ", "") for p in raw.split(",") if p.strip()]
    if not parts:
        return compact
    cleaned: list[str] = []
    for p in parts:
        if p.startswith("^"):
            p = p[1:]
        if p:
            cleaned.append(p)
    if len(cleaned) == 1:
        return cleaned[0]
    return "+".join(cleaned)


def _agg_formula_with_suffix(formula_agg: str, suffix: str) -> str:
    """
    Transforme une formule d'agr\u00e9gation pour r\u00e9f\u00e9rencer une expression sp\u00e9cifique.
    Exemple : 'TA - RA - RB'  \u2192  'TA.budget - RA.budget - RB.budget'
    Seuls les codes \u00e0 2 lettres majuscules sont substitu\u00e9s.
    """
    return re.sub(r'\b([A-Z]{2})\b', lambda m: f'{m.group(1)}.{suffix}', formula_agg)


def _create_report_line_safe(
    models: Any,
    db: str,
    uid: int,
    password: str,
    *,
    code: str,
    label: str,
    report_id: int,
    sequence: int,
    is_total: bool,
) -> tuple[int | None, str | None]:
    """
    Crée account.report.line. Odoo 19+ : pas de champ ``unfoldable`` ; ``hierarchy_level`` est calculé
    (ne pas l'écrire à la création).
    """
    vals: dict[str, Any] = {
        "name":            f"{code} \u2014 {label}",
        "report_id":       report_id,
        "code":            code,
        "sequence":        sequence,
        "foldable":        not is_total,
        "hide_if_zero":    False,
    }
    try:
        return int(_ek(models, db, uid, password, "account.report.line", "create", [vals])), None
    except Exception as e:
        err1 = str(e)
        minimal = {
            "name":      vals["name"],
            "report_id": report_id,
            "code":      code,
            "sequence":  sequence,
        }
        try:
            return (
                int(_ek(models, db, uid, password, "account.report.line", "create", [minimal])),
                f"ligne {code} : 1er refus ({err1[:220]}), créée en minimal.",
            )
        except Exception as e2:
            return None, f"ligne {code} : {err1} | minimal: {e2}"


def _create_column_safe(
    models: Any, db: str, uid: int, password: str, col_vals: dict
) -> tuple[int | None, str | None]:
    """
    Crée une colonne account.report.column ; repli sur champs minimaux si l'API refuse.
    Retourne (id, None) ou (None, message d'erreur).
    """
    try:
        return int(_ek(models, db, uid, password, "account.report.column", "create", [col_vals])), None
    except Exception as e:
        err1 = str(e)
        minimal: dict[str, Any] = {
            k: col_vals[k]
            for k in ("name", "expression_label", "figure_type", "report_id", "sequence")
            if k in col_vals
        }
        if "blank_if_zero" in col_vals:
            minimal["blank_if_zero"] = col_vals["blank_if_zero"]
        try:
            return (
                int(_ek(models, db, uid, password, "account.report.column", "create", [minimal])),
                f"colonne « {col_vals.get('expression_label')} » : 1er refus ({err1[:200]}), créée en minimal.",
            )
        except Exception as e2:
            return None, f"colonne « {col_vals.get('expression_label')} » : {err1} | minimal: {e2}"


def _create_expression_safe(
    models: Any, db: str, uid: int, password: str, expr_vals: dict
) -> tuple[Any | None, str | None]:
    """
    Cr\u00e9e une expression account.report.expression.
    Fallback sur un sous-ensemble de champs si l'API rejette la premi\u00e8re tentative
    (champs non support\u00e9s selon la version Odoo).
    Retourne (id cr\u00e9\u00e9 ou valeur renvoy\u00e9e par create, None) ou (None, message d'erreur).
    """
    label = expr_vals.get("label") or "?"
    try:
        return _ek(models, db, uid, password, "account.report.expression", "create", [expr_vals]), None
    except Exception as e1:
        safe = {
            k: v
            for k, v in expr_vals.items()
            if k in (
                "report_line_id",
                "label",
                "engine",
                "formula",
                "date_scope",
                "subformula",
                "figure_type",
            )
        }
        try:
            return (
                _ek(models, db, uid, password, "account.report.expression", "create", [safe]),
                None,
            )
        except Exception as e2:
            return None, f"expression {label!r} : {e1!s} | minimal: {e2!s}"


def _expr_formula_for_engine(expr_vals: dict) -> dict:
    """Copie des vals avec formule normalis\u00e9e pour account_codes et budget."""
    out = dict(expr_vals)
    eng = (out.get("engine") or "").strip()
    if eng in ("account_codes", "budget") and "formula" in out:
        out["formula"] = normalize_cpc_account_codes_formula(out["formula"])
    return out


def cpc_crossovered_budget_available(models: Any, db: str, uid: int, password: str) -> bool:
    """True si le modèle ``crossovered.budget.lines`` est présent (budget analytique classique)."""
    try:
        n = int(
            _ek(
                models,
                db,
                uid,
                password,
                "ir.model",
                "search_count",
                [[["model", "=", "crossovered.budget.lines"]]],
            )
            or 0
        )
        return n > 0
    except Exception:
        return False


def cpc_account_report_budget_item_available(models: Any, db: str, uid: int, password: str) -> bool:
    """True si le modèle ``account.report.budget.item`` est présent (budgets financiers liés au reporting)."""
    try:
        n = int(
            _ek(
                models,
                db,
                uid,
                password,
                "ir.model",
                "search_count",
                [[["model", "=", "account.report.budget.item"]]],
            )
            or 0
        )
        return n > 0
    except Exception:
        return False


def expression_engine_keys(models: Any, db: str, uid: int, password: str) -> frozenset[str]:
    """Valeurs autoris\u00e9es pour ``account.report.expression.engine`` sur cette base."""
    try:
        fg = _ek(models, db, uid, password, "account.report.expression", "fields_get", [], {})
        sel = fg.get("engine", {}).get("selection") or []
        return frozenset(
            str(x[0])
            for x in sel
            if isinstance(x, (list, tuple)) and len(x) >= 1 and x[0] is not False
        )
    except Exception:
        return frozenset()


def cpc_budget_pct_aggregation_formula(line_code: str, *, budget_pct_meaningful: bool) -> str:
    """
    Formule moteur ``aggregation`` pour la colonne %.
    Odoo 19 : ``if_other_is_zero(...)`` n'est plus accept\u00e9 par la regex de validation.
    Si la colonne budget n'est pas fiable (même GL que le r\u00e9alis\u00e9), retourner ``0``.
    """
    if not budget_pct_meaningful:
        return "0"
    c = line_code
    return f"{c}.balance/{c}.budget*100"


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
      3. Active filter_budgets / filter_budget sur le rapport si le mod\u00e8le les expose.
      4. Cr\u00e9e 4 colonnes : R\u00e9alis\u00e9 / Budget / \u00c9cart / % R\u00e9alisation.
      5. Cr\u00e9e toutes les lignes CPC SYSCOHADA avec leurs expressions par colonne.

    Retourne un dict :
      report_id   : ID du rapport cr\u00e9\u00e9
      col_count   : nombre de colonnes cr\u00e9\u00e9es
      line_count  : nombre de lignes CPC cr\u00e9\u00e9es
      prior_ids   : IDs supprim\u00e9s avant cr\u00e9ation
      filter_written : bool\u00e9ens \u00e9crits sur le rapport (filter_analytic, filter_budgets, \u2026)
      filter_personalization_error : message si l\u2019activation des filtres a \u00e9chou\u00e9
      column_errors : messages si une colonne n\u2019a pas pu \u00eatre cr\u00e9\u00e9e
      line_errors   : messages si une ligne n\u2019a pas pu \u00eatre cr\u00e9\u00e9e
      expression_errors : \u00e9checs cr\u00e9ation account.report.expression
      budget_mode : ``native`` | ``external`` | ``fallback_gl``
      budget_external_source : ``report_budget_item`` | ``crossovered`` | None
      budget_engine_used : moteur de l'expression ``budget`` sur les lignes d\u00e9tail
      budget_pct_meaningful : True si % et \u00e9cart peuvent s'appuyer sur une colonne budget r\u00e9elle
      creation_warnings : avertissements (ex. fallback sans moteur budget)
      verification  : r\u00e9sultat de verify_cpc_budget_analytique_report (contr\u00f4le auto)
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

    filter_written: dict[str, Any] = {}
    filter_personalization_error: str | None = None
    try:
        opt = personalize_pl_analytic_budget_options(
            models, db, uid, password, report_id, enable_budget_filter=True
        )
        filter_written = dict(opt.get("written") or {})
    except Exception as e:
        filter_personalization_error = str(e)

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
    column_errors: list[str] = []
    for col in col_defs:
        cid, warn = _create_column_safe(models, db, uid, password, col)
        if cid is not None:
            col_count += 1
            if warn:
                column_errors.append(warn)
        else:
            column_errors.append(warn or "colonne inconnue")

    # \u00c9tape 4 \u2014 lignes CPC + expressions
    seq = 10
    line_count = 0
    line_errors: list[str] = []
    expression_errors: list[str] = []
    eng_keys = expression_engine_keys(models, db, uid, password)
    report_budget_item_ok = cpc_account_report_budget_item_available(models, db, uid, password)
    crossovered_ok = cpc_crossovered_budget_available(models, db, uid, password)
    budget_external_source: str | None = None
    if "budget" in eng_keys:
        budget_mode = "native"
        budget_engine_used = "budget"
    elif report_budget_item_ok:
        budget_mode = "external"
        budget_engine_used = "external"
        budget_external_source = "report_budget_item"
    elif crossovered_ok:
        budget_mode = "external"
        budget_engine_used = "external"
        budget_external_source = "crossovered"
    else:
        budget_mode = "fallback_gl"
        budget_engine_used = "account_codes"
    budget_pct_meaningful = budget_mode != "fallback_gl"
    creation_warnings: list[str] = []
    if budget_mode == "fallback_gl":
        creation_warnings.append(
            "Cette instance Odoo n'a ni moteur « budget » sur les expressions, ni modèle "
            "account.report.budget.item, ni crossovered.budget.lines : la colonne Budget reprend "
            "le réalisé (inutile pour l'analyse)."
        )
    elif budget_mode == "external" and budget_external_source == "report_budget_item":
        creation_warnings.append(
            "Colonne Budget = moteur « external » (``account.report.budget.item``). "
            "Les utilisateurs Odoo choisissent période, analytique et budget financier **dans Odoo** ; "
            "les ``account.report.external.value`` doivent être alimentés par un **mécanisme côté Odoo** "
            "(cron, module, serveur) ou par l’outillage d’intégration **uniquement pour tests / mise en route**."
        )
    elif budget_mode == "external":
        creation_warnings.append(
            "Colonne Budget = moteur « external » (crossovered). "
            "Les utilisateurs Odoo ne font que filtrer dans Odoo ; pour afficher des montants, "
            "prévoir une **alimentation technique sur le serveur Odoo** (cron, module, etc.) "
            "vers ``account.report.external.value``, ou l’équivalent en zone d’intégration pour essais."
        )

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
            line_errors.append(lwarn or f"{code}: ligne non cr\u00e9\u00e9e")
            continue
        if lwarn:
            line_errors.append(lwarn)
        line_count += 1

        if nature == "account":
            # R\u00e9alis\u00e9 : engine account_codes respecte filter_analytic
            _push_expr({
                "_line_code":     code,
                "report_line_id": line_id,
                "label":          "balance",
                "engine":         "account_codes",
                "formula":        formula_ac,
                "date_scope":     "strict_range",
            })
            # Budget : natif, external (crossovered), ou repli GL
            if budget_mode == "native":
                _push_expr({
                    "_line_code":     code,
                    "report_line_id": line_id,
                    "label":          "budget",
                    "engine":         "budget",
                    "formula":        formula_ac,
                    "date_scope":     "strict_range",
                })
            elif budget_mode == "external":
                _push_expr({
                    "_line_code":     code,
                    "report_line_id": line_id,
                    "label":          "budget",
                    "engine":         "external",
                    "formula":        "sum",
                    "subformula":     "editable",
                    "figure_type":    "monetary",
                    "date_scope":     "strict_range",
                })
            else:
                _push_expr({
                    "_line_code":     code,
                    "report_line_id": line_id,
                    "label":          "budget",
                    "engine":         "account_codes",
                    "formula":        formula_ac,
                    "date_scope":     "strict_range",
                })
            # \u00c9cart : Budget \u2212 R\u00e9alis\u00e9
            _push_expr({
                "_line_code":     code,
                "report_line_id": line_id,
                "label":          "ecart",
                "engine":         "aggregation",
                "formula":        f"{code}.budget - {code}.balance",
                "date_scope":     "strict_range",
            })
            # % R\u00e9alisation
            _push_expr({
                "_line_code":     code,
                "report_line_id": line_id,
                "label":          "pct",
                "engine":         "aggregation",
                "formula":        cpc_budget_pct_aggregation_formula(
                    code, budget_pct_meaningful=budget_pct_meaningful
                ),
                "date_scope":     "strict_range",
            })

        elif nature == "aggregate":
            # Odoo 19+ : la regex d'agr\u00e9gation exige code.libell\u00e9 (ex. TA.balance), pas seul TA.
            _push_expr({
                "_line_code":     code,
                "report_line_id": line_id,
                "label":          "balance",
                "engine":         "aggregation",
                "formula":        _agg_formula_with_suffix(formula_agg, "balance"),
                "date_scope":     "strict_range",
            })
            # Budget (m\u00eame formule mais sur .budget de chaque code)
            _push_expr({
                "_line_code":     code,
                "report_line_id": line_id,
                "label":          "budget",
                "engine":         "aggregation",
                "formula":        _agg_formula_with_suffix(formula_agg, "budget"),
                "date_scope":     "strict_range",
            })
            # \u00c9cart
            _push_expr({
                "_line_code":     code,
                "report_line_id": line_id,
                "label":          "ecart",
                "engine":         "aggregation",
                "formula":        f"{code}.budget - {code}.balance",
                "date_scope":     "strict_range",
            })
            # % R\u00e9alisation
            _push_expr({
                "_line_code":     code,
                "report_line_id": line_id,
                "label":          "pct",
                "engine":         "aggregation",
                "formula":        cpc_budget_pct_aggregation_formula(
                    code, budget_pct_meaningful=budget_pct_meaningful
                ),
                "date_scope":     "strict_range",
            })

    verification: dict[str, Any] = {}
    try:
        from verify_cpc_budget_analytique import verify_cpc_budget_analytique_report

        verification = verify_cpc_budget_analytique_report(
            models, db, uid, password, report_id=report_id
        )
    except Exception as e:
        verification = {
            "ok": False,
            "errors": [f"V\u00e9rification automatique impossible : {e}"],
            "warnings": [],
            "report_id": report_id,
        }

    return {
        "report_id":  report_id,
        "col_count":  col_count,
        "line_count": line_count,
        "prior_ids":  prior_ids,
        "filter_written": filter_written,
        "filter_personalization_error": filter_personalization_error,
        "column_errors": column_errors,
        "line_errors":   line_errors,
        "expression_errors": expression_errors,
        "budget_mode":        budget_mode,
        "budget_external_source": budget_external_source,
        "budget_engine_used": budget_engine_used,
        "budget_pct_meaningful": budget_pct_meaningful,
        "creation_warnings": creation_warnings,
        "verification":  verification,
    }
