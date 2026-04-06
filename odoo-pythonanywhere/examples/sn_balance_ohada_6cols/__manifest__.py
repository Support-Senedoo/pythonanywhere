# -*- coding: utf-8 -*-
{
    "name": "Balance OHADA 6 colonnes (Senedoo)",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "summary": "Rapport comptable configurable : balance 6 colonnes (moteur aggregation, préfixe ohada6_).",
    "description": """
Rapport type balance générale OHADA : débit/crédit initiaux, mouvements, débit/crédit finaux.
Nécessite le moteur de rapports financiers (account.report), en pratique Odoo Enterprise
ou équivalent avec le module account_reports.

Code de ligne feuille : bal_ohada_import (distinct de la toolbox web bal_ohada).
    """,
    "author": "Senedoo",
    "license": "LGPL-3",
    "depends": ["account_reports"],
    "data": ["data/balance_ohada_6cols.xml"],
    "installable": True,
    "application": False,
}
