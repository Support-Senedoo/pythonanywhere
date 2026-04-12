"""
Crée dans Odoo (via XML-RPC) un wizard natif « CPC Budget Analytique ».

Le wizard est un modèle manuel (x_cpc_budget_wizard) avec :
  - Compte analytique, Période Du/Au, Budget
  - Bouton « Calculer » → server action Python qui :
      1. Lit account.move.line (analytic filtered) → calcule le réalisé CPC
      2. Lit account.report.budget.item → calcule le budget CPC
      3. Écrit account.report.external.value (colonne Budget du rapport CPC)
      4. Ouvre le rapport CPC dans Odoo
  - Menu : Comptabilité > Rapports > CPC Budget Analytique (Senedoo)

Aucune dépendance module custom — fonctionne sur Odoo 17-19 SaaS Enterprise avec Studio.

Usage Flask toolbox (action staff.py) :
    from create_cpc_odoo_wizard import create_cpc_wizard, purge_cpc_wizard, cpc_wizard_exists
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WIZARD_MODEL   = "x_cpc_budget_wizard"
WIZARD_NAME    = "CPC Budget Analytique"
WIZARD_MENU_LABEL = "CPC Budget Analytique (Senedoo)"
CPC_REPORT_NAME_LIKE = "CPC SYSCOHADA"        # recherche ilike dans account.report
EXTERNAL_EXPR_LABEL  = "budget_analytique"    # label expression externe à peupler

# ---------------------------------------------------------------------------
# Structure CPC SYSCOHADA (identique à create_cpc_budget_analytique._CPC_STRUCTURE)
# Format : (code, libellé, nature, formule_account_codes, formule_aggregation)
# nature 'account'   -> lignes de détail (préfixes de comptes)
# nature 'aggregate' -> totaux calculés depuis les lignes de détail
# ---------------------------------------------------------------------------
_CPC_STRUCTURE = [
    # -- PRODUITS D'EXPLOITATION --
    ("TA", "Ventes de marchandises",              "account",   "^701,^7011,^7012,^7013",   None),
    ("RA", "Achats de marchandises",              "account",   "^601,^6011,^6012,^6013",   None),
    ("RB", "Variation de stocks marchandises",    "account",   "^6031",                    None),
    ("XA", "MARGE COMMERCIALE (TA-RA-RB)",        "aggregate", None, "TA - RA - RB"),
    ("TB", "Ventes de produits fabriques",        "account",   "^702,^703,^7021,^7031",    None),
    ("TC", "Travaux, services vendus",            "account",   "^704,^705,^706,^707,^708", None),
    ("TD", "Produits accessoires",                "account",   "^709",                     None),
    ("XB", "CHIFFRE D'AFFAIRES (TA+TB+TC+TD)",   "aggregate", None, "TA + TB + TC + TD"),
    ("TE", "Production stockee (ou destockee)",   "account",   "^6032,^6033",              None),
    ("TF", "Production immobilisee",              "account",   "^72",                      None),
    ("TG", "Subventions d'exploitation",          "account",   "^71",                      None),
    ("TH", "Autres produits",                     "account",   "^75",                      None),
    ("TI", "Transferts de charges exploitation",  "account",   "^781",                     None),
    # -- CHARGES D'EXPLOITATION --
    ("RC", "Achats de matieres premieres",        "account",   "^602",                     None),
    ("RD", "Variation stocks matieres premieres", "account",   "^6032",                    None),
    ("RE", "Autres achats",                       "account",   "^604,^605,^608",            None),
    ("RF", "Variation autres approvisionnements", "account",   "^6033",                    None),
    ("RG", "Transports",                          "account",   "^61",                      None),
    ("RH", "Services exterieurs",                 "account",   "^62,^63",                  None),
    ("RI", "Impots et taxes",                     "account",   "^64",                      None),
    ("RJ", "Autres charges",                      "account",   "^65",                      None),
    ("XC", "VALEUR AJOUTEE",                      "aggregate", None,
     "XB + TE + TF + TG + TH + TI - RC - RD - RE - RF - RG - RH - RI - RJ"),
    ("RK", "Charges de personnel",                "account",   "^66",                      None),
    ("XD", "EXCEDENT BRUT EXPLOITATION (XC-RK)", "aggregate", None, "XC - RK"),
    ("TJ", "Reprises amortissements, provisions", "account",   "^791,^798",                None),
    ("RL", "Dotations amortissements provisions", "account",   "^681,^691",                None),
    ("XE", "RESULTAT D'EXPLOITATION (XD+TJ-RL)", "aggregate", None, "XD + TJ - RL"),
    # -- OPERATIONS FINANCIERES --
    ("TK", "Revenus financiers",                  "account",   "^77",                      None),
    ("TL", "Reprises provisions financieres",     "account",   "^797",                     None),
    ("TM", "Transferts de charges financieres",   "account",   "^787",                     None),
    ("RM", "Frais financiers et assimiles",       "account",   "^67",                      None),
    ("RN", "Dotations provisions financieres",    "account",   "^697",                     None),
    ("XF", "RESULTAT FINANCIER",                  "aggregate", None, "TK + TL + TM - RM - RN"),
    ("XG", "RESULTAT ACTIVITES ORDINAIRES (XE+XF)", "aggregate", None, "XE + XF"),
    # -- HORS ACTIVITES ORDINAIRES --
    ("TN", "Produits HAO",                        "account",   "^88",                      None),
    ("TO", "Reprises HAO",                        "account",   "^798",                     None),
    ("RO", "Charges HAO",                         "account",   "^83,^84,^85,^87",          None),
    ("RP", "Dotations HAO",                       "account",   "^698",                     None),
    ("XH", "RESULTAT HAO",                        "aggregate", None, "TN + TO - RO - RP"),
    # -- RESULTAT NET --
    ("RQ", "Participation des travailleurs",      "account",   "^869",                     None),
    ("RS", "Impots sur le resultat",              "account",   "^89",                      None),
    ("XI", "RESULTAT NET (XG+XH-RQ-RS)",          "aggregate", None, "XG + XH - RQ - RS"),
]

# Signe CPC par code :
#   T* = produits/income → Odoo balance négatif pour les crédits → on inverse (sign=-1)
#   R* = charges/expense → Odoo balance positif pour les débits → on garde (sign=+1)
#   X* = agrégats → calculés depuis les autres (non applicable ici)
_LINE_SIGN = {
    code: (-1 if code.startswith("T") else 1)
    for code, *_ in _CPC_STRUCTURE
    if not code.startswith("X")
}

# ---------------------------------------------------------------------------
# Code Python de la server action (exécuté DANS Odoo, avec `env`)
# Ce code est stocké dans ir.actions.server.code
# ---------------------------------------------------------------------------

# NOTE : Ce string doit être indentation-neutre (pas d'indentation initiale)
# car Odoo exécute le code avec exec() dans son propre contexte.
_SERVER_ACTION_CODE = r'''
import json as _json
import re as _re

# ------------------------------------------------------------------ helpers
def _ek(model, method, args=None, kwargs=None):
    return getattr(env[model], method)(*(args or []), **(kwargs or {}))

def _sum_formula(formula_str, amounts_by_code):
    """Somme les montants des comptes dont le code commence par un prefixe de la formule."""
    total = 0.0
    for raw in (formula_str or "").split(","):
        pref = raw.strip().lstrip("^")
        if not pref:
            continue
        for code, amt in amounts_by_code.items():
            if code.startswith(pref):
                total += amt
    return total

def _eval_aggregate(formula_str, line_vals):
    """Evalue une formule d'agregation type 'TA - RA - RB' sur line_vals dict {code: val}."""
    tokens = _re.split(r'([+\-])', (formula_str or "").strip())
    result = 0.0
    sign = 1
    for tok in tokens:
        tok = tok.strip()
        if tok == '+':
            sign = 1
        elif tok == '-':
            sign = -1
        elif tok:
            result += sign * float(line_vals.get(tok, 0.0))
    return result

