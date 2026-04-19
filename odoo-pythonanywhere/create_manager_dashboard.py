"""
Installe dans Odoo SaaS (via XML-RPC) un wizard Tableau de Bord Manager.

Le tableau de bord s'execute entierement dans l'environnement Odoo :
  - Modele manuel x_manager_dashboard_wizard
  - Server action Python qui calcule les KPIs et ecrit le HTML dans x_result_html
  - Vue formulaire avec parametres + bouton Calculer + zone d'affichage HTML
  - Menu : Comptabilite > Rapports > Tableau de Bord Manager (Senedoo)

KPIs couverts (si modules installes) :
  - Ventes (CA, commandes, panier moyen, top clients)
  - Achats (volume, commandes, top fournisseurs)
  - Facturation (facture HT, impayes, en retard)
  - Tresorerie (solde bancaire, encaissements / decaissements)
  - Stock (valeur, ruptures, top categories)
  - Fabrication MRP (OFs, retards, en cours)

Comparaison automatique N vs N-1 pour toutes les sections.
Compatible Odoo 18–19 SaaS Enterprise (17 souvent OK).

Usage Flask toolbox :
    from create_manager_dashboard import (
        create_manager_dashboard,
        purge_manager_dashboard,
        manager_dashboard_exists,
    )
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

WIZARD_MODEL     = "x_manager_dashboard_wizard"
WIZARD_NAME      = "Tableau de Bord Manager"
WIZARD_MENU_LABEL = "Tableau de Bord Manager (Senedoo)"

# ---------------------------------------------------------------------------
# Server action code — s'execute dans l'environnement Odoo (env, record)
# ---------------------------------------------------------------------------
# IMPORTANT : raw string pour que les \ dans le code Python embarque soient
# preserves tels quels (Odoo les voit litteralement, Python les interprete
# ensuite lors du exec()).

_SERVER_ACTION_CODE = r"""
# Tableau de Bord Manager Senedoo — s'execute dans Odoo (env, record)
from datetime import date as _d
import calendar as _c

# ---- Utilitaires ----

def _s(fn, dft=None):
    try: return fn()
    except Exception: return dft

def _p(n, n1):
    if not n1: return None
    return round((n - n1) / abs(n1) * 100, 1)

def _f(v):
    # Formate un nombre : 1.2M, 5k, etc.
    if v is None: return 'N/A'
    v = float(v)
    if abs(v) >= 1_000_000: return f'{v / 1_000_000:.1f}M'
    if abs(v) >= 1_000:     return f'{v / 1_000:.0f}k'
    return str(int(round(v)))

def _b(pct, inv=False):
    # Badge de variation colore (vert/rouge).
    if pct is None: return ''
    ok  = (pct >= 0) if not inv else (pct <= 0)
    col = '#20c997' if ok else '#dc3545'
    arr = '&#9650;' if pct >= 0 else '&#9660;'
    return f'<span style="color:{col};font-size:11px;font-weight:600">{arr} {abs(pct):.1f}%</span>'

# ---- Calcul des periodes ----

