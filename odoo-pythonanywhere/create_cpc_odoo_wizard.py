"""
Crée dans Odoo (via XML-RPC) un wizard natif « Budget par projet » (CPC SYSCOHADA).

Le wizard est un modèle manuel (x_cpc_budget_wizard) avec :
  - Compte analytique (alignement avec le budget), budget financier (account.report.budget), période Du/Au
  - Bouton « Remplir le rapport CPC » → server action Python qui :
      1. Vérifie la cohérence analytique avec le budget (champs Studio optionnels sur account.report.budget)
      2. Lit account.report.budget.item (filtré par budget + période + analytique sur ligne si présent)
      3. Écrit ``account.report.external.value`` pour les expressions **Budget** en moteur ``external``
         uniquement (totaux par rubrique CPC)
      4. Ouvre le rapport CPC dans Odoo (``CPC_REPORT_TOOLBOX_EXACT``)
  - Menus : Facturation/Comptabilité > Reporting > deux entrées voisines (séquences 8 et 9) : d'abord l'assistant
    (formulaire via ``ir.actions.act_window``, plus fiable que ``ir.actions.server`` dans la barre Odoo), puis le rapport interactif (``ir.actions.client``).
  - Rapport CPC : **filtre analytique** activé sur la fiche du rapport ; colonne **Réalisé** =
    ``realise_axe`` en **account_codes** (dépliage par compte). Choisir le **même axe** dans les filtres
    du rapport que celui du wizard pour cohérence visuelle. **Écart** = ``budget − realise_axe`` ; le
    budget **external** reste un total par rubrique (voir doc ``create_cpc_budget_analytique.py``).
  - Colonne Budget (hors moteur natif ``budget``) : remplie depuis le budget financier choisi dans le
    wizard (pas de saisie manuelle au crayon).

Les champs manuels ``x_analytic_account_id`` sur ``account.report.budget`` et
``account.report.budget.item`` sont créés par la toolbox (idempotent si déjà présents).
L'analytique est porté par **l'en-tête** du budget (un budget = un compte analytique) ; sur les **lignes**,
il est affiché en **lecture seule** dans les vues toolbox et aligné sur l'en-tête (import / sync).
Le provision **Budget Senedoo** ajoute aussi ``x_sn_account_code`` (numéro de compte sur les lignes),
des **vues** héritées (analytique + colonnes), une **icône** menu (``web_icon_data``) et une feuille
**CSS** (``ir.attachment`` + ``ir.asset`` → ``web.assets_backend``, classes ``o_sn_senedoo_financial_budget*``).
Des règles ``ir.model.access`` sont créées sur le modèle wizard pour les **profils comptables**
(Facturation / Comptable / Responsable) : sans elles, Odoo **masque l’entrée de menu** pour les
utilisateurs qui ne sont pas administrateurs techniques.

Aucune dépendance module custom — fonctionne sur Odoo 18–19 SaaS Enterprise (réf. doc v18 ; 17 en pratique souvent OK — droits admin / Studio).

Usage Flask toolbox (action staff.py) :
    from create_cpc_odoo_wizard import create_cpc_wizard, purge_cpc_wizard, cpc_wizard_exists
    (``purge_cpc_wizard`` retire aussi le rapport ``account.report`` toolbox et ses menus.)
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WIZARD_MODEL   = "x_cpc_budget_wizard"
WIZARD_NAME    = "Budget par projet (Senedoo)"
# Libellés distincts : « 1. » = formulaire (remplissage), « 2. » = grille rapport (évite la confusion wizard / rapport).
WIZARD_MENU_LABEL = "CPC Senedoo — 1. Assistant (formulaire, budget)"
WIZARD_MENU_SEQUENCE = 8
# Anciens libellés de menu (purge pour éviter doublons après renommage)
WIZARD_MENU_PREVIOUS_NAMES = (
    "Assistant budget projet (Senedoo)",
    "CPC Budget Analytique (Senedoo)",
    "Budget par projet (Senedoo)",
)
# Motifs ilike sur ir.ui.menu.name (orphelins après suppression Studio / modèle, libellés partiels)
WIZARD_MENU_ILIKE_PATTERNS = ("%CPC Budget%", "%Budget par projet%", "%Assistant budget%", "%CPC Senedoo — 1.%")
# Menu Reporting distinct du wizard : ouverture directe du rapport (dépliage par compte).
CPC_REPORT_MENU_LABEL = "CPC Senedoo — 2. Rapport interactif (SYSCOHADA)"
CPC_REPORT_MENU_SEQUENCE = 9
# Ancien libellé du menu rapport (purge orphelins avant recréation)
CPC_REPORT_MENU_PREVIOUS_NAMES = ("CPC SYSCOHADA — rapport budget projet (Senedoo)",)
CPC_REPORT_NAME_LIKE = "CPC SYSCOHADA"        # recherche ilike de secours dans account.report
# Nom exact du account.report créé par la toolbox (aligné sur create_cpc_budget_analytique)
CPC_REPORT_TOOLBOX_EXACT = "CPC SYSCOHADA — Budget par projet (Senedoo)"

# Champs créés sur les modèles budget reporting (Many2one vers l’axe analytique)
BUDGET_ANALYTIC_FIELD_NAME = "x_analytic_account_id"
BUDGET_MODELS_WITH_ANALYTIC_M2O = (
    "account.report.budget",
    "account.report.budget.item",
)

# Champs liés (compte général) sur les lignes de budget financier — affichage liste / formulaire.
BUDGET_ITEM_ACCOUNT_CODE_FIELD_NAME = "x_sn_account_code"
BUDGET_ITEM_ACCOUNT_NAME_FIELD_NAME = "x_sn_account_name"
# Espace de noms XML pour les vues / pièces jointes créées par la toolbox (hors module installable).
SN_BUDGET_TOOLBOX_IMD_MODULE = "sn_budget_toolbox"
SN_BUDGET_FORM_VIEW_IMD_NAME = "account_report_budget_form_senedoo_toolbox"
SN_BUDGET_ITEM_LIST_VIEW_IMD_NAME = "account_report_budget_item_list_senedoo_toolbox"
SN_BUDGET_HEADER_LIST_VIEW_IMD_NAME = "account_report_budget_tree_senedoo_toolbox"
SN_BUDGET_HEADER_KANBAN_VIEW_IMD_NAME = "account_report_budget_kanban_senedoo_toolbox"
SN_BUDGET_SCSS_ATTACHMENT_IMD_NAME = "senedoo_budget_toolbox_backend_scss"
SN_BUDGET_SCSS_ASSET_IMD_NAME = "senedoo_budget_toolbox_backend_asset"
# Héritage formulaire budget : xmlid standard Enterprise 18.x (nom sans préfixe view_).
BUDGET_FORM_VIEW_XMLID_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("account_reports", "account_report_budget_form"),
    ("account_reports", "view_account_report_budget_form"),
)
# Liste des en-têtes budgets (menu « En-têtes de budget »).
BUDGET_TREE_VIEW_XMLID_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("account_reports", "account_report_budget_tree"),
    ("account_reports", "view_account_report_budget_tree"),
)

# Groupes Odoo (res.groups) qui doivent voir le menu + ouvrir le formulaire wizard.
# Sans ir.model.access, le menu reste invisible pour la plupart des profils (filtrage Odoo).
_WIZARD_ACCESS_GROUPS_XMLIDS: tuple[str, ...] = (
    "account.group_account_manager",
    "account.group_account_user",
    "account.group_account_invoice",
    # Enterprise « Comptabilité » (module account_accountant) — ignoré si non installé
    "account_accountant.group_account_user",
)

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
# car Odoo exécute le code avec safe_eval : **aucun import**, pas de générateurs/opcode exotiques.
_SERVER_ACTION_CODE = r'''
# Pas d'import : ir.actions.server utilise safe_eval (opcodes IMPORT interdits sur Odoo SaaS).

def _parse_flat_json_obj(s):
    """Parse {\"k\": float, ...} pour analytic_distribution serialise en str — sans module json."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if len(s) < 2 or s[0] != '{' or s[-1] != '}':
        return None
    inner = s[1:-1].strip()
    if not inner:
        return {}
    out = {}
    for chunk in inner.split(','):
        chunk = chunk.strip()
        if ':' not in chunk:
            continue
        k, v = chunk.split(':', 1)
        k = k.strip().strip('"').strip("'")
        v = v.strip()
        try:
            out[k] = float(v)
        except Exception:
            pass
    return out

def _split_formula_tokens(s):
    """Decoupe 'TA - RA + RB' en jetons sans re."""
    s = (s or "").strip()
    out = []
    buf = []
    for c in s:
        if c == '+' or c == '-':
            t = ''.join(buf).strip()
            if t:
                out.append(t)
            out.append(c)
            buf = []
        else:
            buf.append(c)
    t = ''.join(buf).strip()
    if t:
        out.append(t)
    return out

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
    tokens = _split_formula_tokens(formula_str)
    result = 0.0
    sign = 1
    for tok in tokens:
        tok = tok.strip()
        if tok == '+':
            sign = 1
        elif tok == '-':
            sign = -1
        elif tok:
            result = result + sign * float(line_vals.get(tok, 0.0))
    return result

# ------------------------------------------------------------------ wizard fields
wizard = record
analytic_id = int(wizard.x_analytic_account_id.id) if wizard.x_analytic_account_id else 0
date_from = str(wizard.x_date_from) if wizard.x_date_from else ''
date_to   = str(wizard.x_date_to)   if wizard.x_date_to   else ''
budget_id = int(wizard.x_report_budget_id.id) if wizard.x_report_budget_id else 0

if not analytic_id or not date_from or not date_to:
    raise UserError("Veuillez remplir tous les champs obligatoires (analytique, dates).")
if not budget_id:
    raise UserError("Veuillez selectionner un budget financier (account.report.budget).")

# Coherence avec l'axe (champs Studio optionnels : x_analytic_account_id ou analytic_account_id)
rb = env['account.report.budget'].browse(budget_id)
fg_rb = env['account.report.budget'].fields_get()
for fname in ('x_analytic_account_id', 'analytic_account_id'):
    if fname not in fg_rb:
        continue
    rel = rb[fname]
    if rel:
        rid = int(rel.id if hasattr(rel, 'id') else rel[0])
        if rid != int(analytic_id):
            raise UserError(
                "Le budget financier choisi n'est pas rattache au meme compte analytique que la selection."
            )
        break

# ------------------------------------------------------------------ CPC structure
CPC_STRUCTURE = ''' + repr(_CPC_STRUCTURE) + r'''
LINE_SIGN = ''' + repr(_LINE_SIGN) + r'''

# ------------------------------------------------------------------ find CPC report (eviter cpc_reports[0] imprevisible si plusieurs rapports)
TOOLBOX_EXACT = ''' + repr(CPC_REPORT_TOOLBOX_EXACT) + r'''
cpc_report = env['account.report'].search([('name', '=', TOOLBOX_EXACT)], limit=1)
if not cpc_report:
    _cands = env['account.report'].search([('name', 'ilike', ''' + repr(CPC_REPORT_NAME_LIKE) + ")], order='id desc', limit=30)" + r'''
    for r in _cands:
        _nm = r.name or ''
        if ('Budget par projet' in _nm) or ('Budget Analytique' in _nm) or ('Senedoo' in _nm):
            cpc_report = r
            break
    if not cpc_report and _cands:
        cpc_report = _cands[0]
if not cpc_report:
    raise UserError(
        "Rapport CPC SYSCOHADA introuvable dans Odoo. "
        "Utilisez la toolbox Senedoo pour installer le rapport CPC d'abord."
    )
cpc_report_id = cpc_report.id

# Expressions colonne Budget (moteur external uniquement — le Réalisé est account_codes dans le rapport)
expr_by_code = {}
for line in env['account.report.line'].search([('report_id', '=', cpc_report_id)]):
    if not line.code:
        continue
    for expr in env['account.report.expression'].search([
        ('report_line_id', '=', line.id),
        ('label', '=', 'budget'),
        ('engine', '=', 'external'),
    ]):
        expr_by_code[line.code] = expr.id

# ------------------------------------------------------------------ budget
fg_bi = env['account.report.budget.item'].fields_get()
budget_by_code = {}
_use_line_budget = None

if 'account_id' in fg_bi:
    # Odoo 19+ : account.report.budget.item a un champ account_id direct
    amt_field = None
    for f in ('value', 'budget_amount', 'amount', 'planned_amount'):
        if f in fg_bi:
            amt_field = f
            break
    if amt_field:
        b_domain = []
        # Filtrer par budget parent si fourni
        parent_field = None
        for f in ('budget_id', 'report_budget_id', 'budget'):
            if f in fg_bi:
                parent_field = f
                break
        if parent_field and budget_id:
            b_domain.append((parent_field, '=', budget_id))
        # Filtrer par chevauchement de période si les champs existent
        if 'date_from' in fg_bi and 'date_to' in fg_bi and date_from and date_to:
            b_domain += [('date_from', '<=', date_to), ('date_to', '>=', date_from)]
        elif 'date' in fg_bi and date_from and date_to:
            b_domain += [('date', '>=', date_from), ('date', '<=', date_to)]
        # Lignes rattachees a l'axe OU sans axe (Studio : x_analytic_account_id sur l'item)
        for fname in ('x_analytic_account_id', 'analytic_account_id'):
            if fname in fg_bi and (fg_bi[fname].get('type') or '') == 'many2one':
                b_domain.append('|')
                b_domain.append((fname, '=', analytic_id))
                b_domain.append((fname, '=', False))
                break

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
    amt_field = None
    for f in ('value', 'budget_amount', 'amount', 'planned_amount'):
        if f in fg_bi:
            amt_field = f
            break
    if amt_field:
        b_domain = [('report_line_id.report_id', '=', cpc_report_id)]
        parent_field = None
        for f in ('budget_id', 'report_budget_id'):
            if f in fg_bi:
                parent_field = f
                break
        if parent_field and budget_id:
            b_domain.append((parent_field, '=', budget_id))
        if 'date_from' in fg_bi and date_from and date_to:
            b_domain += [('date_from', '<=', date_to), ('date_to', '>=', date_from)]
        for fname in ('x_analytic_account_id', 'analytic_account_id'):
            if fname in fg_bi and (fg_bi[fname].get('type') or '') == 'many2one':
                b_domain.append('|')
                b_domain.append((fname, '=', analytic_id))
                b_domain.append((fname, '=', False))
                break

        items = env['account.report.budget.item'].search_read(
            b_domain, ['report_line_id', amt_field], limit=0,
        )
        # Récupérer les codes de lignes (sans set comprehension — safe_eval)
        line_ids = []
        for item in items:
            lt = item.get('report_line_id')
            if not lt:
                continue
            lid = lt[0] if isinstance(lt, (list, tuple)) else int(lt)
            if lid not in line_ids:
                line_ids.append(lid)
        lines_meta = {}
        for r in env['account.report.line'].browse(line_ids).read(['code']):
            if r.get('code'):
                lines_meta[r['id']] = r['code']
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

# ------------------------------------------------------------------ calcul CPC (budget par rubrique uniquement)
line_budget = {}  # {code: float} montants budget CPC

for code, label, nature, formula_ac, formula_agg in CPC_STRUCTURE:
    if nature == 'account' and formula_ac:
        if budget_by_code is not None:
            raw_b = _sum_formula(formula_ac, budget_by_code)
            line_budget[code] = raw_b
        elif _use_line_budget is not None:
            line_budget[code] = float(_use_line_budget.get(code, 0.0))
        else:
            line_budget[code] = 0.0

    elif nature == 'aggregate' and formula_agg:
        line_budget[code] = _eval_aggregate(formula_agg, line_budget)

# ------------------------------------------------------------------ ecriture external values (budget external uniquement)
company_id = env.company.id

for code, expr_id in expr_by_code.items():
    val = float(line_budget.get(code, 0.0))
    old = env['account.report.external.value'].search([
        ('expression_id', '=', expr_id),
        ('date', '>=', date_from),
        ('date', '<=', date_to),
        ('company_id', '=', company_id),
    ])
    old.unlink()
    env['account.report.external.value'].create({
        'expression_id':    expr_id,
        'value':            val,
        'date':             date_to,
        'target_report_id': cpc_report_id,
        'company_id':       company_id,
    })

# ------------------------------------------------------------------ aide codes comptes / lignes budget (diagnostic)
codes_diag = ''
try:
    if budget_by_code is not None:
        nz = sorted([k for k, v in budget_by_code.items() if abs(float(v or 0.0)) > 1e-9])
        s = ', '.join(nz[:120])
        if len(nz) > 120:
            s = s + ' ... (+' + str(len(nz) - 120) + ' codes)'
        codes_diag = ' | Comptes budget (non nuls): ' + s
    elif _use_line_budget is not None:
        nz = sorted([k for k, v in _use_line_budget.items() if abs(float(v or 0.0)) > 1e-9])
        s = ', '.join(nz[:120])
        if len(nz) > 120:
            s = s + ' ... (+' + str(len(nz) - 120) + ' codes ligne)'
        codes_diag = ' | Lignes budget CPC (non nuls): ' + s
except Exception:
    codes_diag = ''

# ------------------------------------------------------------------ mise a jour statut wizard
written_b = len(expr_by_code)
wizard.write({
    'x_status': (
        "OK - budget external " + str(written_b) + " rubrique(s). "
        "Réalisé : filtre analytique du rapport + dépliage comptes (account_codes). "
        "Aligner le filtre analytique du rapport sur l axe " + str(analytic_id) + " (wizard)."
        + codes_diag
    )
})

# ------------------------------------------------------------------ ouvrir le rapport
action = {
    'type':   'ir.actions.act_url',
    'url':    '/odoo/accounting/reports/' + str(cpc_report_id),
    'target': 'self',
}
'''

def _report_budget_domain_arch(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> str:
    """
    Attribut ``domain`` pour ``x_report_budget_id`` dans la vue : Odoo valide les noms
    de champs sur ``account.report.budget`` ; ``analytic_account_id`` n'existe pas sur
    toutes les versions / bases (erreur « Champ inconnu » si on le référence à tort).
    """
    has_x = _field_exists(models, db, uid, pwd, "account.report.budget", BUDGET_ANALYTIC_FIELD_NAME)
    has_std = _field_exists(models, db, uid, pwd, "account.report.budget", "analytic_account_id")
    if has_x and has_std:
        return (
            "['|', ('x_analytic_account_id', '=', x_analytic_account_id), "
            "('analytic_account_id', '=', x_analytic_account_id)]"
        )
    if has_x:
        return "[('x_analytic_account_id', '=', x_analytic_account_id)]"
    if has_std:
        return "[('analytic_account_id', '=', x_analytic_account_id)]"
    return "[]"


def _make_form_view_arch(sa_id: int, budget_domain_arch: str) -> str:
    """Vue formulaire : analytique → budgets filtres → période ; bouton serveur dans l'en-tête et le pied."""
    return f"""<?xml version="1.0"?>
<form string="{WIZARD_NAME}">
  <header>
    <button name="{sa_id}" type="action" string="Remplir le rapport CPC"
            class="oe_highlight" icon="fa-calculator"
            title="Injecte le budget sur le CPC et ouvre le rapport pour la periode choisie"/>
  </header>
  <sheet>
    <div class="oe_title">
      <h1>{WIZARD_NAME}</h1>
      <p class="oe_grey">
        1) Choisissez le <strong>compte analytique du projet</strong> (coherence avec le budget).
        2) Choisissez le <strong>budget financier</strong> (liste filtree sur l'axe lorsque le modele budget
        expose un champ analytique reconnu par la toolbox).
        3) Ajustez la <strong>periode</strong>, puis <strong>Remplir le rapport CPC</strong> (injecte le budget external).
        Dans le rapport : activez le <strong>meme axe analytique</strong> dans les filtres du rapport pour le
        <strong>Realise</strong> (comptes de resultat depliables) ; option <strong>Masquer les lignes a zero</strong> si besoin.
      </p>
    </div>
    <group string="Projet">
      <field name="x_analytic_account_id" required="1"
             options="{{'no_create': True, 'no_create_edit': True}}"
             placeholder="Compte analytique du projet"/>
      <field name="x_report_budget_id" string="Budget financier du projet"
             domain="{budget_domain_arch}"
             invisible="not x_analytic_account_id"
             required="x_analytic_account_id"
             options="{{'no_create': True, 'no_create_edit': True}}"
             placeholder="Budget rattache a ce projet"/>
    </group>
    <group string="Periode">
      <field name="x_date_from" required="1"/>
      <field name="x_date_to" required="1"/>
    </group>
    <group string="Resultat">
      <field name="x_status" readonly="1" nolabel="1"/>
    </group>
    <footer>
      <button name="{sa_id}" type="action" string="Remplir le rapport CPC"
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


def _m2o_id_rpc(val: Any) -> int | None:
    if val in (False, None):
        return None
    if isinstance(val, (list, tuple)) and val:
        try:
            return int(val[0])
        except (TypeError, ValueError):
            return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def verify_cpc_wizard_ui_install(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    wizard_model: str,
    model_id: int,
    server_action_id: int,
    menu_act_window_id: int,
    view_id: int,
    menu_id: int,
    parent_menu_id: int | None,
) -> dict[str, Any]:
    """
    Contrôle post-création : action calcul (serveur), action menu (fenêtre), vue, menu.
    Retourne ``{"ok": bool, "checks": [...], "errors": [...], "warnings": [...]}``.
    """
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    mid = int(model_id)
    sa = int(server_action_id)
    aw_m = int(menu_act_window_id)
    vid = int(view_id)
    mn = int(menu_id)
    exp_menu_action = f"ir.actions.act_window,{aw_m}"

    try:
        n_acc = int(
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.model.access",
                "search_count",
                [[["model_id", "=", mid]]],
            )
            or 0
        )
    except Exception:
        n_acc = -1
    acc_ok = n_acc > 0
    checks.append({"step": "ir_model_access_count", "ok": acc_ok, "count": n_acc})
    if not acc_ok:
        errors.append(
            "Aucune règle ir.model.access sur le modèle wizard : l'entrée de menu reste souvent "
            "invisible pour les utilisateurs comptables (lancer « Mettre à jour Budget par projet » "
            "avec la toolbox à jour)."
        )

    rows_sa = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.actions.server",
        "read",
        [[sa]],
        {"fields": ["id", "model_id", "state"]},
    )
    if not rows_sa:
        errors.append(f"ir.actions.server id={sa} (calcul) introuvable en lecture.")
    else:
        r0 = rows_sa[0]
        got_mid = _m2o_id_rpc(r0.get("model_id"))
        mid_ok = got_mid == mid
        checks.append({"step": "server_action_calc_model_id", "ok": mid_ok, "got": got_mid, "expected": mid})
        if not mid_ok:
            errors.append(f"Action calcul : model_id attendu {mid}, lu {got_mid!r}.")
        st = (r0.get("state") or "").strip()
        st_ok = st == "code"
        checks.append({"step": "server_action_calc_state", "ok": st_ok, "state": st})
        if not st_ok:
            errors.append(f"Action calcul : state attendu code, obtenu {st!r}.")

    rows_aw = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.actions.act_window",
        "read",
        [[aw_m]],
        {"fields": ["id", "res_model", "view_mode", "views", "view_id"]},
    )
    if not rows_aw:
        errors.append(f"ir.actions.act_window id={aw_m} (menu wizard) introuvable en lecture.")
    else:
        r1 = rows_aw[0]
        rm_ok = (r1.get("res_model") or "").strip() == wizard_model
        checks.append({"step": "menu_act_window_res_model", "ok": rm_ok, "res_model": r1.get("res_model")})
        if not rm_ok:
            errors.append(
                f"Action menu : res_model attendu {wizard_model!r}, obtenu {r1.get('res_model')!r}."
            )
        vm = (r1.get("view_mode") or "").strip()
        vm_ok = "form" in vm.split(",")
        checks.append({"step": "menu_act_window_view_mode", "ok": vm_ok, "view_mode": vm})
        if not vm_ok:
            errors.append(f"Action menu : view_mode doit inclure form, obtenu {vm!r}.")
        views_blob = str(r1.get("views") or "")
        vid_single = r1.get("view_id")
        vid_ok = str(vid) in views_blob
        if not vid_ok and vid_single:
            try:
                vid_ok = int(_m2o_id_rpc(vid_single) or 0) == int(vid)
            except (TypeError, ValueError):
                vid_ok = False
        checks.append(
            {
                "step": "menu_act_window_views",
                "ok": vid_ok,
                "views_snippet": views_blob[:200],
                "view_id_field": vid_single,
            }
        )
        if not vid_ok:
            warnings.append(
                "Action menu : la vue formulaire n'a pas pu etre verifiee via read RPC "
                f"(view_id attendu {vid}) ; verifier manuellement dans Odoo."
            )

    rows_v = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.ui.view",
        "read",
        [[vid]],
        {"fields": ["id", "model", "type"]},
    )
    if not rows_v:
        errors.append(f"ir.ui.view id={vid} introuvable en lecture.")
    else:
        rv = rows_v[0]
        mod_ok = (rv.get("model") or "").strip() == wizard_model
        typ_ok = (rv.get("type") or "").strip() == "form"
        checks.append({"step": "view_model", "ok": mod_ok, "model": rv.get("model")})
        checks.append({"step": "view_type", "ok": typ_ok, "type": rv.get("type")})
        if not mod_ok:
            errors.append(f"Vue : model attendu {wizard_model!r}, obtenu {rv.get('model')!r}.")
        if not typ_ok:
            errors.append(f"Vue : type attendu form, obtenu {rv.get('type')!r}.")

    rows_mn = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.ui.menu",
        "read",
        [[mn]],
        {"fields": ["id", "name", "action", "parent_id"]},
    )
    if not rows_mn:
        errors.append(f"ir.ui.menu id={mn} introuvable en lecture.")
    else:
        rm = rows_mn[0]
        got_act = (rm.get("action") or "").strip()
        act_ok = got_act == exp_menu_action
        checks.append(
            {"step": "wizard_menu_action", "ok": act_ok, "action": got_act, "expected": exp_menu_action}
        )
        if not act_ok:
            errors.append(f"Menu wizard : action {got_act!r} != {exp_menu_action!r}.")
        par = _m2o_id_rpc(rm.get("parent_id"))
        par_ok = par is not None
        checks.append({"step": "wizard_menu_parent_id", "ok": par_ok, "parent_id": par})
        if not par_ok:
            errors.append("Menu wizard : sans parent_id (invisible dans l'arborescence).")
        elif parent_menu_id is not None and par != int(parent_menu_id):
            warnings.append(
                f"Menu wizard : parent_id={par} differ du parent attendu {parent_menu_id} "
                "(deplacement manuel ou resolution Reporting)."
            )

    if parent_menu_id is None:
        warnings.append(
            "Aucun menu parent Reporting resolu (xmlid) ; le menu wizard peut etre mal place."
        )

    return {
        "ok": len(errors) == 0,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
    }


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


def _res_groups_id_from_full_xmlid(
    models: Any, db: str, uid: int, pwd: str, full_xmlid: str
) -> int | None:
    """``account.group_account_user`` → ``ir.model.data`` module ``account``, name ``group_account_user``."""
    mod, sep, tail = full_xmlid.partition(".")
    if not sep or not mod or not tail:
        return None
    rows = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            [[["module", "=", mod], ["name", "=", tail], ["model", "=", "res.groups"]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if not rows:
        return None
    rid = rows[0].get("res_id")
    return int(rid) if rid else None


def ensure_wizard_ir_model_access(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    model_id: int,
) -> dict[str, Any]:
    """
    Crée des ``ir.model.access`` pour le modèle manuel wizard (lecture / écriture / création / suppression).

    Odoo filtre les entrées ``ir.ui.menu`` liées à ``ir.actions.act_window`` selon les droits
    sur ``res_model`` : sans accès explicite, seuls les administrateurs voient souvent le menu.
    """
    mid = int(model_id)
    created: list[int] = []
    notes: list[str] = []
    for gxml in _WIZARD_ACCESS_GROUPS_XMLIDS:
        gid = _res_groups_id_from_full_xmlid(models, db, uid, pwd, gxml)
        if not gid:
            notes.append(f"groupe_absent:{gxml}")
            continue
        existing = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.model.access",
                "search",
                [[["model_id", "=", mid], ["group_id", "=", int(gid)]]],
                {"limit": 1},
            )
            or []
        )
        if existing:
            notes.append(f"acces_deja_present:{gxml}")
            continue
        suffix = gxml.replace(".", "_")
        aid = _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.access",
            "create",
            [
                {
                    "name": f"acc_{WIZARD_MODEL}_{suffix}"[:128],
                    "model_id": mid,
                    "group_id": int(gid),
                    "perm_read": True,
                    "perm_write": True,
                    "perm_create": True,
                    "perm_unlink": True,
                }
            ],
        )
        created.append(int(aid))
        notes.append(f"acces_cree:{gxml}")
    n_existing = int(
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.access",
            "search_count",
            [[["model_id", "=", mid]]],
        )
        or 0
    )
    return {
        "created_ids": created,
        "notes": notes,
        "access_count": n_existing,
        "ok": n_existing > 0,
    }


def ensure_budget_report_analytic_fields(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Crée ``x_analytic_account_id`` (Many2one ``account.analytic.account``) sur
    ``account.report.budget`` et ``account.report.budget.item`` si absents.

    Idempotent : ne recrée pas un champ déjà présent (Studio ou exécution antérieure).
    Retourne ``{ "by_model": { model: { "status": "created"|"skipped"|"missing_model"|"error", ... } } }``.
    """
    out: dict[str, dict[str, Any]] = {}
    for model_name in BUDGET_MODELS_WITH_ANALYTIC_M2O:
        entry: dict[str, Any] = {"model": model_name}
        if not _model_exists(models, db, uid, pwd, model_name):
            entry["status"] = "missing_model"
            entry["note"] = "Modele non installe sur cette base."
            out[model_name] = entry
            continue
        if _field_exists(models, db, uid, pwd, model_name, BUDGET_ANALYTIC_FIELD_NAME):
            entry["status"] = "skipped"
            entry["note"] = "Champ deja present."
            out[model_name] = entry
            continue
        try:
            mid = _get_model_id(models, db, uid, pwd, model_name)
            fid = _ek(
                models,
                db,
                uid,
                pwd,
                "ir.model.fields",
                "create",
                [{
                    "name": BUDGET_ANALYTIC_FIELD_NAME,
                    "field_description": "Compte analytique (Toolbox Senedoo)",
                    "ttype": "many2one",
                    "model_id": mid,
                    "state": "manual",
                    "relation": "account.analytic.account",
                    "required": False,
                    "on_delete": "set null",
                }],
            )
            entry["status"] = "created"
            entry["field_id"] = fid
        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)
        out[model_name] = entry
    return {"by_model": out, "ok": all(
        v.get("status") in ("created", "skipped") for v in out.values()
    )}


def _rpc_create_id(val: Any) -> int | None:
    if val in (None, False):
        return None
    if isinstance(val, (list, tuple)):
        return int(val[0]) if val else None
    return int(val)


def _view_id_from_xmlid(
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
            [[["module", "=", module], ["name", "=", xml_name], ["model", "=", "ir.ui.view"]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if not rows:
        return None
    rid = rows[0].get("res_id")
    return int(rid) if rid else None


def _resolve_account_report_budget_form_view_id(
    models: Any, db: str, uid: int, pwd: str
) -> int | None:
    for mod, xname in BUDGET_FORM_VIEW_XMLID_CANDIDATES:
        vid = _view_id_from_xmlid(models, db, uid, pwd, mod, xname)
        if vid:
            return vid
    ids = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.view",
            "search",
            [[["model", "=", "account.report.budget"], ["type", "=", "form"], ["mode", "=", "primary"]]],
            {"limit": 1, "order": "id asc"},
        )
        or []
    )
    return int(ids[0]) if ids else None


def _resolve_account_report_budget_tree_view_id(
    models: Any, db: str, uid: int, pwd: str
) -> int | None:
    for mod, xname in BUDGET_TREE_VIEW_XMLID_CANDIDATES:
        vid = _view_id_from_xmlid(models, db, uid, pwd, mod, xname)
        if vid:
            return vid
    return _primary_list_view_id(models, db, uid, pwd, "account.report.budget")


def _primary_list_view_id(
    models: Any, db: str, uid: int, pwd: str, model_name: str
) -> int | None:
    for vtype in ("list", "tree"):
        ids = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.view",
                "search",
                [[["model", "=", model_name], ["type", "=", vtype], ["mode", "=", "primary"]]],
                {"limit": 1, "order": "id asc"},
            )
            or []
        )
        if ids:
            return int(ids[0])
    return None


def _kanban_view_ids_for_model(
    models: Any, db: str, uid: int, pwd: str, model_name: str
) -> list[int]:
    ids = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.view",
            "search",
            [[["model", "=", model_name], ["type", "=", "kanban"]]],
            {"order": "priority asc, id asc"},
        )
        or []
    )
    return [int(i) for i in ids]


def _toolbox_budget_header_kanban_view_id(
    models: Any, db: str, uid: int, pwd: str
) -> int | None:
    rows = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            [[["module", "=", SN_BUDGET_TOOLBOX_IMD_MODULE], ["name", "=", SN_BUDGET_HEADER_KANBAN_VIEW_IMD_NAME]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if not rows or not rows[0].get("res_id"):
        return None
    return int(rows[0]["res_id"])


def _budget_header_kanban_templates_inner(field_names: set[str]) -> str:
    """Corps du template kanban ``card`` (OWL Odoo 18+ ; plus ``kanban-box``)."""
    has_df = "date_from" in field_names
    has_dt = "date_to" in field_names
    has_rep = "report_id" in field_names
    analytic_f: str | None = None
    if "x_analytic_account_id" in field_names:
        analytic_f = "x_analytic_account_id"
    elif "analytic_account_id" in field_names:
        analytic_f = "analytic_account_id"

    dates_block = ""
    if has_df or has_dt:
        parts = []
        if has_df:
            parts.append(
                """<span t-if="record.date_from.raw_value" class="o_sn_budget_kanban_meta_line">
              <i class="fa fa-calendar-o me-1"/> Du <field name="date_from"/>
            </span>"""
            )
        if has_dt:
            parts.append(
                """<span t-if="record.date_to.raw_value" class="o_sn_budget_kanban_meta_line">
              <i class="fa fa-calendar-o me-1"/> Au <field name="date_to"/>
            </span>"""
            )
        dates_block = (
            '<div class="o_sn_budget_kanban_dates text-muted small">'
            + "".join(parts)
            + "</div>"
        )

    report_block = ""
    if has_rep:
        report_block = """<div t-if="record.report_id.raw_value" class="o_sn_budget_kanban_report small text-muted text-truncate">
          <i class="fa fa-bar-chart me-1"/> <field name="report_id"/>
        </div>"""

    analytic_block = ""
    if analytic_f:
        analytic_block = f"""<div t-if="record.{analytic_f}.raw_value" class="o_sn_budget_kanban_analytic small">
          <i class="fa fa-crosshairs me-1 o_sn_budget_kanban_icon"/> <field name="{analytic_f}"/>
        </div>"""

    company_block = ""
    if "company_id" in field_names:
        company_block = """<div t-if="record.company_id.raw_value" class="o_sn_budget_kanban_company small text-muted mb-1">
          <i class="fa fa-building-o me-1"/> <field name="company_id"/>
        </div>"""

    return f"""<div class="oe_kanban_card oe_kanban_global_click o_sn_budget_kanban_card h-100">
      <div class="o_sn_budget_kanban_card_inner d-flex flex-column h-100">
        <div class="o_sn_budget_kanban_title text-truncate fw-bold fs-5 mb-2">
          <field name="name"/>
        </div>
        {dates_block}
        {company_block}
        {report_block}
        {analytic_block}
        <div class="o_sn_budget_kanban_footer mt-auto pt-2 text-end">
          <span class="badge rounded-pill o_sn_budget_kanban_badge">Budget</span>
        </div>
      </div>
    </div>"""


def _budget_header_kanban_field_declarations(field_names: set[str]) -> str:
    decl: list[str] = ["name"]
    if "company_id" in field_names:
        decl.append("company_id")
    for n in ("date_from", "date_to", "report_id", "x_analytic_account_id", "analytic_account_id"):
        if n in field_names and n not in decl:
            decl.append(n)
    return "\n    ".join(f'<field name="{n}"/>' for n in decl)


def _budget_header_kanban_arch_primary(field_names: set[str]) -> str:
    fields_xml = _budget_header_kanban_field_declarations(field_names)
    inner = _budget_header_kanban_templates_inner(field_names)
    return f"""<kanban class="o_sn_senedoo_budget_headers_kanban" create="false" default_order="name asc">
    {fields_xml}
    <templates>
        <t t-name="card">
            {inner}
        </t>
    </templates>
</kanban>"""


def _budget_header_kanban_arch_extension(field_names: set[str]) -> str:
    """Vue extension : autre kanban présent sur le modèle (héritage + remplacement du template)."""
    inner = _budget_header_kanban_templates_inner(field_names)
    return f"""<data>
  <xpath expr="//kanban" position="attributes">
    <attribute name="class" add="o_sn_senedoo_budget_headers_kanban" separator=" "/>
  </xpath>
  <xpath expr="//templates" position="replace">
    <templates>
        <t t-name="card">
            {inner}
        </t>
    </templates>
  </xpath>
</data>"""


def ensure_budget_report_senedoo_budget_header_kanban_view(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Vue **kanban** pour les en-têtes ``account.report.budget`` (cartes Senedoo).

    Si aucune vue kanban n'existe sur le modèle : création d'une vue **primaire**.
    Sinon : extension de la première vue kanban existante (hors celle de la toolbox).
    """
    model_name = "account.report.budget"
    if not _model_exists(models, db, uid, pwd, model_name):
        return {"status": "missing_model", "ok": False}

    try:
        fg = _ek(models, db, uid, pwd, model_name, "fields_get", [[]], {})
    except Exception as e:
        return {"status": "fields_get_error", "ok": False, "error": str(e)}
    field_names = set(fg.keys()) if isinstance(fg, dict) else set()

    existing_tid = _toolbox_budget_header_kanban_view_id(models, db, uid, pwd)
    all_k = _kanban_view_ids_for_model(models, db, uid, pwd, model_name)

    arch_primary = _budget_header_kanban_arch_primary(field_names)
    arch_ext = _budget_header_kanban_arch_extension(field_names)

    if existing_tid:
        row = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.view",
                "read",
                [[existing_tid]],
                {"fields": ["inherit_id", "mode", "type"]},
            )
            or [{}]
        )[0]
        inherit_id = row.get("inherit_id")
        inherit_val = inherit_id[0] if isinstance(inherit_id, (list, tuple)) and inherit_id else inherit_id
        use_arch = arch_ext if inherit_val else arch_primary
        _ek(models, db, uid, pwd, "ir.ui.view", "write", [[existing_tid], {"arch": use_arch}])
        return {
            "status": "updated",
            "ok": True,
            "view_id": existing_tid,
            "inherit_id": int(inherit_val) if inherit_val else None,
        }

    foreign = [vid for vid in all_k]
    if foreign:
        parent_id = int(foreign[0])
        vid = _rpc_create_id(
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.view",
                "create",
                [
                    {
                        "name": "account.report.budget.kanban.headers.senedoo.toolbox",
                        "model": model_name,
                        "inherit_id": parent_id,
                        "mode": "extension",
                        "type": "kanban",
                        "arch": arch_ext,
                        "priority": 99,
                    }
                ],
            )
        )
        if not vid:
            return {"status": "error", "ok": False, "error": "create ir.ui.view kanban extension a retourne vide."}
        _ensure_toolbox_xml_id(
            models,
            db,
            uid,
            pwd,
            name=SN_BUDGET_HEADER_KANBAN_VIEW_IMD_NAME,
            model="ir.ui.view",
            res_id=vid,
        )
        return {"status": "created", "ok": True, "view_id": vid, "inherit_id": parent_id}

    vid = _rpc_create_id(
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.view",
            "create",
                [
                    {
                        "name": "account.report.budget.kanban.headers.senedoo.toolbox",
                        "model": model_name,
                        "mode": "primary",
                        "type": "kanban",
                        "arch": arch_primary,
                        "priority": 16,
                    }
                ],
        )
    )
    if not vid:
        return {"status": "error", "ok": False, "error": "create ir.ui.view kanban primary a retourne vide."}
    _ensure_toolbox_xml_id(
        models,
        db,
        uid,
        pwd,
        name=SN_BUDGET_HEADER_KANBAN_VIEW_IMD_NAME,
        model="ir.ui.view",
        res_id=vid,
    )
    return {"status": "created", "ok": True, "view_id": vid, "inherit_id": None}


def _ensure_toolbox_xml_id(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    name: str,
    model: str,
    res_id: int,
) -> str:
    found = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search",
            [[["module", "=", SN_BUDGET_TOOLBOX_IMD_MODULE], ["name", "=", name]]],
            {"limit": 1},
        )
        or []
    )
    if found:
        return "exists"
    _ek(
        models,
        db,
        uid,
        pwd,
        "ir.model.data",
        "create",
        [
            {
                "module": SN_BUDGET_TOOLBOX_IMD_MODULE,
                "name": name,
                "model": model,
                "res_id": int(res_id),
            }
        ],
    )
    return "created"


def ensure_budget_report_item_account_code_field(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Crée ``x_sn_account_code`` (Char lié ``account_id.code``) sur ``account.report.budget.item``.

    Sert d’affichage explicite du **numéro de compte** sur les lignes (complément du many2one compte).
    """
    model_name = "account.report.budget.item"
    if not _model_exists(models, db, uid, pwd, model_name):
        return {"status": "missing_model", "ok": False}
    if not _field_exists(models, db, uid, pwd, model_name, "account_id"):
        return {"status": "missing_account_id", "ok": False, "note": "Champ account_id absent."}
    if _field_exists(models, db, uid, pwd, model_name, BUDGET_ITEM_ACCOUNT_CODE_FIELD_NAME):
        return {"status": "skipped", "ok": True, "note": "Champ deja present."}
    try:
        mid = _get_model_id(models, db, uid, pwd, model_name)
        fid = _rpc_create_id(
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.model.fields",
                "create",
                [
                    {
                        "name": BUDGET_ITEM_ACCOUNT_CODE_FIELD_NAME,
                        "field_description": "Numero de compte (Senedoo)",
                        "ttype": "char",
                        "model_id": mid,
                        "state": "manual",
                        "related": "account_id.code",
                        "readonly": True,
                        "store": False,
                    }
                ],
            )
        )
        return {"status": "created", "ok": True, "field_id": fid}
    except Exception as e:
        return {"status": "error", "ok": False, "error": str(e)}


def ensure_budget_report_item_account_name_field(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Crée ``x_sn_account_name`` (Char lié ``account_id.name``) sur ``account.report.budget.item``.

    Affiche le **libellé** du compte à côté du numéro (``x_sn_account_code``).
    """
    model_name = "account.report.budget.item"
    if not _model_exists(models, db, uid, pwd, model_name):
        return {"status": "missing_model", "ok": False}
    if not _field_exists(models, db, uid, pwd, model_name, "account_id"):
        return {"status": "missing_account_id", "ok": False, "note": "Champ account_id absent."}
    if _field_exists(models, db, uid, pwd, model_name, BUDGET_ITEM_ACCOUNT_NAME_FIELD_NAME):
        return {"status": "skipped", "ok": True, "note": "Champ deja present."}
    try:
        mid = _get_model_id(models, db, uid, pwd, model_name)
        fid = _rpc_create_id(
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.model.fields",
                "create",
                [
                    {
                        "name": BUDGET_ITEM_ACCOUNT_NAME_FIELD_NAME,
                        "field_description": "Libelle compte (Senedoo)",
                        "ttype": "char",
                        "model_id": mid,
                        "state": "manual",
                        "related": "account_id.name",
                        "readonly": True,
                        "store": False,
                    }
                ],
            )
        )
        return {"status": "created", "ok": True, "field_id": fid}
    except Exception as e:
        return {"status": "error", "ok": False, "error": str(e)}


def ensure_budget_report_senedoo_budget_form_view(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Vue formulaire héritée : analytique sur l’en-tête, colonnes **numéro de compte** + analytique
    dans la sous-liste ``item_ids``.
    """
    inherit_id = _resolve_account_report_budget_form_view_id(models, db, uid, pwd)
    if not inherit_id:
        return {"status": "missing_parent_view", "ok": False}

    arch = """<data>
  <xpath expr="//form" position="attributes">
    <attribute name="class" add="o_sn_senedoo_financial_budget" separator=" "/>
  </xpath>
  <xpath expr="//sheet" position="inside">
    <group string="Compte analytique (Senedoo)" name="o_group_sn_budget_analytic" class="o_group_sn_budget_analytic">
      <field name="x_analytic_account_id" options="{'no_create': True, 'no_create_edit': True}"/>
    </group>
  </xpath>
  <xpath expr="//field[@name='item_ids']/list/field[@name='account_id']" position="after">
    <field name="x_sn_account_code" string="Numero compte" optional="show" readonly="1" width="10%%"/>
    <field name="x_sn_account_name" string="Libelle compte" optional="show" readonly="1" width="22%%"/>
    <field name="x_analytic_account_id" string="Compte analytique (budget)" optional="show" readonly="1"
           options="{'no_create': True, 'no_create_edit': True, 'no_open': True}" width="18%%"/>
  </xpath>
</data>"""

    existing = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            [[["module", "=", SN_BUDGET_TOOLBOX_IMD_MODULE], ["name", "=", SN_BUDGET_FORM_VIEW_IMD_NAME]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if existing and existing[0].get("res_id"):
        vid = int(existing[0]["res_id"])
        _ek(models, db, uid, pwd, "ir.ui.view", "write", [[vid], {"arch": arch}])
        return {"status": "updated", "ok": True, "view_id": vid, "inherit_id": inherit_id}

    vid = _rpc_create_id(
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.view",
            "create",
            [
                {
                    "name": "account.report.budget.form.senedoo.toolbox",
                    "model": "account.report.budget",
                    "inherit_id": inherit_id,
                    "mode": "extension",
                    "type": "form",
                    "arch": arch,
                    "priority": 90,
                }
            ],
        )
    )
    if not vid:
        return {"status": "error", "ok": False, "error": "create ir.ui.view a retourne vide."}
    _ensure_toolbox_xml_id(
        models,
        db,
        uid,
        pwd,
        name=SN_BUDGET_FORM_VIEW_IMD_NAME,
        model="ir.ui.view",
        res_id=vid,
    )
    return {"status": "created", "ok": True, "view_id": vid, "inherit_id": inherit_id}


def ensure_budget_report_senedoo_budget_header_list_view(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Liste des en-têtes ``account.report.budget`` (menu « En-têtes de budget ») :
    classe thème Senedoo, colonne **compte analytique**, liste **éditable** (saisie par ligne).
    """
    model_name = "account.report.budget"
    inherit_id = _resolve_account_report_budget_tree_view_id(models, db, uid, pwd)
    if not inherit_id:
        return {"status": "missing_parent_view", "ok": False}

    arch = """<data>
  <xpath expr="//list" position="attributes">
    <attribute name="class" add="o_sn_senedoo_financial_budget_headers" separator=" "/>
    <attribute name="editable">bottom</attribute>
  </xpath>
  <xpath expr="//field[@name='name']" position="after">
    <field name="x_analytic_account_id" string="Compte analytique" optional="show"
           options="{'no_create': True, 'no_create_edit': True}"/>
  </xpath>
</data>"""

    existing = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            [[["module", "=", SN_BUDGET_TOOLBOX_IMD_MODULE], ["name", "=", SN_BUDGET_HEADER_LIST_VIEW_IMD_NAME]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if existing and existing[0].get("res_id"):
        vid = int(existing[0]["res_id"])
        _ek(models, db, uid, pwd, "ir.ui.view", "write", [[vid], {"arch": arch}])
        return {"status": "updated", "ok": True, "view_id": vid, "inherit_id": inherit_id}

    vid = _rpc_create_id(
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.view",
            "create",
            [
                {
                    "name": "account.report.budget.list.headers.senedoo.toolbox",
                    "model": model_name,
                    "inherit_id": inherit_id,
                    "mode": "extension",
                    "type": "list",
                    "arch": arch,
                    "priority": 90,
                }
            ],
        )
    )
    if not vid:
        return {"status": "error", "ok": False, "error": "create ir.ui.view a retourne vide."}
    _ensure_toolbox_xml_id(
        models,
        db,
        uid,
        pwd,
        name=SN_BUDGET_HEADER_LIST_VIEW_IMD_NAME,
        model="ir.ui.view",
        res_id=vid,
    )
    return {"status": "created", "ok": True, "view_id": vid, "inherit_id": inherit_id}


def ensure_budget_report_senedoo_budget_item_list_view(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Enrichit la liste primaire ``account.report.budget.item`` (menu « Lignes de budget ») :
    budget, compte, numéro, période, montant, analytique.
    """
    model_name = "account.report.budget.item"
    inherit_id = _primary_list_view_id(models, db, uid, pwd, model_name)
    if not inherit_id:
        return {"status": "missing_parent_view", "ok": False}

    arch = """<data>
  <xpath expr="//list" position="attributes">
    <attribute name="string">Lignes budget financier (Senedoo)</attribute>
    <attribute name="editable">bottom</attribute>
    <attribute name="class" add="o_sn_senedoo_financial_budget_lines" separator=" "/>
  </xpath>
  <xpath expr="//field[@name='id']" position="replace">
    <field name="budget_id" optional="show"/>
    <field name="account_id" optional="show"/>
    <field name="x_sn_account_code" string="Numero compte" optional="show" readonly="1"/>
    <field name="x_sn_account_name" string="Libelle compte" optional="show" readonly="1"/>
    <field name="date"/>
    <field name="amount"/>
    <field name="x_analytic_account_id" string="Compte analytique (budget)" optional="show" readonly="1"
           options="{'no_create': True, 'no_create_edit': True, 'no_open': True}"/>
  </xpath>
</data>"""

    existing = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            [[["module", "=", SN_BUDGET_TOOLBOX_IMD_MODULE], ["name", "=", SN_BUDGET_ITEM_LIST_VIEW_IMD_NAME]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if existing and existing[0].get("res_id"):
        vid = int(existing[0]["res_id"])
        _ek(models, db, uid, pwd, "ir.ui.view", "write", [[vid], {"arch": arch}])
        return {"status": "updated", "ok": True, "view_id": vid, "inherit_id": inherit_id}

    vid = _rpc_create_id(
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.view",
            "create",
            [
                {
                    "name": "account.report.budget.item.list.senedoo.toolbox",
                    "model": model_name,
                    "inherit_id": inherit_id,
                    "mode": "extension",
                    "type": "list",
                    "arch": arch,
                    "priority": 90,
                }
            ],
        )
    )
    if not vid:
        return {"status": "error", "ok": False, "error": "create ir.ui.view a retourne vide."}
    _ensure_toolbox_xml_id(
        models,
        db,
        uid,
        pwd,
        name=SN_BUDGET_ITEM_LIST_VIEW_IMD_NAME,
        model="ir.ui.view",
        res_id=vid,
    )
    return {"status": "created", "ok": True, "view_id": vid, "inherit_id": inherit_id}


def ensure_budget_report_senedoo_budget_views(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """Formulaire budget + listes en-têtes et lignes + kanban en-têtes (UX Senedoo)."""
    form = ensure_budget_report_senedoo_budget_form_view(models, db, uid, pwd)
    header_list = ensure_budget_report_senedoo_budget_header_list_view(models, db, uid, pwd)
    header_kanban = ensure_budget_report_senedoo_budget_header_kanban_view(models, db, uid, pwd)
    item_list = ensure_budget_report_senedoo_budget_item_list_view(models, db, uid, pwd)
    ok = (
        bool(form.get("ok"))
        and bool(header_list.get("ok"))
        and bool(header_kanban.get("ok"))
        and bool(item_list.get("ok"))
    )
    return {
        "form": form,
        "header_list": header_list,
        "header_kanban": header_kanban,
        "item_list": item_list,
        "ok": ok,
    }


def _toolbox_static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def ensure_senedoo_financial_budget_toolbox_backend_scss_asset(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Publie une feuille **CSS** (charte Senedoo) dans ``web.assets_backend`` via ``ir.attachment``
    + ``ir.asset`` (URL ``/web/content/<id>``).

    Le fichier doit être du **CSS interprétable par le navigateur** (pas du SCSS brut : sinon aucun
    style ne s’applique). Fichier source : ``static/senedoo_budget_toolbox.css``.

    Périmètre : classes ``o_sn_senedoo_financial_budget*`` uniquement.
    """
    static_dir = _toolbox_static_dir()
    css_path = static_dir / "senedoo_budget_toolbox.css"
    if not css_path.is_file():
        return {"status": "missing_file", "ok": False, "path": str(css_path)}

    css_bytes = css_path.read_bytes()
    b64 = base64.b64encode(css_bytes).decode("ascii")
    att_name = "senedoo_budget_toolbox_backend.css"
    # Odoo inclut les feuilles « externes » du bundle via ir.attachment._get_serve_attachment(url) :
    # domaine [('type','=','binary'), ('url','=', <path ir.asset>)]. Sans ``url``, le fichier n'est
    # jamais résolu et aucun <link> effectif (cf. deploy_dashboard_studio.py : /web/content/id/nom.css).

    att_rows = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            [[["module", "=", SN_BUDGET_TOOLBOX_IMD_MODULE], ["name", "=", SN_BUDGET_SCSS_ATTACHMENT_IMD_NAME]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    if att_rows and att_rows[0].get("res_id"):
        att_id = int(att_rows[0]["res_id"])
        att_status = "updated"
    else:
        att_id = _rpc_create_id(
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.attachment",
                "create",
                [
                    {
                        "name": att_name,
                        "type": "binary",
                        "mimetype": "text/css",
                        "datas": b64,
                        "public": True,
                    }
                ],
            )
        )
        if not att_id:
            return {"status": "error", "ok": False, "error": "Echec creation ir.attachment CSS."}
        _ensure_toolbox_xml_id(
            models,
            db,
            uid,
            pwd,
            name=SN_BUDGET_SCSS_ATTACHMENT_IMD_NAME,
            model="ir.attachment",
            res_id=att_id,
        )
        att_status = "created"

    content_path = f"/web/content/{int(att_id)}/{att_name}"
    _ek(
        models,
        db,
        uid,
        pwd,
        "ir.attachment",
        "write",
        [
            [int(att_id)],
            {
                "datas": b64,
                "mimetype": "text/css",
                "name": att_name,
                "public": True,
                "url": content_path,
            },
        ],
    )
    asset_name = "Senedoo — charte budget financier (CSS toolbox)"

    asset_rows = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.model.data",
            "search_read",
            [[["module", "=", SN_BUDGET_TOOLBOX_IMD_MODULE], ["name", "=", SN_BUDGET_SCSS_ASSET_IMD_NAME]]],
            {"fields": ["res_id"], "limit": 1},
        )
        or []
    )
    asset_vals = {
        "name": asset_name,
        "bundle": "web.assets_backend",
        "directive": "append",
        "path": content_path,
        "sequence": 120,
        "active": True,
    }
    if asset_rows and asset_rows[0].get("res_id"):
        asset_id = int(asset_rows[0]["res_id"])
        _ek(models, db, uid, pwd, "ir.asset", "write", [[asset_id], asset_vals])
        asset_status = "updated"
    else:
        asset_id = _rpc_create_id(
            _ek(models, db, uid, pwd, "ir.asset", "create", [asset_vals])
        )
        if not asset_id:
            return {"status": "error", "ok": False, "error": "Echec creation ir.asset CSS."}
        _ensure_toolbox_xml_id(
            models,
            db,
            uid,
            pwd,
            name=SN_BUDGET_SCSS_ASSET_IMD_NAME,
            model="ir.asset",
            res_id=asset_id,
        )
        asset_status = "created"

    try:
        _ek(models, db, uid, pwd, "ir.attachment", "regenerate_assets_bundles", [], {})
    except Exception:
        pass

    return {
        "ok": True,
        "status": "ok",
        "attachment_id": int(att_id),
        "attachment_status": att_status,
        "asset_id": int(asset_id),
        "asset_status": asset_status,
        "content_url": content_path,
    }


def ensure_senedoo_financial_budget_root_menu_icon(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    root_menu_id: int,
) -> dict[str, Any]:
    """
    Dépose une icône PNG (dégradé violet / blanc) sur le menu racine « Budget Senedoo ».

    Fichier source : ``static/senedoo_budget_menu_icon.png`` à côté de ce script.
    """
    icon_path = _toolbox_static_dir() / "senedoo_budget_menu_icon.png"
    if not icon_path.is_file():
        return {"status": "missing_file", "ok": False, "path": str(icon_path)}
    png_b64 = base64.b64encode(icon_path.read_bytes()).decode("ascii")
    _ek(
        models,
        db,
        uid,
        pwd,
        "ir.ui.menu",
        "write",
        [[int(root_menu_id)], {"web_icon_data": png_b64}],
    )
    return {"status": "written", "ok": True, "menu_id": int(root_menu_id)}


def ensure_senedoo_financial_budget_toolbox_branding(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    *,
    root_menu_id: int | None,
) -> dict[str, Any]:
    """Icône menu racine + feuille CSS backend (charte limitée aux écrans toolbox)."""
    out: dict[str, Any] = {"scss_asset": {}, "menu_icon": {}}
    out["scss_asset"] = ensure_senedoo_financial_budget_toolbox_backend_scss_asset(models, db, uid, pwd)
    if root_menu_id:
        try:
            out["menu_icon"] = ensure_senedoo_financial_budget_root_menu_icon(
                models, db, uid, pwd, root_menu_id=int(root_menu_id)
            )
        except Exception as e:
            out["menu_icon"] = {"ok": False, "status": "error", "error": str(e)}
    else:
        out["menu_icon"] = {"ok": False, "status": "skipped", "note": "menu racine inconnu."}
    out["ok"] = bool(out["scss_asset"].get("ok")) and bool(out["menu_icon"].get("ok"))
    return out


def _install_fresh_toolbox_cpc_budget_report(
    models: Any, db: str, uid: int, pwd: str
) -> dict[str, Any]:
    """
    Purge tous les rapports toolbox CPC Senedoo puis recrée un ``account.report`` unique.

    Le menu **Reporting** vers le rapport est recréé séparément dans ``create_cpc_wizard``
    (libellé distinct de l'assistant) pour ouvrir le CPC directement avec dépliage par compte.
    """
    import sys
    from pathlib import Path

    ac = Path(__file__).resolve().parent / "archives-cli"
    if ac.is_dir() and str(ac) not in sys.path:
        sys.path.insert(0, str(ac))
    try:
        from create_cpc_budget_analytique import create_toolbox_cpc_budget_analytique
    except ImportError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        out = create_toolbox_cpc_budget_analytique(models, db, uid, pwd)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    out["ok"] = True
    return out


def _budget_fields_summary_for_user_message(ba: dict[str, Any]) -> str:
    """Résumé court pour flash UI (éviter cookie de session > 4 Ko avec SecureCookieSession)."""
    by = (ba or {}).get("by_model") or {}
    parts: list[str] = []
    for model_name, entry in by.items():
        short = (model_name or "").split(".")[-1] or model_name
        st = entry.get("status") or "?"
        if st == "error" and entry.get("error"):
            err = str(entry["error"])[:100].replace("\n", " ").strip()
            parts.append(f"{short}={st}")
            if err:
                parts[-1] += f"({err})"
        else:
            parts.append(f"{short}={st}")
    return ", ".join(parts) if parts else "n/a"


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
    Crée le wizard Budget par projet dans Odoo via XML-RPC.

    Retourne un dict avec les IDs créés et des messages de diagnostic.
    Idempotent : purge l'instance existante avant de recréer.
    Recrée aussi le rapport ``account.report`` toolbox (un seul en base après installation).
    """
    purge_cpc_wizard(models, db, uid, pwd)

    result: dict[str, Any] = {}

    inst = _install_fresh_toolbox_cpc_budget_report(models, db, uid, pwd)
    result["cpc_toolbox_install"] = inst
    if not inst.get("ok"):
        raise RuntimeError(
            inst.get("error")
            or "Echec creation du rapport CPC toolbox (voir logs / droits Odoo)."
        )

    # ---- Menu Reporting : ouverture directe du rapport (complément de l'assistant) -------
    result["cpc_report_menu_id"] = None
    result["cpc_report_client_action_id"] = None
    _rid_menu = int((inst.get("report_id") or 0))
    if _rid_menu:
        try:
            import sys
            from pathlib import Path

            _pa_root = Path(__file__).resolve().parent
            if str(_pa_root) not in sys.path:
                sys.path.insert(0, str(_pa_root))
            from web_app.odoo_account_reports import ensure_account_report_reporting_menu

            _aid, _mid, _menu_pc = ensure_account_report_reporting_menu(
                models,
                db,
                uid,
                pwd,
                _rid_menu,
                CPC_REPORT_MENU_LABEL,
                menu_sequence=CPC_REPORT_MENU_SEQUENCE,
            )
            result["cpc_report_client_action_id"] = _aid
            result["cpc_report_menu_id"] = _mid
            result["cpc_report_menu_post_checks"] = _menu_pc
        except Exception as menu_exc:
            result["cpc_report_menu_error"] = str(menu_exc)

    # ---- 0. Champs analytique sur les budgets financiers (reporting) -------
    result["budget_analytic_fields"] = ensure_budget_report_analytic_fields(
        models, db, uid, pwd
    )

    # ---- 1. ir.model --------------------------------------------------------
    model_id = _ek(models, db, uid, pwd, "ir.model", "create", [{
        "name":  WIZARD_NAME,
        "model": WIZARD_MODEL,
        "state": "manual",
    }])
    result["model_id"] = model_id

    # ---- 2. Champs (batch : 1 seul appel XML-RPC) ---------------------------
    field_defs: list[dict[str, Any]] = [
        {
            "name": "x_analytic_account_id",
            "field_description": "Compte analytique",
            "ttype": "many2one",
            "model_id": model_id,
            "state": "manual",
            "relation": "account.analytic.account",
            "required": True,
            "on_delete": "restrict",
        },
        {
            "name": "x_date_from",
            "field_description": "Periode du",
            "ttype": "date",
            "model_id": model_id,
            "state": "manual",
            "required": True,
        },
        {
            "name": "x_date_to",
            "field_description": "Periode au",
            "ttype": "date",
            "model_id": model_id,
            "state": "manual",
            "required": True,
        },
        {
            "name": "x_report_budget_id",
            "field_description": "Budget financier (account.report.budget)",
            "ttype": "many2one",
            "model_id": model_id,
            "state": "manual",
            "relation": "account.report.budget",
            "required": True,
            "on_delete": "restrict",
        },
        {
            "name": "x_status",
            "field_description": "Statut / resultat",
            "ttype": "char",
            "model_id": model_id,
            "state": "manual",
        },
    ]
    _ek(models, db, uid, pwd, "ir.model.fields", "create", [field_defs])

    # ---- 2b. ir.model.access : sans cela le menu assistant est filtré pour les non-admins Odoo.
    result["wizard_ir_model_access"] = ensure_wizard_ir_model_access(
        models, db, uid, pwd, model_id=int(model_id)
    )

    # ---- 3. Server action (Python code) — model_id déjà connu ---------------
    sa_id = _ek(models, db, uid, pwd, "ir.actions.server", "create", [{
        "name":     f"Calculer budget projet ({WIZARD_NAME})",
        "model_id": model_id,
        "state":    "code",
        "code":     _SERVER_ACTION_CODE,
        "binding_model_id": model_id,
    }])
    result["server_action_id"] = sa_id

    # ---- 4. Vue formulaire (bouton référence le sa_id réel) -----------------
    budget_dom = _report_budget_domain_arch(models, db, uid, pwd)
    view_id = _ek(models, db, uid, pwd, "ir.ui.view", "create", [{
        "name":    f"{WIZARD_MODEL}.form",
        "model":   WIZARD_MODEL,
        "type":    "form",
        "arch":    _make_form_view_arch(int(sa_id), budget_dom),
    }])
    result["view_id"] = view_id

    # ---- 5. Action fenêtre « menu » (ir.actions.act_window) : même effet qu'une entrée standard Odoo.
    #     Les menus ``ir.actions.server`` sont souvent absents de la barre latérale selon édition / droits.
    _vid = int(view_id)
    aw_menu_id = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.actions.act_window",
        "create",
        [
            {
                "name":      WIZARD_MENU_LABEL,
                "res_model": WIZARD_MODEL,
                "view_mode": "form",
                "views":     [[_vid, "form"]],
                "target":    "current",
            }
        ],
    )
    result["menu_act_window_id"] = aw_menu_id

    # ---- 6. Menu sous Reporting (même parent que les rapports comptables Senedoo ; pas de copie
    #     groups_id du parent : sur certaines bases Enterprise cela masquait l'entrée pour les utilisateurs.)
    parent_menu_id, parent_menu_src = _resolve_wizard_parent_menu(models, db, uid, pwd)
    result["wizard_menu_parent_source"] = parent_menu_src

    menu_vals: dict[str, Any] = {
        "name":      WIZARD_MENU_LABEL,
        "parent_id": parent_menu_id,
        "action":    f"ir.actions.act_window,{int(aw_menu_id)}",
        # Séquence basse = haut du sous-menu (Odoo trie par ``sequence`` croissant) ; évite l'effet
        # « enterré » sous des dizaines d'entrées avec ``sequence`` 10, 20, …
        "sequence":  int(WIZARD_MENU_SEQUENCE),
    }

    menu_id = _ek(models, db, uid, pwd, "ir.ui.menu", "create", [menu_vals])
    result["menu_id"] = menu_id
    result["wizard_menu_parent_id"] = parent_menu_id
    _sync_wizard_menu_parent_with_report_menu(
        models,
        db,
        uid,
        pwd,
        int(menu_id),
        int(result["cpc_report_menu_id"]) if result.get("cpc_report_menu_id") else None,
    )
    # Relire le parent effectif après alignement sur le menu rapport
    try:
        _pm = _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.menu",
            "read",
            [[int(menu_id)]],
            {"fields": ["parent_id"]},
        )
        if _pm:
            parent_menu_id = _m2o_id_rpc(_pm[0].get("parent_id")) or parent_menu_id
            result["wizard_menu_parent_id"] = parent_menu_id
    except Exception:
        pass
    if not parent_menu_id:
        re_root = _reattach_wizard_menu_under_finance_root(
            models, db, uid, pwd, int(menu_id)
        )
        result["wizard_menu_parent_reattached_to"] = re_root
        if re_root:
            result["wizard_menu_parent_id"] = re_root
            parent_menu_id = re_root

    try:
        result["wizard_install_post_checks"] = verify_cpc_wizard_ui_install(
            models,
            db,
            uid,
            pwd,
            wizard_model=WIZARD_MODEL,
            model_id=int(model_id),
            server_action_id=int(sa_id),
            menu_act_window_id=int(aw_menu_id),
            view_id=int(view_id),
            menu_id=int(menu_id),
            parent_menu_id=parent_menu_id,
        )
    except Exception as wiz_v_exc:
        result["wizard_install_post_checks"] = {
            "ok": False,
            "checks": [],
            "errors": [f"Controle wizard UI : {wiz_v_exc}"],
            "warnings": [],
        }

    ba = result.get("budget_analytic_fields") or {}
    result["ok"] = True
    result["budget_analytic_fields_ok"] = bool(ba.get("ok", True))
    # Ne pas inclure by_model en entier dans message : le flash grossit la session cookie
    # (limite Werkzeug ~4093 octets) et provoque erreur à la redirection après POST.
    summary = _budget_fields_summary_for_user_message(ba)
    inst = result.get("cpc_toolbox_install") or {}
    new_rid = int((inst.get("report_id") or 0))
    if result.get("wizard_menu_parent_reattached_to"):
        _parent_hint = (
            f" Odoo : app Facturation ou Comptabilite — en bas du menu principal : {WIZARD_MENU_LABEL}"
        )
    elif parent_menu_src != "none":
        _parent_hint = (
            f" Odoo : Facturation/Comptabilite > Reporting > {WIZARD_MENU_LABEL}"
        )
    else:
        _parent_hint = (
            f" Odoo : chercher « {WIZARD_MENU_LABEL} » (Parametres > Menus) si l'entree ne s'affiche pas."
        )
    result["message"] = (
        f"Wizard Budget par projet cree : {WIZARD_MODEL}, action calcul id={sa_id}, menu id={menu_id}."
        f"{_parent_hint}"
        f" (formulaire : analytique, budget, periode ; bouton Remplir le rapport CPC). "
        f"Parent technique : {parent_menu_src!r}."
        f" Champs budget : {summary}."
    )
    _iac = result.get("wizard_ir_model_access") or {}
    if _iac.get("ok"):
        result["message"] += (
            f" Droits menu (profils comptables) : {_iac.get('access_count', 0)} règle(s) "
            "ir.model.access sur le wizard."
        )
    else:
        result["message"] += (
            " Alerte : aucun ir.model.access n'a pu être créé (groupes absents ?) — "
            "le menu peut rester invisible hors administrateur."
        )
    if new_rid:
        result["message"] += f" Rapport CPC toolbox recree (account.report id={new_rid})."
        _gl = int((inst.get("groupby_leaf_lines") or 0))
        if _gl:
            result["message"] += f" Detail par compte : {_gl} ligne(s) feuilles (depliage)."
        _mid_r = result.get("cpc_report_menu_id")
        if _mid_r:
            result["message"] += (
                f" Menu Reporting : {CPC_REPORT_MENU_LABEL!r} (menu id={_mid_r})."
            )
        elif result.get("cpc_report_menu_error"):
            result["message"] += (
                " Menu rapport Reporting non cree : "
                f"{str(result['cpc_report_menu_error'])[:180]}."
            )
        _mpc = result.get("cpc_report_menu_post_checks") or {}
        if isinstance(_mpc, dict) and not _mpc.get("ok", True):
            _e = _mpc.get("errors") or []
            if _e:
                result["message"] += " Controle menu rapport : " + "; ".join(str(x) for x in _e[:2]) + "."
            _w = _mpc.get("warnings") or []
            if _w:
                result["message"] += " " + "; ".join(str(x) for x in _w[:2]) + "."
    if not result["budget_analytic_fields_ok"]:
        result["message"] += (
            " Attention : certains champs x_analytic_account_id n'ont pas ete crees (voir detail JSON cote serveur)."
        )
    _wiz_pc = result.get("wizard_install_post_checks") or {}
    if isinstance(_wiz_pc, dict) and not _wiz_pc.get("ok", True):
        _we = _wiz_pc.get("errors") or []
        if _we:
            result["message"] += (
                " Controle assistant (menu/vue/actions) : "
                + "; ".join(str(x) for x in _we[:3])
                + "."
            )
    return result


def _menu_id_from_xmlid(
    models: Any, db: str, uid: int, pwd: str, module: str, xml_name: str
) -> int | None:
    """Résout ``ir.ui.menu`` via ``ir.model.data`` (indépendant de la langue d'affichage)."""
    rows = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.model.data",
        "search_read",
        [[["module", "=", module], ["name", "=", xml_name], ["model", "=", "ir.ui.menu"]]],
        {"fields": ["res_id"], "limit": 1},
    ) or []
    if not rows:
        return None
    rid = rows[0].get("res_id")
    return int(rid) if rid else None


def _sync_wizard_menu_parent_with_report_menu(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
    wizard_menu_id: int,
    report_menu_id: int | None,
) -> None:
    """
    Force le menu assistant sous le **même parent** que le menu « rapport CPC » (client action).

    Évite les cas où seul le menu 2. apparaît dans un sous-menu (ex. « Gestion ») alors que le 1.
    resterait rattaché à un autre parent après résolution xmlid / données hétérogènes.
    """
    if not report_menu_id:
        return
    try:
        rows = _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.menu",
            "read",
            [[int(report_menu_id)]],
            {"fields": ["parent_id"]},
        )
        if not rows:
            return
        pid = _m2o_id_rpc(rows[0].get("parent_id"))
        if not pid:
            return
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.menu",
            "write",
            [
                [int(wizard_menu_id)],
                {
                    "parent_id": int(pid),
                    "sequence": int(WIZARD_MENU_SEQUENCE),
                },
            ],
        )
    except Exception:
        pass


def _resolve_wizard_parent_menu(
    models: Any, db: str, uid: int, pwd: str
) -> tuple[int | None, str]:
    """
    Parent ``ir.ui.menu`` pour l'assistant : même résolution que les menus « rapports comptables »
    (``resolve_parent_menu_for_account_report``), puis repli sur ``_find_reports_menu``.
    """
    try:
        from web_app.odoo_account_reports import resolve_parent_menu_for_account_report

        rid = resolve_parent_menu_for_account_report(models, db, uid, pwd)
        if rid:
            return int(rid), "resolve_parent_menu_for_account_report"
    except Exception:
        pass
    rid = _find_reports_menu(models, db, uid, pwd)
    if rid:
        return int(rid), "_find_reports_menu"
    return None, "none"


def _reattach_wizard_menu_under_finance_root(
    models: Any, db: str, uid: int, pwd: str, menu_id: int
) -> int | None:
    """Dernier recours : rattacher le menu sous l'app Facturation (``menu_finance``) pour le rendre visible."""
    root = _menu_id_from_xmlid(models, db, uid, pwd, "account", "menu_finance")
    if not root:
        return None
    try:
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.menu",
            "write",
            [[int(menu_id)], {"parent_id": int(root), "sequence": 40}],
        )
        return int(root)
    except Exception:
        return None


def _find_reports_menu(models: Any, db: str, uid: int, pwd: str) -> int | None:
    """
    Parent pour placer l'assistant sous le menu Rapports / Reporting de la comptabilité.

    Odoo 19 (module ``account``) : ``account.menu_finance_reports`` (« Reporting ») est enfant
    de ``menu_finance`` (app Facturation / Invoicing) — le nom du parent n'est souvent **pas**
    « Comptabilité », d'où l'échec de l'ancienne recherche et un menu introuvable ou mal placé.
    """
    # 1) Xmlid : **menu_finance_reports** en premier (menu Reporting visible) ; états légaux en repli
    #    (même logique que ``_ACCOUNT_REPORT_MENU_PARENT_XMLIDS`` dans odoo_account_reports.py).
    for mod, xid in (
        ("account", "menu_finance_reports"),
        ("account_accountant", "menu_finance_reports"),
        ("account_reports", "menu_finance_reports"),
        ("account", "account_reports_legal_statements_menu"),
        ("account_reports", "account_reports_legal_statements_menu"),
    ):
        mid = _menu_id_from_xmlid(models, db, uid, pwd, mod, xid)
        if mid:
            return mid

    # 2) Enfant de la racine Compta / Facturation (menu_finance)
    root = _menu_id_from_xmlid(models, db, uid, pwd, "account", "menu_finance")
    if root:
        mids = _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.menu",
            "search",
            [[
                ("parent_id", "=", int(root)),
                ("name", "in", [
                    "Reporting", "Rapports", "Reports", "Statement Reports",
                    "Analyse", "Analysis",
                ]),
            ]],
            {"limit": 1, "order": "sequence asc"},
        ) or []
        if mids:
            return int(mids[0])

    # 3) Ancienne heuristique (parent libellé Comptabilité / Accounting)
    ids = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.ui.menu",
        "search",
        [[("name", "in", ["Rapports", "Reports", "Reporting"]),
          "|",
          ("parent_id.name", "ilike", "Comptabilit"),
          ("parent_id.name", "ilike", "Accounting")]],
        {"limit": 1},
    )
    if ids:
        return int(ids[0])
    ids = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.ui.menu",
        "search",
        [[("name", "in", ["Rapports", "Reports", "Reporting"])]],
        {"limit": 1},
    )
    if ids:
        return int(ids[0])

    # 4) Dernier recours : sous l'app Facturation (mieux que parent_id absent)
    if root:
        return int(root)
    return None


# ---------------------------------------------------------------------------
# Suppression du wizard
# ---------------------------------------------------------------------------

def _purge_cpc_toolbox_account_reports(
    models: Any, db: str, uid: int, pwd: str
) -> tuple[list[int], str | None]:
    """
    Supprime les ``account.report`` toolbox CPC Senedoo (lignes, colonnes, etc.) ainsi que
    les menus / ``ir.actions.client`` liés (même logique qu'avant recréation à l'installation).
    Retourne ``(ids_supprimés, message_erreur_ou_None)``.
    """
    import sys
    from pathlib import Path

    ac = Path(__file__).resolve().parent / "archives-cli"
    if ac.is_dir() and str(ac) not in sys.path:
        sys.path.insert(0, str(ac))
    try:
        from create_cpc_budget_analytique import purge_cpc_budget_analytique_instances

        rids = purge_cpc_budget_analytique_instances(models, db, uid, pwd)
        return (list(rids), None)
    except Exception as exc:
        return ([], str(exc))


def _unlink_orphan_cpc_report_menus(
    models: Any, db: str, uid: int, pwd: str
) -> list[int]:
    """Menus Reporting encore présents sous le libellé courant ou historique du rapport (orphelins)."""
    labels = (CPC_REPORT_MENU_LABEL,) + tuple(CPC_REPORT_MENU_PREVIOUS_NAMES)
    found: list[int] = []
    for lab in labels:
        part = (
            _ek(
                models,
                db,
                uid,
                pwd,
                "ir.ui.menu",
                "search",
                [[("name", "=", lab)]],
            )
            or []
        )
        found.extend(int(x) for x in part)
    ids = sorted(set(found))
    if ids:
        try:
            _ek(models, db, uid, pwd, "ir.ui.menu", "unlink", [ids])
        except Exception:
            pass
    return ids


def _collect_cpc_wizard_menu_ids(
    models: Any, db: str, uid: int, pwd: str
) -> set[int]:
    """
    Tous les ``ir.ui.menu`` à retirer avec le wizard : noms exacts (actuel + historique),
    menus dont l'action pointe vers une fenêtre ``res_model=x_cpc_budget_wizard``,
    et entrées orphelines dont le libellé correspond encore aux motifs toolbox.
    """
    out: set[int] = set()
    exact = [WIZARD_MENU_LABEL] + list(WIZARD_MENU_PREVIOUS_NAMES)
    ids = _ek(models, db, uid, pwd, "ir.ui.menu", "search", [[("name", "in", exact)]]) or []
    out.update(int(x) for x in ids)

    aw_ids = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.actions.act_window",
        "search",
        [[("res_model", "=", WIZARD_MODEL)]],
    ) or []
    for aid in aw_ids:
        astr = f"ir.actions.act_window,{int(aid)}"
        mids = _ek(
            models, db, uid, pwd, "ir.ui.menu", "search", [[("action", "=", astr)]]
        ) or []
        out.update(int(x) for x in mids)

    for pat in WIZARD_MENU_ILIKE_PATTERNS:
        mids = _ek(
            models, db, uid, pwd, "ir.ui.menu", "search", [[("name", "ilike", pat)]]
        ) or []
        out.update(int(x) for x in mids)

    return out


def purge_cpc_wizard(models: Any, db: str, uid: int, pwd: str) -> dict[str, Any]:
    """
    Supprime le wizard Budget par projet (modèle, vues, menus, actions fenêtre, actions serveur)
    et le rapport ``account.report`` toolbox CPC (menus Reporting + actions client associées).
    """
    purged: list[str] = []

    report_rids, report_err = _purge_cpc_toolbox_account_reports(models, db, uid, pwd)
    if report_rids:
        purged.append(f"account_report({report_rids})")
    elif report_err:
        purged.append(f"account_report_error({report_err[:220]})")

    orphan_report_menus = _unlink_orphan_cpc_report_menus(models, db, uid, pwd)
    if orphan_report_menus:
        purged.append(f"menus_rapport_cpc({orphan_report_menus})")

    menu_ids = sorted(_collect_cpc_wizard_menu_ids(models, db, uid, pwd))
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
            "message": f"Wizard Budget par projet supprime : {', '.join(purged) or 'rien trouve'}."}


# ---------------------------------------------------------------------------
# Vérification
# ---------------------------------------------------------------------------

def cpc_wizard_exists(models: Any, db: str, uid: int, pwd: str) -> bool:
    """True si le wizard (ir.model x_cpc_budget_wizard) est déjà installé sur cette base."""
    return _model_exists(models, db, uid, pwd, WIZARD_MODEL)
