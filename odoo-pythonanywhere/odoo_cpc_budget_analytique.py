#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
  CPC SYSCOHADA — BUDGET PAR COMPTE ANALYTIQUE — ODOO v19 SaaS (Sénégal)
=============================================================================

  PROBLÈME RÉSOLU :
    Dans le CPC SYSCOHADA natif d'Odoo, dès qu'un filtre analytique est
    appliqué, la colonne Budget disparaît.

  SOLUTION :
    Création d'un rapport personnalisé avec 4 colonnes :
      1. Réalisé          → écritures filtrées par compte analytique
      2. Budget Analytique → budget lié au compte analytique sélectionné
      3. Écart             → Budget - Réalisé
      4. % Réalisation    → Réalisé / Budget × 100

  ARCHITECTURE TECHNIQUE :
    - Les expressions "réalisé" utilisent l'engine account_codes
      avec date_scope = strict_range (respecte le filtre analytique)
    - Les expressions "budget" utilisent l'engine budget si la base l'expose ; sinon
      account_codes (même formule que le réalisé, Odoo 19+ SaaS). Le rapport active filter_budgets /
      filter_budget lorsque le modèle Odoo les expose (comme le P&L Senedoo).
    - Les expressions "%" utilisent l'engine aggregation

  PRÉREQUIS :
    - Module account_budget installé (Comptabilité > Configuration > Budgets)
    - Plan analytique créé
    - Localisation sénégalaise (l10n_sn) installée