def _periods(rec):
    pt    = rec.x_period_type or 'year'
    today = _d.today()
    try:   y = int(rec.x_ref_year  or today.year)
    except: y = today.year
    try:   m = int(rec.x_ref_month or today.month)
    except: m = today.month
    if not (1 <= m <= 12): m = today.month
    MN = ['Janvier','Fevrier','Mars','Avril','Mai','Juin',
          'Juillet','Aout','Septembre','Octobre','Novembre','Decembre']
    if pt == 'month':
        ld = _c.monthrange(y, m)[1]
        df_n,  dt_n  = _d(y,   m, 1), _d(y,   m, ld)
        df_n1, dt_n1 = _d(y-1, m, 1), _d(y-1, m, _c.monthrange(y-1, m)[1])
        ln, ln1 = f'{MN[m-1]} {y}', f'{MN[m-1]} {y-1}'
    elif pt in ('q1', 'q2', 'q3', 'q4'):
        q  = int(pt[1]); fm = (q-1)*3+1; lm = q*3
        df_n,  dt_n  = _d(y,   fm, 1), _d(y,   lm, _c.monthrange(y,   lm)[1])
        df_n1, dt_n1 = _d(y-1, fm, 1), _d(y-1, lm, _c.monthrange(y-1, lm)[1])
        ln, ln1 = f'T{q} {y}', f'T{q} {y-1}'
    elif pt == 'ytd':
        df_n  = _d(y, 1, 1)
        dt_n  = today if today.year == y else _d(y, 12, 31)
        df_n1 = _d(y-1, 1, 1)
        dt_n1 = _d(y-1, today.month, today.day)
        ln, ln1 = f'Cumul {y} YTD', f'Cumul {y-1} YTD'
    elif pt == 'custom' and rec.x_date_from_custom and rec.x_date_to_custom:
        df_n,  dt_n  = rec.x_date_from_custom,              rec.x_date_to_custom
        df_n1, dt_n1 = df_n.replace(year=df_n.year-1),      dt_n.replace(year=dt_n.year-1)
        ln  = f'{df_n.strftime("%d/%m/%Y")} au {dt_n.strftime("%d/%m/%Y")}'
        ln1 = f'{df_n1.strftime("%d/%m/%Y")} au {dt_n1.strftime("%d/%m/%Y")}'
    else:  # year par defaut
        df_n,  dt_n  = _d(y,   1, 1), _d(y,   12, 31)
        df_n1, dt_n1 = _d(y-1, 1, 1), _d(y-1, 12, 31)
        ln, ln1 = f'Annee {y}', f'Annee {y-1}'
    return str(df_n), str(dt_n), str(df_n1), str(dt_n1), ln, ln1

# ---- Detection modules ----

def _mods():
    targets = ['sale', 'purchase', 'stock', 'account', 'mrp', 'account_accountant']
    rows = env['ir.module.module'].sudo().search_read(
        [('name', 'in', targets), ('state', '=', 'installed')], ['name'])
    return {r['name'] for r in rows}

# ---- Domaines ----

def _cd(cid): return [('company_id', '=', cid)] if cid else []

# ---- read_group wrapper compatible Odoo 18–19 (17 souvent OK) ----

def _rg(mn, dom, fields, groupby, order='', lim=0):
    M = env[mn].sudo()
    try:
        kw = {}
        if order: kw['orderby'] = order
        if lim:   kw['limit']   = lim
        return M.read_group(dom, fields, groupby, **kw) or []
    except Exception:
        return []

# ---- KPI Ventes ----

def _kpi_sales(df_n, dt_n, df_n1, dt_n1, cid):
    def _fetch(df, dt):
        dom = ([('state', 'in', ['sale', 'done']),
                ('date_order', '>=', df), ('date_order', '<=', dt + ' 23:59:59')]
               + _cd(cid))
        r   = _rg('sale.order', dom, ['amount_untaxed:sum', 'id:count'], [])
        a   = r[0] if r else {}
        rev = float(a.get('amount_untaxed') or 0)
        cnt = int(a.get('id') or 0)
        top = _rg('sale.order', dom, ['partner_id', 'amount_untaxed:sum'],
                  ['partner_id'], 'amount_untaxed desc', 5)
        return {'rev': rev, 'cnt': cnt, 'avg': round(rev / cnt, 0) if cnt else 0,
                'top': [{'n': t['partner_id'][1] if t.get('partner_id') else '?',
                          'v': float(t.get('amount_untaxed') or 0)} for t in top]}
    n  = _s(lambda: _fetch(df_n,  dt_n),  {'rev': 0, 'cnt': 0, 'avg': 0, 'top': []})
    n1 = _s(lambda: _fetch(df_n1, dt_n1), {'rev': 0, 'cnt': 0, 'avg': 0, 'top': []})
    return {'rev_n':  n['rev'],  'rev_n1':  n1['rev'],  'rev_pct':  _p(n['rev'],  n1['rev']),
            'cnt_n':  n['cnt'],  'cnt_n1':  n1['cnt'],  'cnt_pct':  _p(n['cnt'],  n1['cnt']),
            'avg_n':  n['avg'],  'top': n['top']}

# ---- KPI Achats ----

