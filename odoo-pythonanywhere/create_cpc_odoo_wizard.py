"""
Crée dans Odoo (via XML-RPC) un wizard natif « Budget par projet » (CPC SYSCOHADA).

Le wizard est un modèle manuel (x_cpc_budget_wizard) avec :
  - Compte analytique, budget financier (account.report.budget), période Du/Au
  - Bouton « Calculer » → server action Python qui :
      1. Vérifie la cohérence analytique avec le budget (champs Studio optionnels sur account.report.budget)
      2. Lit account.move.line (filtré analytique) → réalisé CPC
      3. Lit account.report.budget.item (filtré par budget + période + analytique sur ligne si présent)
      4. Écrit account.report.external.value (expressions Budget ``external``, label ``budget``)
      5. Ouvre le rapport CPC dans Odoo (rapport toolbox unique ``CPC_REPORT_TOOLBOX_EXACT``)
  - Menus : Facturation/Comptabilité > Reporting > Assistant budget projet (Senedoo) — action serveur → formulaire ;
    Reporting > … > CPC SYSCOHADA — rapport budget projet (Senedoo).
  - Rapport CPC : **pas** de filtre analytique Odoo sur la fiche du rapport (incompatible avec un écart
    cohérent vs budget sur plusieurs bases Enterprise). La colonne « Réalisé (axe) » est ``realise_axe``
    (moteur **external** + ``account.report.external.value``) ; l’« Écart » = ``budget − realise_axe``.
    Le wizard injecte ``realise_axe`` et le budget (**external** si la base n’expose pas le moteur
    natif ``budget``) pour la même période et le même axe. Voir **DEPLOY_PYTHONANYWHERE.md** (section
    utilitaires, CPC) et le docstring de ``create_cpc_budget_analytique.py`` pour le détail « pourquoi
    external » et les liens doc **Odoo 18.0**.
  - Colonne Budget (hors moteur natif ``budget``) : remplie depuis le budget financier choisi dans le
    wizard (pas de saisie manuelle au crayon).

Les champs manuels ``x_analytic_account_id`` sur ``account.report.budget`` et
``account.report.budget.item`` sont créés par la toolbox (idempotent si déjà présents).

Aucune dépendance module custom — fonctionne sur Odoo 18–19 SaaS Enterprise (réf. doc v18 ; 17 en pratique souvent OK — droits admin / Studio).

Usage Flask toolbox (action staff.py) :
    from create_cpc_odoo_wizard import create_cpc_wizard, purge_cpc_wizard, cpc_wizard_exists
    (``purge_cpc_wizard`` retire aussi le rapport ``account.report`` toolbox et ses menus.)
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WIZARD_MODEL   = "x_cpc_budget_wizard"
WIZARD_NAME    = "Budget par projet (Senedoo)"
WIZARD_MENU_LABEL = "Assistant budget projet (Senedoo)"
# Anciens libellés de menu (purge pour éviter doublons après renommage)
WIZARD_MENU_PREVIOUS_NAMES = (
    "CPC Budget Analytique (Senedoo)",
    "Budget par projet (Senedoo)",
)
# Motifs ilike sur ir.ui.menu.name (orphelins après suppression Studio / modèle, libellés partiels)
WIZARD_MENU_ILIKE_PATTERNS = ("%CPC Budget%", "%Budget par projet%", "%Assistant budget%")
# Menu Reporting distinct du wizard : ouverture directe du rapport (dépliage par compte).
CPC_REPORT_MENU_LABEL = "CPC SYSCOHADA — rapport budget projet (Senedoo)"
CPC_REPORT_NAME_LIKE = "CPC SYSCOHADA"        # recherche ilike de secours dans account.report
# Nom exact du account.report créé par la toolbox (aligné sur create_cpc_budget_analytique)
CPC_REPORT_TOOLBOX_EXACT = "CPC SYSCOHADA — Budget par projet (Senedoo)"

# Champs créés sur les modèles budget reporting (Many2one vers l’axe analytique)
BUDGET_ANALYTIC_FIELD_NAME = "x_analytic_account_id"
BUDGET_MODELS_WITH_ANALYTIC_M2O = (
    "account.report.budget",
    "account.report.budget.item",
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

# Expressions colonne Budget (moteur external uniquement)
expr_by_code = {}
# Colonne Réalisé (axe) — external ; alimentée comme le budget (pas le filtre analytique du rapport)
expr_realise_by_code = {}
for line in env['account.report.line'].search([('report_id', '=', cpc_report_id)]):
    if not line.code:
        continue
    for expr in env['account.report.expression'].search([
        ('report_line_id', '=', line.id),
        ('label', '=', 'budget'),
        ('engine', '=', 'external'),
    ]):
        expr_by_code[line.code] = expr.id
    for expr in env['account.report.expression'].search([
        ('report_line_id', '=', line.id),
        ('label', '=', 'realise_axe'),
        ('engine', '=', 'external'),
    ]):
        expr_realise_by_code[line.code] = expr.id

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
            raw_dist = _parse_flat_json_obj(raw_dist)
        except Exception:
            continue
        if raw_dist is None:
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

# ------------------------------------------------------------------ ecriture external values (realise axe + budget external)
company_id = env.company.id

for code, expr_id in expr_realise_by_code.items():
    val = float(line_realized.get(code, 0.0))
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
written_r = len(expr_realise_by_code)
written_b = len(expr_by_code)
wizard.write({
    'x_status': (
        "OK - realise axe " + str(written_r) + " ligne(s), budget external " + str(written_b) + ". "
        "Ne pas activer le filtre analytique du rapport Odoo (desactive sur ce CPC). "
        "Analytique utilise : " + str(analytic_id) + "."
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
        1) Choisissez le <strong>compte analytique du projet</strong>.
        2) Choisissez le <strong>budget financier</strong> (liste filtree sur l'axe lorsque le modele budget
        expose un champ analytique reconnu par la toolbox).
        3) Ajustez la <strong>periode</strong> si besoin, puis <strong>Remplir le rapport CPC</strong>.
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
    menu_server_action_id: int,
    view_id: int,
    menu_id: int,
    parent_menu_id: int | None,
) -> dict[str, Any]:
    """
    Contrôle post-création : actions serveur, vue formulaire, menu (lecture + cohérence).
    Retourne ``{"ok": bool, "checks": [...], "errors": [...], "warnings": [...]}``.
    """
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    mid = int(model_id)
    sa = int(server_action_id)
    sa_m = int(menu_server_action_id)
    vid = int(view_id)
    mn = int(menu_id)
    exp_menu_action = f"ir.actions.server,{sa_m}"

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

    rows_sm = _ek(
        models,
        db,
        uid,
        pwd,
        "ir.actions.server",
        "read",
        [[sa_m]],
        {"fields": ["id", "state", "code"]},
    )
    if not rows_sm:
        errors.append(f"ir.actions.server id={sa_m} (menu) introuvable en lecture.")
    else:
        r1 = rows_sm[0]
        st_m = (r1.get("state") or "").strip()
        st_m_ok = st_m == "code"
        checks.append({"step": "server_action_menu_state", "ok": st_m_ok, "state": st_m})
        if not st_m_ok:
            errors.append(f"Action menu : state attendu code, obtenu {st_m!r}.")
        code = str(r1.get("code") or "")
        code_ok = (
            "ir.actions.act_window" in code
            and wizard_model in code
            and str(vid) in code
        )
        checks.append(
            {
                "step": "server_action_menu_code_window",
                "ok": code_ok,
                "has_act_window": "ir.actions.act_window" in code,
                "has_model": wizard_model in code,
                "has_view_id": str(vid) in code,
            }
        )
        if not code_ok:
            errors.append(
                "Action menu : le code ne semble pas ouvrir la vue formulaire attendue "
                f"(modele {wizard_model!r}, view_id {vid})."
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

    # ---- 5. Action serveur « menu » : ouvre le formulaire (pleine page + dates par défaut)
    _vid = int(view_id)
    menu_opener_code = (
        "_ctx = {}\n"
        "try:\n"
        "    _today = context_today()\n"
        "    _first = _today.replace(day=1)\n"
        "    _ctx = {'default_x_date_from': str(_first), 'default_x_date_to': str(_today)}\n"
        "except Exception:\n"
        "    pass\n"
        "action = {\n"
        '    "type": "ir.actions.act_window",\n'
        f'    "name": {repr(WIZARD_NAME)},\n'
        f'    "res_model": {repr(WIZARD_MODEL)},\n'
        '    "view_mode": "form",\n'
        f'    "views": [[{_vid}, "form"]],\n'
        '    "target": "current",\n'
        '    "context": _ctx,\n'
        "}\n"
    )
    sa_menu_id = _ek(models, db, uid, pwd, "ir.actions.server", "create", [{
        "name":     f"Ouvrir {WIZARD_MENU_LABEL}",
        "model_id": model_id,
        "state":    "code",
        "code":     menu_opener_code,
    }])
    result["menu_server_action_id"] = sa_menu_id

    # ---- 6. Menu sous Reporting (même parent que les rapports comptables Senedoo ; pas de copie
    #     groups_id du parent : sur certaines bases Enterprise cela masquait l'entrée pour les utilisateurs.)
    parent_menu_id, parent_menu_src = _resolve_wizard_parent_menu(models, db, uid, pwd)
    result["wizard_menu_parent_source"] = parent_menu_src

    menu_vals: dict[str, Any] = {
        "name":      WIZARD_MENU_LABEL,
        "parent_id": parent_menu_id,
        "action":    f"ir.actions.server,{int(sa_menu_id)}",
        "sequence":  99,
    }

    menu_id = _ek(models, db, uid, pwd, "ir.ui.menu", "create", [menu_vals])
    result["menu_id"] = menu_id
    result["wizard_menu_parent_id"] = parent_menu_id
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
            menu_server_action_id=int(sa_menu_id),
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
            [[int(menu_id)], {"parent_id": int(root), "sequence": 950}],
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
    # 1) Xmlid officiels (EE : états légaux / rapports ; CE : menu_finance_reports)
    for mod, xid in (
        ("account", "account_reports_legal_statements_menu"),
        ("account_reports", "account_reports_legal_statements_menu"),
        ("account", "menu_finance_reports"),
        ("account_accountant", "menu_finance_reports"),
        ("account_reports", "menu_finance_reports"),
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
    """Menus Reporting encore présents sous le libellé exact du rapport (orphelins)."""
    mids = (
        _ek(
            models,
            db,
            uid,
            pwd,
            "ir.ui.menu",
            "search",
            [[("name", "=", CPC_REPORT_MENU_LABEL)]],
        )
        or []
    )
    ids = sorted({int(x) for x in mids})
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