=============================================================================
"""

import xmlrpc.client
import sys
import json
import re
from datetime import date, datetime

from personalize_pl_analytic_budget import personalize_pl_analytic_budget_options
from create_cpc_budget_analytique import (
    cpc_budget_pct_aggregation_formula,
    normalize_cpc_account_codes_formula,
)

# =============================================================================
# 🔧 CONFIGURATION — À ADAPTER
# =============================================================================

ODOO_URL = "https://VOTRE_DOMAINE.odoo.com"
DB       = "VOTRE_BASE_DE_DONNEES"
USERNAME = "admin@exemple.com"
API_KEY  = "VOTRE_CLE_API"

# Nom du rapport à créer
REPORT_NAME = "CPC SYSCOHADA — Budget Analytique"

# Exercice fiscal en cours (pour initialisation des budgets de démonstration)
FISCAL_YEAR_START = "2025-01-01"
FISCAL_YEAR_END   = "2025-12-31"

# =============================================================================
# 🔌 CONNEXION
# =============================================================================

def connect():
    print(f"\n{'═'*64}")
    print(f"  CONNEXION ODOO v19  —  {ODOO_URL}")
    print(f"{'═'*64}")
    try:
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
        ver    = common.version().get("server_version", "?")
        uid    = common.authenticate(DB, USERNAME, API_KEY, {})
        if not uid:
            print("  ❌ Authentification échouée")
            sys.exit(1)
        models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object", allow_none=True)
        print(f"  ✅ Connecté — Odoo {ver}  |  UID : {uid}")
        return uid, models
    except Exception as e:
        print(f"  ❌ {e}")
        sys.exit(1)


def rpc(models, uid, model, method, args=None, kw=None):
    """Wrapper XML-RPC."""
    return models.execute_kw(DB, uid, API_KEY, model, method, args or [], kw or {})


# =============================================================================
# 🔍 ÉTAPE 1 — DIAGNOSTIC DE L'ENVIRONNEMENT
# =============================================================================

def diagnose(models, uid):
    print(f"\n{'═'*64}")
    print("  ÉTAPE 1 — DIAGNOSTIC")
    print(f"{'═'*64}\n")
    info = {}

    # --- Module budget
    bud = rpc(models, uid, "ir.module.module", "search_read",
              [[["name", "in", ["account_budget", "account_budget_ml"]],
                ["state", "=", "installed"]]],
              {"fields": ["name", "state"]})
    info["budget_module"] = bud[0]["name"] if bud else None
    status = f"✅ {bud[0]['name']}" if bud else "❌ NON INSTALLÉ (requis !)"
    print(f"  Module budget         : {status}")

    # --- Module localisation Sénégal
    sn = rpc(models, uid, "ir.module.module", "search_read",
             [[["name", "in", ["l10n_sn", "l10n_syscohada"]],
               ["state", "=", "installed"]]],
             {"fields": ["name"]})
    info["l10n"] = [m["name"] for m in sn]
    print(f"  Localisation          : {info['l10n'] or '⚠️  Aucune détectée'}")

    # --- CPC SYSCOHADA existant
    cpc = rpc(models, uid, "account.report", "search_read",
              [[["name", "ilike", "Résultat"]]],
              {"fields": ["id", "name"], "limit": 10})
    info["cpc_reports"] = cpc
    if cpc:
        print(f"  Rapports CPC trouvés  :")
        for r in cpc:
            print(f"    → [{r['id']}] {r['name']}")
    else:
        print("  Rapports CPC          : ⚠️  Aucun (sera créé)")

    # --- Rapport budget analytique déjà créé ?
    existing = rpc(models, uid, "account.report", "search_read",
                   [[["name", "ilike", "Budget Analytique"]]],
                   {"fields": ["id", "name"]})
    info["existing_custom"] = existing
    if existing:
        print(f"  Rapport personnalisé  : ✅ Déjà existant [{existing[0]['id']}]")

    # --- Plans analytiques
    plans = rpc(models, uid, "account.analytic.plan", "search_read",
                [[]], {"fields": ["id", "name"], "limit": 5})
    info["analytic_plans"] = plans
    print(f"  Plans analytiques     : {len(plans)} trouvé(s)")
    for p in plans[:3]:
        print(f"    → [{p['id']}] {p['name']}")

    # --- Comptes analytiques
    analytic_accounts = rpc(models, uid, "account.analytic.account", "search_read",
                            [[]], {"fields": ["id", "name", "code"], "limit": 10})
    info["analytic_accounts"] = analytic_accounts
    print(f"  Comptes analytiques   : {len(analytic_accounts)} trouvé(s)")
    for a in analytic_accounts[:5]:
        print(f"    → [{a['id']}] {a.get('code',''):<10} {a['name']}")

    # --- Budgets existants
    budgets = rpc(models, uid, "crossovered.budget", "search_read",
                  [[]], {"fields": ["id", "name", "state"], "limit": 5})
    info["budgets"] = budgets
    print(f"  Budgets déclarés      : {len(budgets)}")
    for b in budgets[:3]:
        print(f"    → [{b['id']}] {b['name']} ({b['state']})")

    # --- Colonnes du rapport natif
    if cpc:
        cols = rpc(models, uid, "account.report.column", "search_read",
                   [[["report_id", "=", cpc[0]["id"]]]],
                   {"fields": ["name", "expression_label", "sequence"],
                    "order": "sequence asc"})
        info["native_columns"] = cols
        print(f"\n  Colonnes du CPC natif [{cpc[0]['id']}] :")
        for c in cols:
            print(f"    [{c['sequence']}] {c['name']:<35} → {c['expression_label']}")

    print()
    return info


# =============================================================================
# 🏗️  ÉTAPE 2 — VÉRIFICATION / INSTALLATION DU MODULE BUDGET
# =============================================================================

def ensure_budget_module(models, uid, info):
    if info.get("budget_module"):
        print(f"  ✅ Module {info['budget_module']} déjà installé")
        return
    print("  ⚠️  Module account_budget requis — tentative d'installation...")
    try:
        mod_id = rpc(models, uid, "ir.module.module", "search",
                     [[["name", "=", "account_budget"]]])[0]
        rpc(models, uid, "ir.module.module", "button_immediate_install", [[mod_id]])
        print("  ✅ Module account_budget installé")
    except Exception as e:
        print(f"  ❌ Impossible d'installer le module : {e}")
        print("     → Allez dans Apps, cherchez 'Budget' et installez-le manuellement")


# =============================================================================
# 🏗️  ÉTAPE 3 — CRÉATION DU RAPPORT PERSONNALISÉ
# =============================================================================

def get_syscohada_cpc_id(models, uid, info):
    """Retourne l'ID du CPC SYSCOHADA natif ou None."""
    if info["cpc_reports"]:
        # Privilégier le rapport le plus proche du CPC SYSCOHADA
        for r in info["cpc_reports"]:
            if "résultat" in r["name"].lower() or "syscohada" in r["name"].lower():
                return r["id"]
        return info["cpc_reports"][0]["id"]
    return None


def delete_existing_report(models, uid):
    """Supprime le rapport personnalisé si déjà existant."""
    existing = rpc(models, uid, "account.report", "search",
                   [[["name", "=", REPORT_NAME]]])
    if existing:
        # Supprimer colonnes et lignes d'abord
        cols = rpc(models, uid, "account.report.column", "search",
                   [[["report_id", "in", existing]]])
        if cols:
            rpc(models, uid, "account.report.column", "unlink", [cols])
        lines = rpc(models, uid, "account.report.line", "search",
                    [[["report_id", "in", existing]]])
        if lines:
            # Supprimer expressions d'abord
            exprs = rpc(models, uid, "account.report.expression", "search",
                        [[["report_line_id", "in", lines]]])
            if exprs:
                rpc(models, uid, "account.report.expression", "unlink", [exprs])
            rpc(models, uid, "account.report.line", "unlink", [lines])
        rpc(models, uid, "account.report", "unlink", [existing])
        print(f"  🗑️  Rapport existant supprimé ({len(existing)} rapport(s))")