def _kpi_purch(df_n, dt_n, df_n1, dt_n1, cid):
    def _fetch(df, dt):
        dom = ([('state', 'in', ['purchase', 'done']),
                ('date_order', '>=', df), ('date_order', '<=', dt + ' 23:59:59')]
               + _cd(cid))
        r   = _rg('purchase.order', dom, ['amount_untaxed:sum', 'id:count'], [])
        a   = r[0] if r else {}
        amt = float(a.get('amount_untaxed') or 0)
        cnt = int(a.get('id') or 0)
        top = _rg('purchase.order', dom, ['partner_id', 'amount_untaxed:sum'],
                  ['partner_id'], 'amount_untaxed desc', 5)
        return {'amt': amt, 'cnt': cnt,
                'top': [{'n': t['partner_id'][1] if t.get('partner_id') else '?',
                          'v': float(t.get('amount_untaxed') or 0)} for t in top]}
    n  = _s(lambda: _fetch(df_n,  dt_n),  {'amt': 0, 'cnt': 0, 'top': []})
    n1 = _s(lambda: _fetch(df_n1, dt_n1), {'amt': 0, 'cnt': 0, 'top': []})
    return {'amt_n':  n['amt'],  'amt_n1':  n1['amt'],  'amt_pct':  _p(n['amt'],  n1['amt']),
            'cnt_n':  n['cnt'],  'cnt_n1':  n1['cnt'],  'top': n['top']}

# ---- KPI Facturation ----

def _kpi_inv(df_n, dt_n, df_n1, dt_n1, cid):
    ts   = str(_d.today())
    base = _cd(cid)
    def _q(df, dt):
        dom = ([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
                ('invoice_date', '>=', df), ('invoice_date', '<=', dt)] + base)
        r = _rg('account.move', dom, ['amount_untaxed_signed:sum', 'id:count'], [])
        a = r[0] if r else {}
        return {'amt': float(a.get('amount_untaxed_signed') or 0), 'cnt': int(a.get('id') or 0)}
    n  = _s(lambda: _q(df_n,  dt_n),  {'amt': 0, 'cnt': 0})
    n1 = _s(lambda: _q(df_n1, dt_n1), {'amt': 0, 'cnt': 0})
    udom = ([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
             ('payment_state', 'in', ['not_paid', 'partial'])] + base)
    up  = _rg('account.move', udom, ['amount_residual:sum', 'id:count'], [])
    ua  = up[0] if up else {}
    odom = udom + [('invoice_date_due', '<', ts)]
    ov  = _rg('account.move', odom, ['amount_residual:sum', 'id:count'], [])
    oa  = ov[0] if ov else {}
    return {'inv_n':  n['amt'],  'inv_n1':  n1['amt'],  'inv_pct':  _p(n['amt'],  n1['amt']),
            'cnt_n':  n['cnt'],  'cnt_n1':  n1['cnt'],
            'up_amt': float(ua.get('amount_residual') or 0),
            'up_cnt': int(ua.get('id') or 0),
            'ov_amt': float(oa.get('amount_residual') or 0),
            'ov_cnt': int(oa.get('id') or 0)}

# ---- KPI Tresorerie ----

def _kpi_treas(df_n, dt_n, df_n1, dt_n1, cid):
    base = _cd(cid)
    bk   = _s(lambda: env['account.account'].sudo().search_read(
        [('account_type', 'in', ['asset_cash', 'asset_bank']),
         ('deprecated', '=', False)] + base,
        ['name', 'current_balance'], limit=50), []) or []
    bal  = sum(float(r.get('current_balance') or 0) for r in bk)
    def _fl(df, dt):
        di = [('payment_type', '=', 'inbound'),  ('state', '=', 'posted'),
              ('date', '>=', df), ('date', '<=', dt)] + base
        do = [('payment_type', '=', 'outbound'), ('state', '=', 'posted'),
              ('date', '>=', df), ('date', '<=', dt)] + base
        ri = _rg('account.payment', di, ['amount:sum'], [])
        ro = _rg('account.payment', do, ['amount:sum'], [])
        return {'i': float((ri[0] if ri else {}).get('amount') or 0),
                'o': float((ro[0] if ro else {}).get('amount') or 0)}
    fn  = _s(lambda: _fl(df_n,  dt_n),  {'i': 0, 'o': 0})
    fn1 = _s(lambda: _fl(df_n1, dt_n1), {'i': 0, 'o': 0})
    return {'bal':   bal,
            'bk':    [{'n': r['name'], 'b': float(r.get('current_balance') or 0)} for r in bk[:5]],
            'in_n':  fn['i'],  'in_n1':  fn1['i'],  'in_pct':  _p(fn['i'],  fn1['i']),
            'out_n': fn['o'],  'out_n1': fn1['o'],  'out_pct': _p(fn['o'],  fn1['o']),
            'net_n': fn['i'] - fn['o'], 'net_n1': fn1['i'] - fn1['o']}