# ------------------------------------------------------------------ wizard fields
wizard = record
analytic_id = int(wizard.x_analytic_account_id.id) if wizard.x_analytic_account_id else 0
date_from = str(wizard.x_date_from) if wizard.x_date_from else ''
date_to   = str(wizard.x_date_to)   if wizard.x_date_to   else ''
budget_id = int(wizard.x_budget_id.id) if wizard.x_budget_id else 0

if not analytic_id or not date_from or not date_to:
    raise UserError("Veuillez remplir tous les champs obligatoires (analytique, dates).")

# ------------------------------------------------------------------ CPC structure
CPC_STRUCTURE = ''' + repr(_CPC_STRUCTURE) + r'''
LINE_SIGN = ''' + repr(_LINE_SIGN) + r'''

# ------------------------------------------------------------------ find CPC report
cpc_reports = env['account.report'].search([('name', 'ilike', '''' + CPC_REPORT_NAME_LIKE + r'''')], limit=5)
if not cpc_reports:
    raise UserError(
        "Rapport CPC SYSCOHADA introuvable dans Odoo. "
        "Utilisez la toolbox Senedoo pour installer le rapport CPC d'abord."
    )
cpc_report = cpc_reports[0]
cpc_report_id = cpc_report.id

# Récuperer les expressions externes (label='budget_analytique') par code de ligne
expr_by_code = {}
for line in env['account.report.line'].search([('report_id', '=', cpc_report_id)]):
    if not line.code:
        continue
    for expr in env['account.report.expression'].search([
        ('report_line_id', '=', line.id),
        ('label', '=', '''' + EXTERNAL_EXPR_LABEL + r''''),
    ]):
        expr_by_code[line.code] = expr.id

# ------------------------------------------------------------------ realized (analytic filtered)
domain_ml = [
    ('date', '>=', date_from),
    ('date', '<=', date_to),
    ('parent_state', '=', 'posted'),
    ('analytic_distribution', '!=', False),
]
# Essayer un filtre serveur sur analytic_distribution
analytic_str = str(analytic_id)
for test_domain in [
    domain_ml + [('analytic_distribution', 'in', [analytic_str])],
    domain_ml + [('analytic_distribution', 'in', [analytic_id])],
]:
    try:
        env['account.move.line'].search_count(test_domain)
        domain_ml = test_domain
        break
    except Exception:
        pass

move_lines = env['account.move.line'].search_read(
    domain_ml,
    ['account_id', 'debit', 'credit', 'balance', 'analytic_distribution'],
    limit=0,
)

# Agréger par code compte (part prorata analytique)
realized_by_code = {}
for ml in move_lines:
    raw_dist = ml.get('analytic_distribution')
    if not raw_dist:
        continue
    if isinstance(raw_dist, str):
        try:
            raw_dist = _json.loads(raw_dist)
        except Exception:
            continue
    if not isinstance(raw_dist, dict):
        continue

    matched_pct = 0.0
    for key, pct in raw_dist.items():
        key_s = str(key)
        if key_s == analytic_str or analytic_str in key_s.split(','):
            try:
                matched_pct += float(pct)
            except Exception:
                pass

    if matched_pct <= 0:
        continue

    acc_tuple = ml.get('account_id')
    if not acc_tuple:
        continue
    acc_id = acc_tuple[0] if isinstance(acc_tuple, (list, tuple)) else int(acc_tuple)
    acc = env['account.account'].browse(acc_id)
    code = (acc.code or '').strip()
    if not code:
        continue

    balance = float(ml.get('balance') or 0.0)
    amt = balance * (matched_pct / 100.0)
    realized_by_code[code] = realized_by_code.get(code, 0.0) + amt

# ------------------------------------------------------------------ budget
fg_bi = env['account.report.budget.item'].fields_get()
budget_by_code = {}

if 'account_id' in fg_bi:
    # Odoo 19+ : account.report.budget.item a un champ account_id direct
    amt_field = next(
        (f for f in ('value', 'budget_amount', 'amount', 'planned_amount') if f in fg_bi),
        None,
    )
    if amt_field:
        b_domain = []
        # Filtrer par budget parent si fourni
        parent_field = next(
            (f for f in ('budget_id', 'report_budget_id', 'budget') if f in fg_bi),
            None,
        )
        if parent_field and budget_id:
            b_domain.append((parent_field, '=', budget_id))
        # Filtrer par chevauchement de période si les champs existent
        if 'date_from' in fg_bi and 'date_to' in fg_bi and date_from and date_to:
            b_domain += [('date_from', '<=', date_to), ('date_to', '>=', date_from)]
        elif 'date' in fg_bi and date_from and date_to:
            b_domain += [('date', '>=', date_from), ('date', '<=', date_to)]

        items = env['account.report.budget.item'].search_read(
            b_domain, ['account_id', amt_field], limit=0,
        )
        for item in items:
            acc_tuple = item.get('account_id')
            if not acc_tuple:
                continue
            acc_id = acc_tuple[0] if isinstance(acc_tuple, (list, tuple)) else int(acc_tuple)
            acc = env['account.account'].browse(acc_id)
            code = (acc.code or '').strip()
            if not code:
                continue
            v = float(item.get(amt_field) or 0.0)
            budget_by_code[code] = budget_by_code.get(code, 0.0) + v

elif 'report_line_id' in fg_bi:
    # Fallback : account.report.budget.item lié aux lignes du rapport (sans account_id direct)
    amt_field = next(
        (f for f in ('value', 'budget_amount', 'amount', 'planned_amount') if f in fg_bi),
        None,
    )
    if amt_field:
        b_domain = [('report_line_id.report_id', '=', cpc_report_id)]
        parent_field = next(
            (f for f in ('budget_id', 'report_budget_id') if f in fg_bi), None,
        )
        if parent_field and budget_id:
            b_domain.append((parent_field, '=', budget_id))
        if 'date_from' in fg_bi and date_from and date_to:
            b_domain += [('date_from', '<=', date_to), ('date_to', '>=', date_from)]

        items = env['account.report.budget.item'].search_read(
            b_domain, ['report_line_id', amt_field], limit=0,
        )
        # Récupérer les codes de lignes
        line_ids = list({
            item['report_line_id'][0]
            for item in items
            if item.get('report_line_id')
        })
        lines_meta = {
            r['id']: r['code']
            for r in env['account.report.line'].browse(line_ids).read(['code'])
            if r.get('code')
        }
        # On ne peut pas mapper directement ligne→compte prefix ici,
        # donc on utilise les montants tels quels par code de ligne
        # (budget_by_line_code sera converti plus bas)
        budget_by_line_code = {}
        for item in items:
            lt = item.get('report_line_id')
            if not lt:
                continue
            lid = lt[0] if isinstance(lt, (list, tuple)) else int(lt)
            code = lines_meta.get(lid, '')
            if not code:
                continue
            v = float(item.get(amt_field) or 0.0)
            budget_by_line_code[code] = budget_by_line_code.get(code, 0.0) + v
        # Dans ce cas on utilise budget_by_line_code au lieu de budget_by_code
        # (flag pour distinguer les deux cas plus bas)
        budget_by_code = None
        _use_line_budget = budget_by_line_code
else:
    budget_by_code = {}
    _use_line_budget = None

# ------------------------------------------------------------------ calcul CPC
line_realized = {}  # {code: float} montants réalisés CPC
line_budget   = {}  # {code: float} montants budget CPC

for code, label, nature, formula_ac, formula_agg in CPC_STRUCTURE:
    if nature == 'account' and formula_ac:
        sign = LINE_SIGN.get(code, 1)
        raw_r = _sum_formula(formula_ac, realized_by_code)
        line_realized[code] = sign * raw_r

        if budget_by_code is not None:
            # budget par code compte : les montants sont supposés positifs (saisis CPC)
            raw_b = _sum_formula(formula_ac, budget_by_code)
            line_budget[code] = raw_b
        elif _use_line_budget is not None:
            # budget par code de ligne CPC directement
            line_budget[code] = float(_use_line_budget.get(code, 0.0))
        else:
            line_budget[code] = 0.0

    elif nature == 'aggregate' and formula_agg:
        line_realized[code] = _eval_aggregate(formula_agg, line_realized)
        line_budget[code]   = _eval_aggregate(formula_agg, line_budget)

# ------------------------------------------------------------------ ecriture external values
company_id = env.company.id

for code, expr_id in expr_by_code.items():
    budget_val = float(line_budget.get(code, 0.0))

    # Supprimer les valeurs existantes sur la periode
    old = env['account.report.external.value'].search([
        ('expression_id', '=', expr_id),
        ('date', '>=', date_from),
        ('date', '<=', date_to),
        ('company_id', '=', company_id),
    ])
    old.unlink()

    # Créer la nouvelle valeur
    env['account.report.external.value'].create({
        'expression_id':    expr_id,
        'value':            budget_val,
        'date':             date_to,
        'target_report_id': cpc_report_id,
        'company_id':       company_id,
    })

# ------------------------------------------------------------------ mise a jour statut wizard
written = len(expr_by_code)
wizard.write({
    'x_status': (
        f"OK - {written} ligne(s) CPC mise(s) a jour. "
        f"Ouvrez le rapport CPC dans Odoo avec le filtre analytique = compte {analytic_id}."
    )
})

# ------------------------------------------------------------------ ouvrir le rapport
action = {
    'type':   'ir.actions.act_url',
    'url':    f'/odoo/accounting/reports/{cpc_report_id}',
    'target': 'self',
}
'''

# ---------------------------------------------------------------------------
# XML de la vue formulaire du wizard
# ---------------------------------------------------------------------------
_FORM_VIEW_ARCH = f"""<?xml version="1.0"?>
<form string="{WIZARD_NAME}">
  <sheet>
    <div class="oe_title">
      <h1>{WIZARD_NAME}</h1>
      <p class="oe_grey">
        Selectionnez un axe analytique et une periode, puis cliquez sur Calculer.
      </p>
    </div>
    <group>
      <field name="x_analytic_account_id" required="1"/>
      <field name="x_date_from" required="1"/>
      <field name="x_date_to" required="1"/>
    </group>
    <footer>
      <button name="action_compute" type="object" string="Calculer"
              class="btn-primary" icon="fa-calculator"/>
      <button special="cancel" string="Fermer"/>
    </footer>
  </sheet>
</form>"""

# ---------------------------------------------------------------------------
# Helpers XML-RPC
# ---------------------------------------------------------------------------

def _ek(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    model: str,
    method: str,
    args: list | None = None,
    kw: dict | None = None,
) -> Any:
    return models.execute_kw(db, uid, pwd, model, method, args or [], kw or {})


def _model_exists(models: Any, db: str, uid: int, pwd: str, model: str) -> bool:
    n = _ek(models, db, uid, pwd, "ir.model", "search_count",
            [[("model", "=", model)]])
    return int(n or 0) > 0


def _field_exists(models: Any, db: str, uid: int, pwd: str,
                  model_name: str, field_name: str) -> bool:
    n = _ek(models, db, uid, pwd, "ir.model.fields", "search_count",
            [[("model_id.model", "=", model_name), ("name", "=", field_name)]])
    return int(n or 0) > 0


def _get_model_id(models: Any, db: str, uid: int, pwd: str, model_name: str) -> int:
    ids = _ek(models, db, uid, pwd, "ir.model", "search",
              [[("model", "=", model_name)]], {"limit": 1})
    if not ids:
        raise RuntimeError(f"Modele {model_name!r} introuvable dans ir.model")
    return int(ids[0])

# ---------------------------------------------------------------------------
# Création du wizard dans Odoo
# ---------------------------------------------------------------------------

def create_cpc_wizard(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Crée le wizard CPC Budget Analytique dans Odoo via XML-RPC.

    Retourne un dict avec les IDs créés et des messages de diagnostic.
    Idempotent : purge l'instance existante avant de recréer.
    """
    purge_cpc_wizard(models, db, uid, pwd)

    result: dict[str, Any] = {}

    # ---- 1. ir.model --------------------------------------------------------
    model_id = _ek(models, db, uid, pwd, "ir.model", "create", [{
        "name":  WIZARD_NAME,
        "model": WIZARD_MODEL,
        "state": "manual",
    }])
    result["model_id"] = model_id

    # ---- 2. Champs ----------------------------------------------------------
    def _create_field(fname: str, ftype: str, fstring: str, extra: dict | None = None) -> int:
        vals: dict[str, Any] = {
            "name":     fname,
            "field_description": fstring,
            "ttype":    ftype,
            "model_id": model_id,
            "state":    "manual",
        }
        if extra:
            vals.update(extra)
        return int(_ek(models, db, uid, pwd, "ir.model.fields", "create", [vals]))

    # Compte analytique (required=True → ondelete doit etre restrict ou cascade)
    _create_field("x_analytic_account_id", "many2one",
                  "Compte analytique",
                  {"relation": "account.analytic.account",
                   "required": True,
                   "on_delete": "restrict"})

    # Dates
    _create_field("x_date_from", "date", "Periode du", {"required": True})
    _create_field("x_date_to",   "date", "Periode au", {"required": True})

    # Budget parent (account.report.budget si le modele existe, sinon Char)
    if _model_exists(models, db, uid, pwd, "account.report.budget"):
        _create_field("x_budget_id", "many2one",
                      "Budget",
                      {"relation": "account.report.budget",
                       "on_delete": "set null"})
    else:
        _create_field("x_budget_id", "char", "Reference budget (nom)")

    # Statut
    _create_field("x_status", "char", "Statut / resultat")

    # ---- 3. Server action (Python code) -------------------------------------
    sa_model_id = _get_model_id(models, db, uid, pwd, WIZARD_MODEL)
    sa_id = _ek(models, db, uid, pwd, "ir.actions.server", "create", [{
        "name":     f"Calculer CPC Budget ({WIZARD_NAME})",
        "model_id": sa_model_id,
        "state":    "code",
        "code":     _SERVER_ACTION_CODE,
        "binding_model_id": sa_model_id,
    }])
    result["server_action_id"] = sa_id

    # ---- 4. Vue formulaire --------------------------------------------------
    view_id = _ek(models, db, uid, pwd, "ir.ui.view", "create", [{
        "name":    f"{WIZARD_MODEL}.form",
        "model":   WIZARD_MODEL,
        "type":    "form",
        "arch":    _FORM_VIEW_ARCH,
    }])
    result["view_id"] = view_id

    # ---- 5. Action window ---------------------------------------------------
    aw_id = _ek(models, db, uid, pwd, "ir.actions.act_window", "create", [{
        "name":       WIZARD_NAME,
        "res_model":  WIZARD_MODEL,
        "view_mode":  "form",
        "target":     "new",
        "binding_model_id": sa_model_id,
    }])
    result["act_window_id"] = aw_id

    # ---- 6. Menu sous Comptabilité > Rapports -------------------------------
    # Chercher le menu parent "Rapports" sous Comptabilité
    parent_menu_id = _find_reports_menu(models, db, uid, pwd)

    menu_id = _ek(models, db, uid, pwd, "ir.ui.menu", "create", [{
        "name":          WIZARD_MENU_LABEL,
        "parent_id":     parent_menu_id,
        "action":        f"ir.actions.act_window,{aw_id}",
        "sequence":      99,
    }])
    result["menu_id"] = menu_id

    result["ok"] = True
    result["message"] = (
        f"Wizard CPC cree : modele {WIZARD_MODEL!r}, "
        f"server action id={sa_id}, menu id={menu_id}. "
        f"Accessible dans Odoo : Comptabilite > Rapports > {WIZARD_MENU_LABEL!r}."
    )
    return result


def _find_reports_menu(models: Any, db: str, uid: int, pwd: str) -> int | None:
    """
    Cherche le menu 'Rapports' sous Comptabilité.
    Retourne son id ou None si introuvable.
    """
    candidates = ["Rapports", "Reports", "Reporting"]
    # Recherche d'abord dans les sous-menus Comptabilité
    accounting_menus = _ek(
        models, db, uid, pwd, "ir.ui.menu", "search",
        [["|", ("name", "ilike", "Comptabilit"),
               ("name", "ilike", "Accounting")]],
        {"limit": 10},
    )
    for am in accounting_menus:
        for cand in candidates:
            ids = _ek(
                models, db, uid, pwd, "ir.ui.menu", "search",
                [[("parent_id", "=", am), ("name", "ilike", cand)]],
                {"limit": 1},
            )
            if ids:
                return int(ids[0])
    # Fallback : cherche globalement
    for cand in candidates:
        ids = _ek(
            models, db, uid, pwd, "ir.ui.menu", "search",
            [[("name", "=", cand)]],
            {"limit": 1},
        )
        if ids:
            return int(ids[0])
    return None


# ---------------------------------------------------------------------------
# Suppression du wizard
# ---------------------------------------------------------------------------

def purge_cpc_wizard(models: Any, db: str, uid: int, pwd: str) -> dict[str, Any]:
    """Supprime le wizard CPC (modèle, vues, menus, server actions) s'il existe."""
    purged: list[str] = []

    # Menu
    menu_ids = _ek(models, db, uid, pwd, "ir.ui.menu", "search",
                   [[("name", "=", WIZARD_MENU_LABEL)]])
    if menu_ids:
        _ek(models, db, uid, pwd, "ir.ui.menu", "unlink", [menu_ids])
        purged.append(f"menus({menu_ids})")

    # Act window
    aw_ids = _ek(models, db, uid, pwd, "ir.actions.act_window", "search",
                 [[("res_model", "=", WIZARD_MODEL)]])
    if aw_ids:
        _ek(models, db, uid, pwd, "ir.actions.act_window", "unlink", [aw_ids])
        purged.append(f"act_window({aw_ids})")

    # Server actions
    # Get model_id first (may not exist)
    model_ids = _ek(models, db, uid, pwd, "ir.model", "search",
                    [[("model", "=", WIZARD_MODEL)]])
    if model_ids:
        sa_ids = _ek(models, db, uid, pwd, "ir.actions.server", "search",
                     [[("model_id", "in", model_ids)]])
        if sa_ids:
            _ek(models, db, uid, pwd, "ir.actions.server", "unlink", [sa_ids])
            purged.append(f"server_actions({sa_ids})")

        # Views
        view_ids = _ek(models, db, uid, pwd, "ir.ui.view", "search",
                       [[("model", "=", WIZARD_MODEL)]])
        if view_ids:
            _ek(models, db, uid, pwd, "ir.ui.view", "unlink", [view_ids])
            purged.append(f"views({view_ids})")

        # Model (cascade)
        _ek(models, db, uid, pwd, "ir.model", "unlink", [model_ids])
        purged.append(f"model({model_ids})")

    return {"purged": purged, "ok": True,
            "message": f"Wizard CPC supprime : {', '.join(purged) or 'rien trouve'}."}


# ---------------------------------------------------------------------------
# Vérification
# ---------------------------------------------------------------------------

def cpc_wizard_exists(models: Any, db: str, uid: int, pwd: str) -> bool:
    """True si le wizard (ir.model x_cpc_budget_wizard) est déjà installé sur cette base."""
    return _model_exists(models, db, uid, pwd, WIZARD_MODEL)