def create_main_report(models, uid, parent_id):
    """Crée le rapport principal account.report."""
    print(f"\n{'═'*64}")
    print("  ÉTAPE 3 — CRÉATION DU RAPPORT PRINCIPAL")
    print(f"{'═'*64}\n")

    delete_existing_report(models, uid)

    vals = {
        "name"                        : REPORT_NAME,
        "filter_date_range"           : True,
        "filter_analytic"             : True,        # ← FILTRE ANALYTIQUE ACTIF
        "filter_journals"             : True,
        "filter_unfold_all"           : True,
        "filter_show_draft"           : False,
        "default_opening_date_filter" : "this_year",
        "search_bar"                  : True,
        "load_more_limit"             : 80,
        "prefix_groups_count"         : 0,
    }

    # Tenter d'hériter du CPC natif si disponible
    if parent_id:
        vals["root_report_id"] = parent_id
        print(f"  Héritage du CPC natif  : [{parent_id}]")

    report_id = rpc(models, uid, "account.report", "create", [vals])
    print(f"  ✅ Rapport créé        : ID {report_id}")
    print(f"     Nom                 : {REPORT_NAME}")
    print(f"     Filtre analytique   : activé\n")
    return report_id


# =============================================================================
# 📊 ÉTAPE 4 — CRÉATION DES 4 COLONNES
# =============================================================================

def create_columns(models, uid, report_id):
    """
    Crée les 4 colonnes du rapport :
      1. Réalisé           : écritures comptables filtrées par analytique
      2. Budget Analytique : budget du compte analytique sélectionné
      3. Écart             : Budget - Réalisé
      4. % Réalisation     : (Réalisé / Budget) × 100
    """
    print(f"{'═'*64}")
    print("  ÉTAPE 4 — CRÉATION DES COLONNES")
    print(f"{'═'*64}\n")

    # Nettoyage préalable
    old = rpc(models, uid, "account.report.column", "search",
              [[["report_id", "=", report_id]]])
    if old:
        rpc(models, uid, "account.report.column", "unlink", [old])

    columns_def = [
        # ── COL 1 : RÉALISÉ ───────────────────────────────────────────────
        # engine account_codes respecte filter_analytic → OK
        {
            "name"             : "Réalisé",
            "expression_label" : "balance",
            "figure_type"      : "monetary",
            "report_id"        : report_id,
            "sequence"         : 10,
            "blank_if_zero"    : False,
            "sortable"         : True,
        },
        # ── COL 2 : BUDGET ANALYTIQUE ─────────────────────────────────────
        # Moteur natif budget → crossovered.budget.lines (lignes d'expressions).
        {
            "name"             : "Budget",
            "expression_label" : "budget",
            "figure_type"      : "monetary",
            "report_id"        : report_id,
            "sequence"         : 20,
            "blank_if_zero"    : False,
            "sortable"         : True,
        },
        # ── COL 3 : ÉCART ─────────────────────────────────────────────────
        {
            "name"             : "Écart",
            "expression_label" : "ecart",
            "figure_type"      : "monetary",
            "report_id"        : report_id,
            "sequence"         : 30,
            "blank_if_zero"    : False,
            "sortable"         : True,
        },
        # ── COL 4 : % RÉALISATION ─────────────────────────────────────────
        {
            "name"             : "% Réalisation",
            "expression_label" : "pct",
            "figure_type"      : "percentage",
            "report_id"        : report_id,
            "sequence"         : 40,
            "blank_if_zero"    : False,
            "sortable"         : True,
        },
    ]

    col_ids = []
    for col in columns_def:
        try:
            cid = rpc(models, uid, "account.report.column", "create", [col])
            col_ids.append(cid)
            print(f"  ✅ [{col['sequence']:02}] {col['name']:<25} → {col['expression_label']}")
        except Exception as e:
            print(f"  ❌ Colonne {col['name']} : {e}")

    print(f"\n  {len(col_ids)}/4 colonnes créées\n")
    return col_ids


# =============================================================================
# 📋 ÉTAPE 5 — STRUCTURE DU CPC SYSCOHADA (lignes + expressions)
# =============================================================================