# ---- KPI Stock ----

def _kpi_stock(cid):
    base = _cd(cid)
    vr = _rg('stock.quant', [('location_id.usage', '=', 'internal')] + base,
             ['value:sum', 'quantity:sum'], [])
    va = vr[0] if vr else {}
    cr = _rg('stock.quant', [('location_id.usage', '=', 'internal')] + base,
             ['product_id.categ_id', 'value:sum'], ['product_id.categ_id'], 'value desc', 5)
    cats = [{'n': (r.get('product_id.categ_id') or ['', '?'])[1],
              'v': float(r.get('value') or 0)} for r in cr]
    so = _s(lambda: env['stock.warehouse.orderpoint'].sudo().search_count(
        [('qty_on_hand', '<=', 0)] + _cd(cid)), 0)
    return {'val': float(va.get('value') or 0),
            'qty': float(va.get('quantity') or 0),
            'cats': cats,
            'so':   int(so or 0)}

# ---- KPI Fabrication ----

def _kpi_mrp(df_n, dt_n, df_n1, dt_n1, cid):
    base = _cd(cid)
    ts   = str(_d.today())
    def _fetch(df, dt):
        dom = [('date_start', '>=', df), ('date_start', '<=', dt + ' 23:59:59')] + base
        rws = _rg('mrp.production', dom, ['state', 'id:count'], ['state'])
        bs  = {r['state']: int(r.get('id') or 0) for r in rws}
        tot = sum(bs.values()); done = bs.get('done', 0)
        return {'tot': tot, 'done': done, 'pct': round(done / tot * 100, 1) if tot else 0}
    n  = _s(lambda: _fetch(df_n,  dt_n),  {'tot': 0, 'done': 0, 'pct': 0})
    n1 = _s(lambda: _fetch(df_n1, dt_n1), {'tot': 0, 'done': 0, 'pct': 0})
    late = _s(lambda: env['mrp.production'].sudo().search_count(
        [('state', 'not in', ['done', 'cancel']), ('date_deadline', '<', ts)] + base), 0)
    wip  = _s(lambda: env['mrp.production'].sudo().search_count(
        [('state', 'in', ['confirmed', 'progress', 'to_close'])] + base), 0)
    return {'tot_n': n['tot'], 'tot_n1': n1['tot'], 'tot_pct': _p(n['tot'], n1['tot']),
            'done_n': n['done'], 'pct_n': n['pct'],
            'late': int(late or 0), 'wip': int(wip or 0)}

# ---- Constructeur HTML (style Senedoo) ----

PR = '#6f2da8'; BG = '#f4f1fa'; WH = '#ffffff'
SU = '#20c997'; DA = '#dc3545'; MU = '#6c757d'; BO = '#e2d9f3'; TX = '#1a0533'

def _card(title, color, html):
    return (f'<td style="vertical-align:top;padding:8px;width:50%">'
            f'<div style="border:2px solid {BO};border-radius:10px;overflow:hidden;background:{WH}">'
            f'<div style="background:{color};color:{WH};padding:10px 14px;font-weight:700;font-size:13px">{title}</div>'
            f'<div style="padding:12px 14px">{html}</div>'
            f'</div></td>')

def _card_full(title, color, html):
    return (f'<div style="border:2px solid {BO};border-radius:10px;overflow:hidden;'
            f'background:{WH};margin:8px">'
            f'<div style="background:{color};color:{WH};padding:10px 14px;font-weight:700;font-size:13px">{title}</div>'
            f'<div style="padding:12px 14px">{html}</div>'
            f'</div>')

def _th(ln, ln1):
    s = f'padding:4px 8px;font-size:11px;border-bottom:2px solid {BO};text-align:left'
    return (f'<table style="width:100%;border-collapse:collapse">'
            f'<tr><th style="{s};color:{MU}">Indicateur</th>'
            f'<th style="{s};color:{TX}">{ln}</th>'
            f'<th style="{s};color:{MU}">{ln1}</th>'
            f'<th style="{s}"></th></tr>')

