# -*- coding: utf-8 -*-
{
    "name": "Budgets financiers — analytique (Senedoo)",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "summary": "Budgets account.report.budget, axe analytique, lignes éditables (items).",
    "description": """
Gestion des budgets financiers du reporting (``account.report.budget``) avec rattachement
optionnel à un **compte analytique** (projet), exposé dans le wizard toolbox « Budget par projet ».

Inclut un menu pour éditer les **lignes** (``account.report.budget.item``) en liste rapide
(``editable=bottom``). Adapter les vues si votre version Odoo diffère (noms de champs montant).

**Dépendance** : ``account_reports`` (Enterprise). Si l’installation échoue sur un ``inherit_id``,
vérifiez les IDs externes des vues ``account_reports`` sur votre version et ajustez les XML.
    """,
    "author": "Senedoo",
    "license": "LGPL-3",
    "depends": ["analytic", "account_reports"],
    "data": [
        "views/account_report_budget_views.xml",
        "views/account_report_budget_item_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
}