# Structure du CPC SYSCOHADA — Plan comptable OHADA/Sénégal
# Format : (code_ligne, libellé, nature, formule_account_codes, formule_aggregation)
# nature : 'account' → engine account_codes | 'aggregate' → engine aggregation

def _agg_formula_with_suffix(formula_agg: str, suffix: str) -> str:
    """Référence chaque code CPC (2 lettres) avec .suffix (ex. TA.budget)."""
    return re.sub(r"\b([A-Z]{2})\b", lambda m: f"{m.group(1)}.{suffix}", formula_agg)


CPC_STRUCTURE = [
    # ── PRODUITS D'EXPLOITATION ────────────────────────────────────────────────
    ("TA",  "Ventes de marchandises",                    "account",   "^701,^7011,^7012,^7013",     None),
    ("RA",  "Achats de marchandises",                    "account",   "^601,^6011,^6012,^6013",     None),
    ("RB",  "Variation de stocks de marchandises",       "account",   "^6031",                      None),
    ("XA",  "MARGE COMMERCIALE (TA-RA-RB)",              "aggregate", None,  "TA - RA - RB"),
    ("TB",  "Ventes de produits fabriqués",              "account",   "^702,^703,^7021,^7031",      None),
    ("TC",  "Travaux, services vendus",                  "account",   "^704,^705,^706,^707,^708",   None),
    ("TD",  "Produits accessoires",                      "account",   "^709",                       None),
    ("XB",  "CHIFFRE D'AFFAIRES (TA+TB+TC+TD)",          "aggregate", None,  "TA + TB + TC + TD"),
    ("TE",  "Production stockée (ou déstockée)",         "account",   "^6032,^6033",                None),
    ("TF",  "Production immobilisée",                    "account",   "^72",                        None),
    ("TG",  "Subventions d'exploitation",                "account",   "^71",                        None),
    ("TH",  "Autres produits",                           "account",   "^75",                        None),
    ("TI",  "Transferts de charges d'exploitation",      "account",   "^781",                       None),
    # ── CHARGES D'EXPLOITATION ────────────────────────────────────────────────
    ("RC",  "Achats de matières premières",              "account",   "^602",                       None),
    ("RD",  "Variation de stocks matières premières",    "account",   "^6032",                      None),
    ("RE",  "Autres achats",                             "account",   "^604,^605,^608",             None),
    ("RF",  "Variation autres approvisionnements",       "account",   "^6033",                      None),
    ("RG",  "Transports",                                "account",   "^61",                        None),
    ("RH",  "Services extérieurs",                       "account",   "^62,^63",                    None),
    ("RI",  "Impôts et taxes",                           "account",   "^64",                        None),
    ("RJ",  "Autres charges",                            "account",   "^65",                        None),
    ("XC",  "VALEUR AJOUTÉE (XB+TE+TF+TG+TH+TI-RC-RD-RE-RF-RG-RH-RI-RJ)",
                                                         "aggregate", None,  "XB + TE + TF + TG + TH + TI - RC - RD - RE - RF - RG - RH - RI - RJ"),
    ("RK",  "Charges de personnel",                     "account",   "^66",                        None),
    ("XD",  "EXCÉDENT BRUT D'EXPLOITATION (XC-RK)",     "aggregate", None,  "XC - RK"),
    ("TJ",  "Reprises d'amortissements, provisions",    "account",   "^791,^798",                  None),
    ("RL",  "Dotations amortissements et provisions",   "account",   "^681,^691",                  None),
    ("XE",  "RÉSULTAT D'EXPLOITATION (XD+TJ-RL)",       "aggregate", None,  "XD + TJ - RL"),
    # ── OPÉRATIONS FINANCIÈRES ────────────────────────────────────────────────
    ("TK",  "Revenus financiers",                        "account",   "^77",                        None),
    ("TL",  "Reprises provisions financières",           "account",   "^797",                       None),
    ("TM",  "Transferts de charges financières",         "account",   "^787",                       None),
    ("RM",  "Frais financiers et charges assimilées",   "account",   "^67",                        None),
    ("RN",  "Dotations provisions financières",         "account",   "^697",                       None),
    ("XF",  "RÉSULTAT FINANCIER (TK+TL+TM-RM-RN)",     "aggregate", None,  "TK + TL + TM - RM - RN"),
    ("XG",  "RÉSULTAT DES ACTIVITÉS ORDINAIRES (XE+XF)","aggregate", None,  "XE + XF"),
    # ── HORS ACTIVITÉS ORDINAIRES ─────────────────────────────────────────────
    ("TN",  "Produits HAO",                              "account",   "^88",                        None),
    ("TO",  "Reprises HAO",                              "account",   "^798",                       None),
    ("RO",  "Charges HAO",                               "account",   "^83,^84,^85,^87",            None),
    ("RP",  "Dotations HAO",                             "account",   "^698",                       None),
    ("XH",  "RÉSULTAT HAO (TN+TO-RO-RP)",               "aggregate", None,  "TN + TO - RO - RP"),
    # ── RÉSULTAT NET ──────────────────────────────────────────────────────────
    ("RQ",  "Participation des travailleurs",            "account",   "^869",                       None),
    ("RS",  "Impôts sur le résultat",                   "account",   "^89",                        None),
    ("XI",  "RÉSULTAT NET (XG+XH-RQ-RS)",               "aggregate", None,  "XG + XH - RQ - RS"),
]