def _tr(lbl, n, n1, pct, inv=False):
    s = f'padding:5px 8px;border-bottom:1px solid {BO}'
    return (f'<tr><td style="{s};font-size:12px;color:{MU}">{lbl}</td>'
            f'<td style="{s};font-size:13px;font-weight:600;color:{TX}">{n}</td>'
            f'<td style="{s};font-size:12px;color:{MU}">{n1}</td>'
            f'<td style="{s}">{_b(pct, inv)}</td></tr>')

def _top5(items):
    if not items: return ''
    rows = ''.join(
        f'<tr><td style="font-size:11px;padding:2px 8px;color:{MU}">{i["n"]}</td>'
        f'<td style="font-size:11px;padding:2px 8px;text-align:right;font-weight:600">{_f(i["v"])}</td></tr>'
        for i in items)
    return (f'<details style="margin-top:8px">'
            f'<summary style="font-size:12px;color:{PR};cursor:pointer;font-weight:600">Top 5 &#9658;</summary>'
            f'<table style="width:100%;border-collapse:collapse;margin-top:4px">{rows}</table></details>')

def _big_kpi(value, label, color=None):
    c = color or PR
    return (f'<div style="display:inline-block;margin-right:20px;text-align:center">'
            f'<div style="font-size:26px;font-weight:800;color:{c}">{value}</div>'
            f'<div style="font-size:11px;color:{MU}">{label}</div></div>')

# ============================================================
# MAIN
# ============================================================

rec = record
cid = rec.x_company_id.id if rec.x_company_id else None

df_n, dt_n, df_n1, dt_n1, ln, ln1 = _periods(rec)
mods = _mods()

has_sale  = 'sale'     in mods
has_purch = 'purchase' in mods
has_acc   = 'account'  in mods or 'account_accountant' in mods
has_stock = 'stock'    in mods
has_mrp   = 'mrp'      in mods

kpi_s = _s(lambda: _kpi_sales( df_n, dt_n, df_n1, dt_n1, cid)) if has_sale  else None
kpi_p = _s(lambda: _kpi_purch( df_n, dt_n, df_n1, dt_n1, cid)) if has_purch else None
kpi_i = _s(lambda: _kpi_inv(   df_n, dt_n, df_n1, dt_n1, cid)) if has_acc   else None
kpi_t = _s(lambda: _kpi_treas( df_n, dt_n, df_n1, dt_n1, cid)) if has_acc   else None
kpi_k = _s(lambda: _kpi_stock( cid))                            if has_stock else None
kpi_m = _s(lambda: _kpi_mrp(   df_n, dt_n, df_n1, dt_n1, cid)) if has_mrp   else None

# -- En-tete --
parts = [
    f'<div style="background:{BG};padding:16px;font-family:Arial,Helvetica,sans-serif">',
    f'<div style="background:{PR};border-radius:12px;padding:18px 22px;margin-bottom:16px;color:{WH}">',
    f'<div style="font-size:20px;font-weight:800">&#128200; Tableau de Bord Manager</div>',
    f'<div style="font-size:13px;margin-top:4px;opacity:0.9">',
    f'<strong>{ln}</strong> vs {ln1}',
    f' &mdash; Calcule le {_d.today().strftime("%d/%m/%Y")}',
    f'</div></div>',
    f'<table style="width:100%;border-collapse:collapse"><tr>',
]

# -- Ventes --
if kpi_s:
    b  = _th(ln, ln1)
    b += _tr("Chiffre d'affaires", _f(kpi_s['rev_n']), _f(kpi_s['rev_n1']), kpi_s['rev_pct'])
    b += _tr('Commandes',          str(kpi_s['cnt_n']), str(kpi_s['cnt_n1']), kpi_s['cnt_pct'])
    b += _tr('Panier moyen',       _f(kpi_s['avg_n']),  '&mdash;', None)
    b += '</table>' + _top5(kpi_s['top'])
    parts.append(_card('&#128722; Ventes', PR, b))

# -- Achats --
if kpi_p:
    b  = _th(ln, ln1)
    b += _tr('Volume achats', _f(kpi_p['amt_n']), _f(kpi_p['amt_n1']), kpi_p['amt_pct'], inv=True)
    b += _tr('Commandes',     str(kpi_p['cnt_n']), str(kpi_p['cnt_n1']), kpi_p['cnt_pct'], inv=True)
    b += '</table>' + _top5(kpi_p['top'])
    parts.append(_card('&#128717; Achats', '#7b3fa0', b))

