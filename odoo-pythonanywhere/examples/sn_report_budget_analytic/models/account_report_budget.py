# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountReportBudget(models.Model):
    _inherit = "account.report.budget"

    x_analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Compte analytique (projet)",
        index=True,
        help="Utilisé pour filtrer le budget dans le wizard « Budget par projet » (toolbox Senedoo).",
    )


class AccountReportBudgetItem(models.Model):
    _inherit = "account.report.budget.item"

    x_analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Compte analytique",
        index=True,
        help="Optionnel : précise l’axe sur la ligne ; sinon le budget ou les champs Odoo standard s’appliquent.",
    )