def _expression_engine_keys_local(models, uid):
    fg = rpc(models, uid, "account.report.expression", "fields_get", [], {})
    sel = fg.get("engine", {}).get("selection") or []
    return frozenset(
        str(x[0])
        for x in sel
        if isinstance(x, (list, tuple)) and len(x) >= 1 and x[0] is not False
    )


def create_expression_safe(models, uid, expr_vals):
    """Crée une expression avec fallback si champ non supporté."""
    ev = dict(expr_vals)
    eng = (ev.get("engine") or "").strip()
    if eng in ("account_codes", "budget") and ev.get("formula"):
        ev["formula"] = normalize_cpc_account_codes_formula(ev["formula"])
    try:
        return rpc(models, uid, "account.report.expression", "create", [ev])
    except Exception as e:
        # Retry sans champs optionnels
        safe = {k: v for k, v in ev.items()
                if k in ("report_line_id", "label", "engine", "formula", "date_scope")}
        try:
            return rpc(models, uid, "account.report.expression", "create", [safe])
        except Exception as e2:
            print(f"      ⚠️  Expression {expr_vals.get('label')}: {e2}")
            return None


def create_report_lines(models, uid, report_id):
    """Crée toutes les lignes CPC SYSCOHADA avec leurs 4 expressions."""
    print(f"{'═'*64}")
    print("  ÉTAPE 5 — LIGNES CPC SYSCOHADA + EXPRESSIONS")
    print(f"{'═'*64}\n")

    eng_keys = _expression_engine_keys_local(models, uid)
    budget_engine_native = "budget" in eng_keys
    budget_engine = "budget" if budget_engine_native else "account_codes"
    if not budget_engine_native:
        print(
            "  ⚠️  Moteur « budget » absent sur account.report.expression (Odoo 19+ / SaaS) : "
            "colonne Budget = account_codes comme le Réalisé ; % et écart neutralisés sur détail.\n"
        )

    # Nettoyage
    old_lines = rpc(models, uid, "account.report.line", "search",
                    [[["report_id", "=", report_id]]])
    if old_lines:
        old_exprs = rpc(models, uid, "account.report.expression", "search",
                        [[["report_line_id", "in", old_lines]]])
        if old_exprs:
            rpc(models, uid, "account.report.expression", "unlink", [old_exprs])
        rpc(models, uid, "account.report.line", "unlink", [old_lines])
        print(f"  🗑️  {len(old_lines)} lignes préexistantes supprimées\n")

    line_ids = []
    seq = 10

    for code, label, nature, formula_ac, formula_agg in CPC_STRUCTURE:
        is_total = code.startswith("X")
        try:
            # Odoo 19+ : pas de champ unfoldable ; hierarchy_level est calculé.
            line_vals = {
                "name"         : f"{code} — {label}",
                "report_id"    : report_id,
                "code"         : code,
                "sequence"     : seq,
                "foldable"     : not is_total,
                "hide_if_zero" : False,
            }
            try:
                line_id = rpc(models, uid, "account.report.line", "create", [line_vals])
            except Exception as e1:
                minimal = {
                    "name": line_vals["name"],
                    "report_id": report_id,
                    "code": code,
                    "sequence": seq,
                }
                try:
                    line_id = rpc(models, uid, "account.report.line", "create", [minimal])
                    print(f"      ⚠️  Ligne {code} : créée en minimal ({e1})")
                except Exception as e2:
                    raise RuntimeError(f"{e1} | minimal: {e2}") from e2
            line_ids.append(line_id)
            seq += 10

            # ── EXPRESSIONS PAR COLONNE ──────────────────────────────────

            if nature == "account":
                # COL 1 : RÉALISÉ (balance = crédit - débit pour produits, débit - crédit pour charges)
                create_expression_safe(models, uid, {
                    "report_line_id" : line_id,
                    "label"          : "balance",
                    "engine"         : "account_codes",
                    "formula"        : formula_ac,
                    "date_scope"     : "strict_range",
                    # subformula : C = solde créditeur (produits), D = débit (charges)
                    # On laisse le moteur calculer le solde net
                })

                # COL 2 : BUDGET — engine budget (crossovered.budget.lines)
                create_expression_safe(models, uid, {
                    "report_line_id" : line_id,
                    "label"          : "budget",
                    "engine"         : budget_engine,
                    "formula"        : formula_ac,
                    "date_scope"     : "strict_range",
                })

                # COL 3 : ÉCART (Budget - Réalisé) via aggregation
                create_expression_safe(models, uid, {
                    "report_line_id" : line_id,
                    "label"          : "ecart",
                    "engine"         : "aggregation",
                    "formula"        : f"{code}.budget - {code}.balance",
                    "date_scope"     : "strict_range",
                })

                # COL 4 : % RÉALISATION
                # if_other_is_zero gère la division par zéro
                create_expression_safe(models, uid, {
                    "report_line_id" : line_id,
                    "label"          : "pct",
                    "engine"         : "aggregation",
                    "formula"        : cpc_budget_pct_aggregation_formula(
                        code, budget_engine_native=budget_engine_native
                    ),
                    "date_scope"     : "strict_range",
                })

            elif nature == "aggregate":
                create_expression_safe(models, uid, {
                    "report_line_id": line_id,
                    "label":          "balance",
                    "engine":         "aggregation",
                    "formula":        formula_agg,
                    "date_scope":     "strict_range",
                })
                create_expression_safe(models, uid, {
                    "report_line_id": line_id,
                    "label":          "budget",
                    "engine":         "aggregation",
                    "formula":        _agg_formula_with_suffix(formula_agg, "budget"),
                    "date_scope":     "strict_range",
                })
                create_expression_safe(models, uid, {
                    "report_line_id": line_id,
                    "label":          "ecart",
                    "engine":         "aggregation",
                    "formula":        f"{code}.budget - {code}.balance",
                    "date_scope":     "strict_range",
                })
                create_expression_safe(models, uid, {
                    "report_line_id": line_id,
                    "label":          "pct",
                    "engine":         "aggregation",
                    "formula":        cpc_budget_pct_aggregation_formula(
                        code, budget_engine_native=budget_engine_native
                    ),
                    "date_scope":     "strict_range",
                })

            icon = "Σ" if is_total else "·"
            print(f"  {icon} [{code:<4}] {label[:55]:<55}")

        except Exception as e:
            print(f"  ❌ [{code}] {e}")

    print(f"\n  ✅ {len(line_ids)}/{len(CPC_STRUCTURE)} lignes créées\n")
    return line_ids