if kpi_s or kpi_p:
    parts.append('</tr><tr>')

# -- Facturation --
if kpi_i:
    b  = _th(ln, ln1)
    b += _tr('Facture HT',  _f(kpi_i['inv_n']),     _f(kpi_i['inv_n1']),            kpi_i['inv_pct'])
    b += _tr('Nb factures', str(kpi_i['cnt_n']),     str(kpi_i['cnt_n1']),           None)
    b += _tr('Impayes',     _f(kpi_i['up_amt']),     str(kpi_i['up_cnt'])+' fact.',  None, inv=True)
    b += _tr('En retard',   _f(kpi_i['ov_amt']),     str(kpi_i['ov_cnt'])+' fact.',  None, inv=True)
    b += '</table>'
    parts.append(_card('&#128196; Facturation', '#2b6cb0', b))

# -- Tresorerie --
if kpi_t:
    bc = SU if kpi_t['bal'] >= 0 else DA
    b  = (f'<div style="text-align:center;padding:6px 0 12px">'
          f'<div style="font-size:28px;font-weight:800;color:{bc}">{_f(kpi_t["bal"])}</div>'
          f'<div style="font-size:11px;color:{MU}">Solde bancaire actuel</div>'
          f'</div>')
    b += _th(ln, ln1)
    b += _tr('Encaissements', _f(kpi_t['in_n']),  _f(kpi_t['in_n1']),  kpi_t['in_pct'])
    b += _tr('Decaissements', _f(kpi_t['out_n']), _f(kpi_t['out_n1']), kpi_t['out_pct'], inv=True)
    b += _tr('Flux net',      _f(kpi_t['net_n']), _f(kpi_t['net_n1']), None)
    b += '</table>'
    if kpi_t.get('bk'):
        brows = ''.join(
            f'<tr><td style="font-size:11px;padding:2px 8px;color:{MU}">{a["n"]}</td>'
            f'<td style="font-size:11px;padding:2px 8px;text-align:right">{_f(a["b"])}</td></tr>'
            for a in kpi_t['bk'])
        b += (f'<details style="margin-top:8px">'
              f'<summary style="font-size:12px;color:{PR};cursor:pointer">Comptes &#9658;</summary>'
              f'<table style="width:100%;border-collapse:collapse;margin-top:4px">{brows}</table></details>')
    parts.append(_card('&#127968; Tresorerie', '#276749', b))

parts.append('</tr></table>')

# -- Stock (pleine largeur) --
if kpi_k:
    sc = DA if kpi_k['so'] > 0 else SU
    b  = (_big_kpi(_f(kpi_k['val']), 'Valeur stock')
          + _big_kpi(str(kpi_k['so']), 'Rupture(s)', sc))
    if kpi_k['cats']:
        rows_c = ''.join(
            f'<tr><td style="font-size:11px;padding:2px 8px;color:{MU}">{c["n"]}</td>'
            f'<td style="font-size:11px;padding:2px 8px;text-align:right;font-weight:600">{_f(c["v"])}</td></tr>'
            for c in kpi_k['cats'])
        b += (f'<details style="margin-top:8px">'
              f'<summary style="font-size:12px;color:{PR};cursor:pointer">Par categorie &#9658;</summary>'
              f'<table style="width:100%;border-collapse:collapse;margin-top:4px">{rows_c}</table></details>')
    parts.append(_card_full('&#128230; Stock &amp; Logistique', '#744210', b))

# -- Fabrication (pleine largeur) --
if kpi_m:
    lc = DA if kpi_m['late'] > 0 else SU
    b  = (_big_kpi(str(kpi_m['tot_n']),  f'OFs periode {_b(kpi_m["tot_pct"])}')
          + _big_kpi(str(kpi_m['late']),  'En retard',  lc)
          + _big_kpi(str(kpi_m['wip']),   'En cours',   MU))
    b += _th(ln, ln1)
    b += _tr('Total OFs',       str(kpi_m['tot_n']),  str(kpi_m['tot_n1']), kpi_m['tot_pct'])
    b += _tr('OFs termines',    str(kpi_m['done_n']), '&mdash;',            None)
    b += _tr('Taux realisation', str(kpi_m['pct_n'])+'%', '&mdash;',        None)
    b += '</table>'
    parts.append(_card_full('&#127981; Fabrication', '#975a16', b))

