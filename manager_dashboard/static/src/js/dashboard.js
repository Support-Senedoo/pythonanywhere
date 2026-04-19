/* global odoo */
// Tableau de Bord Manager — Senedoo  (Odoo 17 / 18 / 19)
//
// Chargé via ir.asset (sequence 1000+) dans web.assets_backend.
// Pas de directive @odoo-module : fichier servi depuis /web/content/{id}/...
// Odoo ne peut pas résoudre de module name depuis ce chemin dynamique.
//
// Enregistrement SYNCHRONE : odoo.loader.require() est disponible immédiatement
// car ce fichier s'exécute APRÈS tous les modules OWL dans le bundle compilé.
// → pas de race condition avec loadRouterState.
(function () {
    'use strict';

    // ── Dépendances OWL (synchrone — disponible en contexte bundle) ───────────
    var owl, registryMod, hooksMod;
    try {
        owl         = odoo.loader.require('@odoo/owl');
        registryMod = odoo.loader.require('@web/core/registry');
        hooksMod    = odoo.loader.require('@web/core/utils/hooks');
    } catch (e) {
        console.error('[TDM] Dépendances OWL introuvables :', e);
        return;
    }

    var Component   = owl.Component;
    var useState    = owl.useState;
    var onWillStart = owl.onWillStart;
    var xml         = owl.xml;
    var registry    = registryMod.registry;
    var useService  = hooksMod.useService;

    // ── Constantes ────────────────────────────────────────────────────────────
    var MONTHS  = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"];
    var INCOME  = ["income","income_other"];
    var COGS    = ["expense_direct_cost"];
    var CHARGES = ["expense"];
    var AMORT   = ["expense_depreciation"];
    var CASH    = ["asset_cash","liability_credit_card"];
    var REC     = ["asset_receivable"];
    var PAY     = ["liability_payable"];
    var STOCK   = ["asset_current"];
    var TABS = [
        { id:"synthese",   label:"Synthèse",           icon:"fa-th-large",      color:"#F4720B" },
        { id:"pl",         label:"P & L",              icon:"fa-bar-chart",     color:"#2E7D32" },
        { id:"tresorerie", label:"Trésorerie",          icon:"fa-university",    color:"#006064" },
        { id:"ventes",     label:"Ventes",              icon:"fa-shopping-cart", color:"#1565C0" },
        { id:"achats",     label:"Achats",              icon:"fa-truck",         color:"#C62828" },
        { id:"operations", label:"Stock & Fabrication", icon:"fa-cogs",          color:"#4527A0" },
    ];

    // ── Helpers ───────────────────────────────────────────────────────────────
    function fmt(v) {
        if (v === null || v === undefined) return "\u2014";
        var a = Math.abs(v);
        if (a >= 1e6) return (v/1e6).toFixed(2) + "\u00a0M\u20ac";
        if (a >= 1e3) return (v/1e3).toFixed(1)  + "\u00a0K\u20ac";
        return Math.round(v).toLocaleString("fr-FR") + "\u00a0\u20ac";
    }
    function pctStr(n, n1, invert) {
        if (!n1) return null;
        var p  = (n - n1) / Math.abs(n1) * 100;
        var up = invert ? p < 0 : p > 0;
        return {
            str:  (p >= 0 ? "+" : "") + p.toFixed(1) + "%",
            cls:  up ? "up" : "down",
            icon: up ? "fa-arrow-up" : "fa-arrow-down",
        };
    }
    function mkKpi(n, n1, invert) {
        return { n: n, n1: (n1 !== undefined ? n1 : null), delta: pctStr(n, n1, invert) };
    }
    function maxArr(a, b) {
        var all = (a || []).concat(b || []).filter(function(v){ return v > 0; });
        return all.length ? Math.max.apply(null, all) : 1;
    }
    // Lit le solde renvoyé par readGroup (Odoo 18+: balance ou balance:sum)
    function readBal(g) {
        var v = g["balance:sum"];
        if (typeof v !== "number") v = g["balance"];
        return typeof v === "number" ? v : 0;
    }

    // ── Template OWL ─────────────────────────────────────────────────────────
    var TEMPLATE = xml/* xml */`
<div class="tdm-root">

    <!-- En-tête -->
    <div class="tdm-header">
        <div class="tdm-brand">
            <div class="tdm-logo">S</div>
            <div>
                <h1>Tableau de Bord Manager</h1>
                <small t-esc="companyName"/>
            </div>
        </div>
        <div class="tdm-year-ctrl">
            <button t-on-click="prevYear">&#9664;</button>
            <span class="tdm-year-num" t-esc="state.year"/>
            <button t-on-click="nextYear">&#9654;</button>
            <span class="tdm-vs-label">vs <t t-esc="state.year - 1"/></span>
        </div>
    </div>

    <!-- Onglets -->
    <div class="tdm-tabs">
        <t t-foreach="tabs" t-as="tab">
            <button class="tdm-tab"
                    t-att-class="{ active: state.tab === tab.id }"
                    t-attf-style="--tab-color: #{tab.color}"
                    t-on-click="() => this.switchTab(tab.id)">
                <i t-attf-class="fa #{tab.icon}"/> <t t-esc="tab.label"/>
            </button>
        </t>
    </div>

    <!-- Contenu -->
    <div class="tdm-content">

        <t t-if="state.loading">
            <div class="tdm-loading">
                <i class="fa fa-spinner fa-spin fa-2x"/>
                <span>Chargement des données...</span>
            </div>
        </t>

        <t t-elif="state.error">
            <div class="tdm-error">
                <i class="fa fa-exclamation-triangle fa-3x"/>
                <p t-esc="state.error"/>
            </div>
        </t>

        <t t-elif="state.data">

            <!-- SYNTHÈSE -->
            <t t-if="state.tab === 'synthese'">
                <div class="tdm-section-title"><i class="fa fa-th-large"/> Indicateurs clés — <t t-esc="state.year"/></div>
                <div class="tdm-kpi-row">
                    <t t-foreach="currentKpis" t-as="k"><t t-call="manager_dashboard.KpiCard"/></t>
                </div>
                <div class="tdm-charts-row">
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-line-chart"/> Ventes mensuelles</h3>
                        <div class="tdm-chart-legend">
                            <span><span class="dot" style="background:#F4720B"/> <t t-esc="state.year"/></span>
                            <span><span class="dot" style="background:#FFC9A0"/> <t t-esc="state.year-1"/></span>
                        </div>
                        <div class="tdm-barchart">
                            <t t-foreach="barsRevN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#F4720B" t-att-data-val="b.tN"/>
                                        <div t-if="b.hN1 !== null" class="tdm-bar" t-attf-style="height:#{b.hN1}px;background:#FFC9A0" t-att-data-val="b.tN1"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-truck"/> Achats mensuels</h3>
                        <div class="tdm-barchart">
                            <t t-foreach="barsAchN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#C62828" t-att-data-val="b.tN"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                </div>
            </t>

            <!-- P&L -->
            <t t-elif="state.tab === 'pl'">
                <div class="tdm-section-title"><i class="fa fa-bar-chart"/> Compte de résultat — <t t-esc="state.year"/></div>
                <div class="tdm-info-row" style="margin-bottom:20px">
                    <div class="tdm-info-block" style="border-top:4px solid #2E7D32;max-width:260px">
                        <span class="ib-label">Taux de marge brute</span>
                        <span class="ib-value" t-esc="margePct"/>
                        <span class="ib-sub" t-if="margeDelta" t-esc="margeDelta"/>
                    </div>
                </div>
                <div class="tdm-waterfall">
                    <t t-foreach="wfRows" t-as="row">
                        <div class="tdm-wf-row"
                             t-att-class="{ subtotal: row.sub, total: row.tot }"
                             t-attf-style="--wf-color: #{row.color}">
                            <span class="tdm-wf-icon"><i t-attf-class="fa #{row.icon}"/></span>
                            <span class="tdm-wf-label" t-esc="row.label"/>
                            <span class="tdm-wf-value" t-esc="row.nFmt"/>
                            <span class="tdm-wf-n1"><t t-if="row.n1Fmt">N-1: <t t-esc="row.n1Fmt"/></t></span>
                            <span class="tdm-wf-delta">
                                <t t-if="row.delta">
                                    <span t-attf-class="tdm-kpi-delta #{row.delta.cls}">
                                        <i t-attf-class="fa #{row.delta.icon}"/> <t t-esc="row.delta.str"/>
                                    </span>
                                </t>
                            </span>
                        </div>
                    </t>
                </div>
                <div class="tdm-charts-row">
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-money"/> Revenus mensuels</h3>
                        <div class="tdm-chart-legend">
                            <span><span class="dot" style="background:#2E7D32"/> <t t-esc="state.year"/></span>
                            <span><span class="dot" style="background:#A5D6A7"/> <t t-esc="state.year-1"/></span>
                        </div>
                        <div class="tdm-barchart">
                            <t t-foreach="barsRevN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#2E7D32" t-att-data-val="b.tN"/>
                                        <div t-if="b.hN1 !== null" class="tdm-bar" t-attf-style="height:#{b.hN1}px;background:#A5D6A7" t-att-data-val="b.tN1"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-list"/> Charges mensuelles</h3>
                        <div class="tdm-barchart">
                            <t t-foreach="barsChgN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#E53935" t-att-data-val="b.tN"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                </div>
            </t>

            <!-- TRÉSORERIE -->
            <t t-elif="state.tab === 'tresorerie'">
                <div class="tdm-section-title"><i class="fa fa-university"/> Position de Trésorerie — <t t-esc="state.year"/></div>
                <div class="tdm-kpi-row">
                    <t t-foreach="currentKpis" t-as="k"><t t-call="manager_dashboard.KpiCard"/></t>
                </div>
                <div class="tdm-charts-row">
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-line-chart"/> Flux revenus mensuels</h3>
                        <div class="tdm-chart-legend">
                            <span><span class="dot" style="background:#006064"/> <t t-esc="state.year"/></span>
                            <span><span class="dot" style="background:#80CBC4"/> <t t-esc="state.year-1"/></span>
                        </div>
                        <div class="tdm-barchart">
                            <t t-foreach="barsRevN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#006064" t-att-data-val="b.tN"/>
                                        <div t-if="b.hN1 !== null" class="tdm-bar" t-attf-style="height:#{b.hN1}px;background:#80CBC4" t-att-data-val="b.tN1"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-truck"/> Flux achats mensuels</h3>
                        <div class="tdm-barchart">
                            <t t-foreach="barsAchN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#C62828" t-att-data-val="b.tN"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                </div>
            </t>

            <!-- VENTES -->
            <t t-elif="state.tab === 'ventes'">
                <div class="tdm-section-title"><i class="fa fa-shopping-cart"/> Performance Ventes — <t t-esc="state.year"/></div>
                <div class="tdm-kpi-row">
                    <t t-foreach="currentKpis" t-as="k"><t t-call="manager_dashboard.KpiCard"/></t>
                </div>
                <div class="tdm-charts-row">
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-line-chart"/> Évolution mensuelle</h3>
                        <div class="tdm-chart-legend">
                            <span><span class="dot" style="background:#1565C0"/> <t t-esc="state.year"/></span>
                            <span><span class="dot" style="background:#90CAF9"/> <t t-esc="state.year-1"/></span>
                        </div>
                        <div class="tdm-barchart">
                            <t t-foreach="barsRevN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#1565C0" t-att-data-val="b.tN"/>
                                        <div t-if="b.hN1 !== null" class="tdm-bar" t-attf-style="height:#{b.hN1}px;background:#90CAF9" t-att-data-val="b.tN1"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                </div>
            </t>

            <!-- ACHATS -->
            <t t-elif="state.tab === 'achats'">
                <div class="tdm-section-title"><i class="fa fa-truck"/> Analyse Achats — <t t-esc="state.year"/></div>
                <div class="tdm-kpi-row">
                    <t t-foreach="currentKpis" t-as="k"><t t-call="manager_dashboard.KpiCard"/></t>
                </div>
                <div class="tdm-charts-row">
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-bar-chart"/> Achats mensuels</h3>
                        <div class="tdm-barchart">
                            <t t-foreach="barsAchN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#C62828" t-att-data-val="b.tN"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                    <div class="tdm-chart-card">
                        <h3><i class="fa fa-list"/> Charges mensuelles</h3>
                        <div class="tdm-barchart">
                            <t t-foreach="barsChgN" t-as="b">
                                <div class="tdm-bar-col">
                                    <div class="tdm-bar-pair">
                                        <div class="tdm-bar" t-attf-style="height:#{b.hN}px;background:#E53935" t-att-data-val="b.tN"/>
                                    </div>
                                    <span class="tdm-bar-lbl" t-esc="b.lbl"/>
                                </div>
                            </t>
                        </div>
                    </div>
                </div>
            </t>

            <!-- STOCK & FABRICATION -->
            <t t-elif="state.tab === 'operations'">
                <div class="tdm-section-title"><i class="fa fa-cogs"/> Stock &amp; Fabrication — <t t-esc="state.year"/></div>
                <div class="tdm-kpi-row">
                    <t t-foreach="currentKpis" t-as="k"><t t-call="manager_dashboard.KpiCard"/></t>
                </div>
            </t>

        </t>
    </div>
</div>

<!-- Sous-template carte KPI -->
<t t-name="manager_dashboard.KpiCard">
    <div class="tdm-kpi-card" t-attf-style="--kpi-color: #{k.color}">
        <div class="tdm-kpi-icon"><i t-attf-class="fa #{k.icon}"/></div>
        <div class="tdm-kpi-label" t-esc="k.label"/>
        <div class="tdm-kpi-value" t-esc="k.nFmt"/>
        <t t-if="k.delta">
            <span t-attf-class="tdm-kpi-delta #{k.delta.cls}">
                <i t-attf-class="fa #{k.delta.icon}"/> <t t-esc="k.delta.str"/>
            </span>
        </t>
        <div class="tdm-kpi-n1" t-if="k.n1Fmt">N-1: <t t-esc="k.n1Fmt"/></div>
    </div>
</t>`;

    // ── Composant OWL (ES6 class — seule syntaxe valide pour hériter de Component) ──
    class ManagerDashboard extends Component {

        setup() {
            this.orm     = useService("orm");
            this.company = useService("company");
            this.tabs    = TABS;
            this.state   = useState({
                tab:     "synthese",
                year:    new Date().getFullYear(),
                data:    null,
                loading: true,
                error:   null,
            });
            onWillStart(() => this._load());
        }

        get companyId()   { return this.company.currentCompany.id; }
        get companyName() { return this.company.currentCompany.name; }

        switchTab(id) { this.state.tab = id; }
        async prevYear() { this.state.year--; await this._load(); }
        async nextYear() { this.state.year++; await this._load(); }

        // ── Requêtes ORM ──────────────────────────────────────────────────────
        async _bal(types, year, cumul) {
            const domain = [
                ["move_id.state",           "=",  "posted"],
                ["company_id",              "=",  this.companyId],
                ["account_id.account_type", "in", types],
            ];
            if (year && !cumul) {
                domain.push(["date", ">=", year + "-01-01"],
                            ["date", "<=", year + "-12-31"]);
            } else if (year && cumul) {
                domain.push(["date", "<=", year + "-12-31"]);
            }
            const res = await this.orm.readGroup(
                "account.move.line", domain, ["balance:sum"], []
            );
            if (!res || !res.length) return 0;
            return readBal(res[0]);
        }

        async _monthly(types, year, sign) {
            const out    = new Array(12).fill(0);
            const groups = await this.orm.readGroup(
                "account.move.line",
                [
                    ["move_id.state",           "=",  "posted"],
                    ["company_id",              "=",  this.companyId],
                    ["account_id.account_type", "in", types],
                    ["date", ">=", year + "-01-01"],
                    ["date", "<=", year + "-12-31"],
                ],
                ["balance:sum"],
                ["date:month"],
                { orderby: "date:month asc" },
            );
            for (const g of groups) {
                const from = (g.__range && g.__range["date:month"] && g.__range["date:month"].from) || "";
                if (from.length >= 7) {
                    const m = parseInt(from.substring(5, 7), 10) - 1;
                    if (m >= 0 && m < 12) out[m] = sign * readBal(g);
                }
            }
            return out;
        }

        // ── Chargement ────────────────────────────────────────────────────────
        async _load() {
            this.state.loading = true;
            this.state.error   = null;
            try {
                const y = this.state.year;
                const r = await Promise.all([
                    this._bal(INCOME,  y),    this._bal(INCOME,  y-1),
                    this._bal(COGS,    y),    this._bal(COGS,    y-1),
                    this._bal(CHARGES, y),    this._bal(CHARGES, y-1),
                    this._bal(AMORT,   y),    this._bal(AMORT,   y-1),
                    this._bal(CASH,    y, true),  this._bal(CASH,  y-1, true),
                    this._bal(REC,     y, true),  this._bal(REC,   y-1, true),
                    this._bal(PAY,     y, true),  this._bal(PAY,   y-1, true),
                    this._bal(STOCK,   y, true),  this._bal(STOCK, y-1, true),
                    this._monthly(INCOME,  y,   -1),
                    this._monthly(INCOME,  y-1, -1),
                    this._monthly(COGS,    y,    1),
                    this._monthly(CHARGES, y,    1),
                ]);

                const CA_n  = -r[0],  CA_n1  = -r[1];
                const RB_n  = CA_n  - r[2],  RB_n1  = CA_n1  - r[3];
                const REX_n = RB_n  - r[4],  REX_n1 = RB_n1  - r[5];
                const RN_n  = REX_n - r[6],  RN_n1  = REX_n1 - r[7];

                this.state.data = {
                    kpi: {
                        ca:    mkKpi(CA_n,  CA_n1),
                        cogs:  mkKpi(r[2],  r[3],  true),
                        rb:    mkKpi(RB_n,  RB_n1),
                        chg:   mkKpi(r[4],  r[5],  true),
                        rex:   mkKpi(REX_n, REX_n1),
                        am:    mkKpi(r[6],  r[7],  true),
                        rn:    mkKpi(RN_n,  RN_n1),
                        treso: mkKpi(r[8],  r[9]),
                        rec:   mkKpi(r[10], r[11]),
                        pay:   mkKpi(-r[12],-r[13], true),
                        stock: mkKpi(r[14], r[15]),
                        marge: { n: CA_n  ? RB_n  / CA_n  * 100 : 0,
                                 n1: CA_n1 ? RB_n1 / CA_n1 * 100 : 0 },
                    },
                    charts: { rev_n: r[16], rev_n1: r[17], ach_n: r[18], chg_mon: r[19] },
                };
            } catch(e) {
                this.state.error = (e && e.data && e.data.message) || (e && e.message) || "Erreur";
                console.error("[TDM]", e);
            }
            this.state.loading = false;
        }

        // ── KPIs par onglet ───────────────────────────────────────────────────
        _mkCard(label, key, color, icon) {
            const k = (this.state.data && this.state.data.kpi && this.state.data.kpi[key]) || { n:0, n1:null, delta:null };
            return { label, color, icon,
                     nFmt:  fmt(k.n),
                     n1Fmt: k.n1 !== null ? fmt(k.n1) : null,
                     delta: k.delta };
        }

        get currentKpis() {
            const t = this.state.tab;
            if (t === "synthese") return [
                this._mkCard("Chiffre d'Affaires",   "ca",    "#F4720B", "fa-money"),
                this._mkCard("Résultat Brut",         "rb",    "#2E7D32", "fa-bar-chart"),
                this._mkCard("Résultat Exploitation", "rex",   "#388E3C", "fa-line-chart"),
                this._mkCard("Trésorerie",            "treso", "#006064", "fa-bank"),
                this._mkCard("Créances clients",      "rec",   "#1565C0", "fa-file-text"),
                this._mkCard("Dettes fournisseurs",   "pay",   "#C62828", "fa-truck"),
            ];
            if (t === "pl") return [
                this._mkCard("Chiffre d'Affaires",    "ca",   "#F4720B", "fa-money"),
                this._mkCard("Coût des ventes",        "cogs", "#C62828", "fa-minus"),
                this._mkCard("Résultat Brut",          "rb",   "#2E7D32", "fa-bar-chart"),
                this._mkCard("Charges d'exploitation", "chg",  "#E53935", "fa-list"),
                this._mkCard("Résultat Net",           "rn",   "#1B5E20", "fa-check"),
            ];
            if (t === "tresorerie") return [
                this._mkCard("Solde Trésorerie",    "treso", "#006064", "fa-bank"),
                this._mkCard("Créances clients",    "rec",   "#1565C0", "fa-file-text"),
                this._mkCard("Dettes fournisseurs", "pay",   "#C62828", "fa-truck"),
            ];
            if (t === "ventes") return [
                this._mkCard("Chiffre d'Affaires", "ca",  "#1565C0", "fa-money"),
                this._mkCard("Résultat Brut",      "rb",  "#2E7D32", "fa-bar-chart"),
                this._mkCard("Créances clients",   "rec", "#01579B", "fa-file-text"),
            ];
            if (t === "achats") return [
                this._mkCard("Coût des ventes",      "cogs", "#C62828", "fa-truck"),
                this._mkCard("Charges exploitation", "chg",  "#D32F2F", "fa-list"),
                this._mkCard("Dettes fournisseurs",  "pay",  "#B71C1C", "fa-credit-card"),
            ];
            if (t === "operations") return [
                this._mkCard("Valeur Stock", "stock", "#4527A0", "fa-cubes"),
            ];
            return [];
        }

        // ── Waterfall ─────────────────────────────────────────────────────────
        get wfRows() {
            if (!this.state.data) return [];
            const d = this.state.data.kpi;
            return [
                { label:"Chiffre d'Affaires",       key:"ca",   icon:"fa-money",  color:"#F4720B", sub:false, tot:false },
                { label:"— Coût des ventes",         key:"cogs", icon:"fa-minus",  color:"#E53935", sub:false, tot:false },
                { label:"= Résultat Brut",           key:"rb",   icon:"fa-equals", color:"#2E7D32", sub:true,  tot:false },
                { label:"— Charges d'exploitation",  key:"chg",  icon:"fa-minus",  color:"#E53935", sub:false, tot:false },
                { label:"= Résultat Exploitation",   key:"rex",  icon:"fa-equals", color:"#388E3C", sub:true,  tot:false },
                { label:"— Amortissements",          key:"am",   icon:"fa-minus",  color:"#F57C00", sub:false, tot:false },
                { label:"= Résultat Net",            key:"rn",   icon:"fa-check",  color:"#1B5E20", sub:false, tot:true  },
            ].map(row => {
                const k = d[row.key] || { n:0, n1:null, delta:null };
                return Object.assign({}, row, {
                    nFmt:  fmt(k.n),
                    n1Fmt: k.n1 !== null ? fmt(k.n1) : null,
                    delta: k.delta,
                });
            });
        }

        get margePct() {
            const m = this.state.data && this.state.data.kpi && this.state.data.kpi.marge;
            return m ? m.n.toFixed(1) + " %" : "\u2014";
        }
        get margeDelta() {
            const m = this.state.data && this.state.data.kpi && this.state.data.kpi.marge;
            if (!m || m.n1 === null) return null;
            const d = (m.n - m.n1).toFixed(1);
            return (d >= 0 ? "+" : "") + d + " pts vs N-1";
        }

        // ── Graphiques ────────────────────────────────────────────────────────
        _bars(dataN, dataN1) {
            if (!dataN) return [];
            const mx = maxArr(dataN, dataN1 || []);
            return dataN.map((v, i) => ({
                lbl: MONTHS[i],
                hN:  Math.max(Math.round(v / mx * 130), v > 0 ? 2 : 0),
                hN1: dataN1 ? Math.max(Math.round(dataN1[i] / mx * 130), dataN1[i] > 0 ? 2 : 0) : null,
                tN:  fmt(v),
                tN1: dataN1 ? fmt(dataN1[i]) : null,
            }));
        }
        get barsRevN() {
            const c = this.state.data && this.state.data.charts;
            return this._bars(c && c.rev_n, c && c.rev_n1);
        }
        get barsAchN() {
            const c = this.state.data && this.state.data.charts;
            return this._bars(c && c.ach_n);
        }
        get barsChgN() {
            const c = this.state.data && this.state.data.charts;
            return this._bars(c && c.chg_mon);
        }
    }

    ManagerDashboard.template = TEMPLATE;
    ManagerDashboard.props    = {};

    // ── Enregistrement synchrone dans le registry Odoo ────────────────────────
    registry.category("actions").add("manager_dashboard.Dashboard", ManagerDashboard);
    console.log("[TDM] manager_dashboard.Dashboard enregistré (synchrone).");

})();