# =============================================================================
# 💰 ÉTAPE 6 — CRÉATION DE BUDGETS DE DÉMONSTRATION ANALYTIQUES
# =============================================================================

def create_demo_analytic_budget(models, uid, info):
    """
    Crée un budget de démonstration lié aux comptes analytiques existants.
    Utile pour tester le rapport immédiatement après installation.
    """
    print(f"{'═'*64}")
    print("  ÉTAPE 6 — BUDGET ANALYTIQUE DE DÉMONSTRATION")
    print(f"{'═'*64}\n")

    if not info.get("analytic_accounts"):
        print("  ⚠️  Aucun compte analytique — création d'un compte de test\n")
        plan_id = None
        if info.get("analytic_plans"):
            plan_id = info["analytic_plans"][0]["id"]
        else:
            # Créer un plan analytique
            plan_id = rpc(models, uid, "account.analytic.plan", "create",
                          [{"name": "Projets", "default_applicability": "optional"}])

        demo_aa = rpc(models, uid, "account.analytic.account", "create",
                      [{"name": "Projet Demo", "code": "DEMO001", "plan_id": plan_id}])
        info["analytic_accounts"] = [{"id": demo_aa, "name": "Projet Demo", "code": "DEMO001"}]
        print(f"  ✅ Compte analytique créé : DEMO001 — Projet Demo (ID: {demo_aa})")

    analytic_id = info["analytic_accounts"][0]["id"]
    analytic_name = info["analytic_accounts"][0]["name"]

    # Créer ou retrouver des positions budgétaires (budget posts)
    budget_positions = {
        "Ventes"           : ["701", "702", "703", "704", "705"],
        "Achats"           : ["601", "602", "604", "605"],
        "Personnel"        : ["661", "662", "663", "664"],
        "Charges externes" : ["61", "62", "63", "64", "65"],
        "Charges financ."  : ["671", "672", "673"],
        "Produits financ." : ["771", "772"],
    }

    post_ids = []
    for pos_name, acc_codes in budget_positions.items():
        # Chercher les comptes correspondants
        acc_ids = rpc(models, uid, "account.account", "search",
                      [[["code", "like", acc_codes[0][:2]]]])[:5]
        if not acc_ids:
            continue

        existing_post = rpc(models, uid, "account.budget.post", "search",
                            [[["name", "=", pos_name]]])
        if existing_post:
            post_ids.append((pos_name, existing_post[0]))
        else:
            try:
                pid = rpc(models, uid, "account.budget.post", "create",
                          [{"name": pos_name, "account_ids": [(6, 0, acc_ids)]}])
                post_ids.append((pos_name, pid))
                print(f"  ✅ Position budgétaire : {pos_name}")
            except Exception as e:
                print(f"  ⚠️  Position {pos_name} : {e}")

    # Montants de budget de démonstration (en FCFA)
    demo_amounts = {
        "Ventes"           : 50_000_000,
        "Achats"           : 20_000_000,
        "Personnel"        : 12_000_000,
        "Charges externes" :  8_000_000,
        "Charges financ."  :  2_000_000,
        "Produits financ." :  1_500_000,
    }

    # Créer le budget principal
    budget_name = f"Budget {FISCAL_YEAR_START[:4]} — {analytic_name}"
    existing_b = rpc(models, uid, "crossovered.budget", "search",
                     [[["name", "=", budget_name]]])
    if existing_b:
        rpc(models, uid, "crossovered.budget", "unlink", [existing_b])

    try:
        budget_lines_vals = []
        for pos_name, pos_id in post_ids:
            budget_lines_vals.append((0, 0, {
                "general_budget_id"  : pos_id,
                "analytic_account_id": analytic_id,
                "date_from"          : FISCAL_YEAR_START,
                "date_to"            : FISCAL_YEAR_END,
                "planned_amount"     : demo_amounts.get(pos_name, 1_000_000),
            }))

        budget_id = rpc(models, uid, "crossovered.budget", "create",
                        [{"name"              : budget_name,
                          "date_from"         : FISCAL_YEAR_START,
                          "date_to"           : FISCAL_YEAR_END,
                          "crossovered_budget_line": budget_lines_vals}])

        # Confirmer le budget
        try:
            rpc(models, uid, "crossovered.budget", "action_budget_confirm", [[budget_id]])
        except Exception:
            pass  # Peut ne pas exister en v19

        print(f"\n  ✅ Budget créé : [{budget_id}] {budget_name}")
        print(f"     Compte analytique : {analytic_name}")
        print(f"     Période : {FISCAL_YEAR_START} → {FISCAL_YEAR_END}")
        print(f"     {len(budget_lines_vals)} lignes de budget\n")
        return budget_id, analytic_id

    except Exception as e:
        print(f"  ❌ Création budget : {e}")
        return None, analytic_id