if not any([kpi_s, kpi_p, kpi_i, kpi_t, kpi_k, kpi_m]):
    parts.append(f'<div style="text-align:center;padding:40px;color:{MU};font-size:14px">'
                 f'Aucun module detecte. Verifiez les modules installes sur cette base Odoo.'
                 f'</div>')

parts.append('</div>')

record.write({'x_result_html': ''.join(parts)})
"""


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


def _model_exists(models: Any, db: str, uid: int, pwd: str) -> bool:
    n = _ek(models, db, uid, pwd, "ir.model", "search_count",
            [[("model", "=", WIZARD_MODEL)]])
    return int(n or 0) > 0


def _find_reports_menu(models: Any, db: str, uid: int, pwd: str) -> int | None:
    """Cherche le menu Rapports sous Comptabilite — 1 ou 2 appels max."""
    ids = _ek(
        models, db, uid, pwd, "ir.ui.menu", "search",
        [[("name", "in", ["Rapports", "Reports", "Reporting"]),
          "|",
          ("parent_id.name", "ilike", "Comptabilit"),
          ("parent_id.name", "ilike", "Accounting")]],
        {"limit": 1},
    )
    if ids:
        return int(ids[0])
    ids = _ek(
        models, db, uid, pwd, "ir.ui.menu", "search",
        [[("name", "in", ["Rapports", "Reports", "Reporting"])]],
        {"limit": 1},
    )
    return int(ids[0]) if ids else None


def _make_form_view_arch(sa_id: int) -> str:
    return f"""<form>
  <sheet>
    <div class="oe_title">
      <h1>Tableau de Bord Manager &#8212; Senedoo</h1>
    </div>
    <group string="Parametres" col="2">
      <group>
        <field name="x_company_id"
               options="{{'no_create': True}}"
               placeholder="Toutes les societes"/>
        <field name="x_analytic_id"
               options="{{'no_create': True}}"
               placeholder="Optionnel"/>
      </group>
      <group>
        <field name="x_period_type"/>
        <field name="x_ref_year"/>
        <field name="x_ref_month"
               invisible="x_period_type != 'month'"/>
        <field name="x_date_from_custom"
               invisible="x_period_type != 'custom'"
               string="Du"/>
        <field name="x_date_to_custom"
               invisible="x_period_type != 'custom'"
               string="Au"/>
      </group>
    </group>
    <div style="margin:12px 0">
      <button string="Calculer le tableau de bord"
              type="action"
              name="{sa_id}"
              class="btn-primary oe_highlight"/>
    </div>
    <field name="x_result_html" widget="html" readonly="1" nolabel="1"/>
  </sheet>
