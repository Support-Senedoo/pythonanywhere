# -*- coding: utf-8 -*-
{
    "name": "Budget Studio — Comptes produits & charges",
    "summary": "Rapport PDF listant les comptes de type produits et charges (inspiré du compte de résultat)",
    "version": "18.0.1.0.0",
    "category": "Accounting/Accounting",
    "author": "Budget Studio",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "reports/pl_accounts_report_templates.xml",
        "reports/pl_accounts_report_views.xml",
    ],
    "installable": True,
    "application": False,
}