# =============================================================================
# 🔗 ÉTAPE 7 — AJOUT AU MENU
# =============================================================================

def add_to_menu(models, uid, report_id):
    """Ajoute le rapport dans le menu Comptabilité > Rapports."""
    print(f"{'═'*64}")
    print("  ÉTAPE 7 — MENU")
    print(f"{'═'*64}\n")

    try:
        # Trouver le menu parent
        parent = rpc(models, uid, "ir.ui.menu", "search_read",
                     [[["complete_name", "ilike", "Rapports"],
                       ["complete_name", "ilike", "Comptabilité"]]],
                     {"fields": ["id", "complete_name"], "limit": 3})
        if not parent:
            parent = rpc(models, uid, "ir.ui.menu", "search_read",
                         [[["name", "ilike", "Reports"]]],
                         {"fields": ["id", "complete_name"], "limit": 3})

        if not parent:
            print("  ⚠️  Menu parent non trouvé — rapport accessible via URL directe\n")
            return

        print(f"  Menu parent : {parent[0]['complete_name']}")

        # Supprimer l'ancienne entrée si elle existe
        old_menu = rpc(models, uid, "ir.ui.menu", "search",
                       [[["name", "=", REPORT_NAME]]])
        if old_menu:
            rpc(models, uid, "ir.ui.menu", "unlink", [old_menu])

        # Créer l'action
        action_id = rpc(models, uid, "ir.actions.client", "create",
                        [{"name"    : REPORT_NAME,
                          "tag"     : "account_report",
                          "context" : json.dumps({"report_id": report_id})}])

        # Créer l'entrée de menu
        menu_id = rpc(models, uid, "ir.ui.menu", "create",
                      [{"name"      : REPORT_NAME,
                        "parent_id" : parent[0]["id"],
                        "action"    : f"ir.actions.client,{action_id}",
                        "sequence"  : 60}])

        print(f"  ✅ Entrée de menu créée (ID: {menu_id})\n")

    except Exception as e:
        print(f"  ⚠️  Menu : {e}\n")