</form>"""


# ---------------------------------------------------------------------------
# Installation du wizard dans Odoo
# ---------------------------------------------------------------------------

def create_manager_dashboard(
    models: Any,
    db: str,
    uid: int,
    pwd: str,
) -> dict[str, Any]:
    """
    Cree le wizard Tableau de Bord Manager dans Odoo via XML-RPC.
    Idempotent : purge l'instance existante avant de recreer.
    Retourne un dict avec les IDs crees et un message de diagnostic.
    """
    purge_manager_dashboard(models, db, uid, pwd)

    result: dict[str, Any] = {}

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
            "name":              "x_company_id",
            "field_description": "Societe",
            "ttype":             "many2one",
            "model_id":          model_id,
            "state":             "manual",
            "relation":          "res.company",
            "on_delete":         "restrict",
        },
        {
            "name":              "x_analytic_id",
            "field_description": "Axe analytique",
            "ttype":             "many2one",
            "model_id":          model_id,
            "state":             "manual",
            "relation":          "account.analytic.account",
            "on_delete":         "restrict",
        },
        {
            "name":              "x_period_type",
            "field_description": "Type de periode",
            "ttype":             "selection",
            "model_id":          model_id,
            "state":             "manual",
            "selection":         (
                "[('month','Mois'),('year','Annee'),"
                "('q1','T1'),('q2','T2'),('q3','T3'),('q4','T4'),"
                "('ytd','Cumul YTD'),('custom','Personnalise')]"
            ),
        },
        {
            "name":              "x_ref_year",
            "field_description": "Annee de reference",
            "ttype":             "integer",
            "model_id":          model_id,
            "state":             "manual",
        },
        {
            "name":              "x_ref_month",
            "field_description": "Mois (1-12)",
            "ttype":             "integer",
            "model_id":          model_id,
            "state":             "manual",
        },
        {
            "name":              "x_date_from_custom",
            "field_description": "Periode du",
            "ttype":             "date",
            "model_id":          model_id,
            "state":             "manual",
        },
        {
            "name":              "x_date_to_custom",
            "field_description": "Periode au",
            "ttype":             "date",
            "model_id":          model_id,
            "state":             "manual",
        },
        {
            "name":              "x_result_html",
            "field_description": "Tableau de bord",
            "ttype":             "html",
            "model_id":          model_id,
            "state":             "manual",
        },
    ]
    _ek(models, db, uid, pwd, "ir.model.fields", "create", [field_defs])

    # ---- 3. Server action (Python code embarque) ----------------------------
    sa_id = _ek(models, db, uid, pwd, "ir.actions.server", "create", [{
        "name":               f"Calculer {WIZARD_NAME}",
        "model_id":           model_id,
        "state":              "code",
        "code":               _SERVER_ACTION_CODE,
        "binding_model_id":   model_id,
    }])
    result["server_action_id"] = sa_id

    # ---- 4. Vue formulaire (bouton reference le sa_id reel) -----------------
    view_id = _ek(models, db, uid, pwd, "ir.ui.view", "create", [{
        "name":  f"{WIZARD_MODEL}.form",
        "model": WIZARD_MODEL,
        "type":  "form",
        "arch":  _make_form_view_arch(sa_id),
    }])
    result["view_id"] = view_id

    # ---- 5. Action window ---------------------------------------------------
    aw_id = _ek(models, db, uid, pwd, "ir.actions.act_window", "create", [{
        "name":      WIZARD_NAME,
        "res_model": WIZARD_MODEL,
        "view_mode": "form",
        "target":    "current",
    }])
    result["act_window_id"] = aw_id

    # ---- 6. Menu sous Comptabilite > Rapports --------------------------------
    parent_menu_id = _find_reports_menu(models, db, uid, pwd)
    menu_id = _ek(models, db, uid, pwd, "ir.ui.menu", "create", [{
        "name":      WIZARD_MENU_LABEL,
        "parent_id": parent_menu_id,
        "action":    f"ir.actions.act_window,{aw_id}",
        "sequence":  100,
    }])
    result["menu_id"] = menu_id

    result["ok"] = True
    result["message"] = (
        f"Tableau de Bord Manager installe : modele {WIZARD_MODEL!r}, "
        f"server action id={sa_id}, menu id={menu_id}. "
        f"Accessible dans Odoo : Comptabilite > Rapports > {WIZARD_MENU_LABEL!r}."
    )
    return result


# ---------------------------------------------------------------------------
# Suppression du wizard
# ---------------------------------------------------------------------------

def purge_manager_dashboard(models: Any, db: str, uid: int, pwd: str) -> dict[str, Any]:
    """Supprime le wizard Tableau de Bord Manager s'il existe. Idempotent."""
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

    # Server actions + views + model (via cascade)
    model_ids = _ek(models, db, uid, pwd, "ir.model", "search",
                    [[("model", "=", WIZARD_MODEL)]])
    if model_ids:
        sa_ids = _ek(models, db, uid, pwd, "ir.actions.server", "search",
                     [[("model_id", "in", model_ids)]])
        if sa_ids:
            _ek(models, db, uid, pwd, "ir.actions.server", "unlink", [sa_ids])
            purged.append(f"server_actions({sa_ids})")

        view_ids = _ek(models, db, uid, pwd, "ir.ui.view", "search",
                       [[("model", "=", WIZARD_MODEL)]])
        if view_ids:
            _ek(models, db, uid, pwd, "ir.ui.view", "unlink", [view_ids])
            purged.append(f"views({view_ids})")

        _ek(models, db, uid, pwd, "ir.model", "unlink", [model_ids])
        purged.append(f"model({model_ids})")

    return {
        "purged":  purged,
        "ok":      True,
        "message": f"Tableau de Bord Manager supprime : {', '.join(purged) or 'rien trouve'}.",
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def manager_dashboard_exists(models: Any, db: str, uid: int, pwd: str) -> bool:
    """True si le wizard est deja installe (ir.model x_manager_dashboard_wizard)."""
    return _model_exists(models, db, uid, pwd)