# =============================================================================
# 📊 RÉSUMÉ FINAL
# =============================================================================

def print_summary(models, uid, report_id, budget_id, analytic_id):
    print(f"\n{'═'*64}")
    print("  RÉSUMÉ FINAL")
    print(f"{'═'*64}\n")

    report = rpc(models, uid, "account.report", "read",
                 [[report_id]], {"fields": ["name", "filter_analytic"]})[0]
    cols   = rpc(models, uid, "account.report.column", "search_read",
                 [[["report_id", "=", report_id]]],
                 {"fields": ["sequence", "name", "expression_label"],
                  "order": "sequence asc"})
    lines  = rpc(models, uid, "account.report.line", "search",
                 [[["report_id", "=", report_id]]])

    print(f"  Rapport         : {report['name']}")
    print(f"  ID              : {report_id}")
    print(f"  Filtre analytique : {'✅ Activé' if report['filter_analytic'] else '❌'}")
    print(f"  Lignes SYSCOHADA: {len(lines)}")
    print(f"\n  Colonnes :")
    for c in cols:
        print(f"    [{c['sequence']:02}] {c['name']:<25} → {c['expression_label']}")

    if budget_id:
        print(f"\n  Budget demo     : ID {budget_id}")
    if analytic_id:
        print(f"  Compte analytique test : ID {analytic_id}")

    print(f"""
  ┌─────────────────────────────────────────────────────────┐
  │  UTILISATION DANS ODOO                                   │
  │                                                          │
  │  1. Comptabilité → Rapports → {REPORT_NAME[:26]:<26}│
  │                                                          │
  │  2. Cliquer sur "Filtres" : période, budget (crossovered) │
  │     et analytique — les montants viennent des modèles    │
  │     Odoo (aucune table de synchro externe).              │
  │                                                          │
  │  3. Les 4 colonnes s'affichent :                         │
  │     Réalisé | Budget | Écart | % Réalisation             │
  │                                                          │
  │  URL directe :                                           │
  │  {ODOO_URL}/odoo/accounting/reports/{report_id}         │
  └─────────────────────────────────────────────────────────┘

  ⚠️  Si la colonne Budget reste vide : vérifier qu'un budget est
     sélectionné dans les filtres du rapport et que les lignes
     crossovered.budget.lines portent le bon compte analytique.
""")


# =============================================================================
# 🚀 MAIN
# =============================================================================

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║   CPC SYSCOHADA — BUDGET ANALYTIQUE — ODOO v19 SaaS          ║
║   Sénégal — Plan comptable OHADA                             ║
╚══════════════════════════════════════════════════════════════╝""")

    # 1. Connexion
    uid, models = connect()

    # 2. Diagnostic
    info = diagnose(models, uid)

    # 3. Budget module check
    ensure_budget_module(models, uid, info)

    # 4. CPC natif
    parent_id = get_syscohada_cpc_id(models, uid, info)

    # 5. Rapport principal
    report_id = create_main_report(models, uid, parent_id)

    # 6. Colonnes
    create_columns(models, uid, report_id)

    # 7. Lignes SYSCOHADA
    create_report_lines(models, uid, report_id)

    # 8. Filtres budgets + analytique (même logique que la toolbox Senedoo)
    try:
        opt = personalize_pl_analytic_budget_options(
            models, DB, uid, API_KEY, report_id, enable_budget_filter=True
        )
        written = opt.get("written") or {}
        if written:
            print(f"\n  ✅ Filtres rapport : {written}\n")
    except Exception as e:
        print(f"\n  ⚠️  Filtres budgets / analytique : {e}\n")

    # 9. Budget de démonstration
    budget_id, analytic_id = create_demo_analytic_budget(models, uid, info)

    # 10. Menu
    add_to_menu(models, uid, report_id)

    # 11. Résumé
    print_summary(models, uid, report_id, budget_id, analytic_id)


# =============================================================================
# USAGE EN MODE INTERACTIF (appel depuis Cursor ou REPL)
# =============================================================================
# Pour réactiver filter_budgets sur un rapport existant :
#   python personalize_pl_analytic_budget.py --report-id <id>
# =============================================================================

if __name__ == "__main__":
    main()
