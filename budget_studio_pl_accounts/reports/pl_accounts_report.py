# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.osv import expression


# Types de comptes « compte de résultat » (produits / charges) — Odoo 18 account.account.account_type
_ACCOUNT_TYPES_INCOME = ("income", "income_other")
_ACCOUNT_TYPES_EXPENSE = ("expense", "expense_depreciation", "expense_direct_cost")


class PlAccountsReportWizard(models.TransientModel):
    _name = "pl.accounts.report.wizard"
    _description = "Assistant rapport comptes produits et charges"

    company_id = fields.Many2one(
        "res.company",
        string="Société",
        required=True,
        default=lambda self: self.env.company,
    )

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            "budget_studio_pl_accounts.action_report_pl_accounts"
        ).report_action(self)


class ReportPlAccountsDocument(models.AbstractModel):
    _name = "report.budget_studio_pl_accounts.report_pl_accounts_document"
    _description = "Rapport PDF — liste comptes produits et charges"

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env["pl.accounts.report.wizard"].browse(docids)
        wizard.ensure_one()
        company = wizard.company_id

        Account = self.env["account.account"].with_company(company)
        domain = self._pl_accounts_domain(company)
        accounts = Account.search(domain, order="code, name")

        income = accounts.filtered(lambda a: a.account_type in _ACCOUNT_TYPES_INCOME)
        expense = accounts.filtered(lambda a: a.account_type in _ACCOUNT_TYPES_EXPENSE)

        acc_type = self.env["account.account"]._fields["account_type"]
        sel = acc_type.selection
        if callable(sel):
            sel = sel(self.env["account.account"])
        type_labels = dict(sel)

        def row(acc):
            return {
                "code": acc.code or "",
                "name": acc.name or "",
                "type_key": acc.account_type or "",
                "type_label": type_labels.get(acc.account_type, acc.account_type or ""),
            }

        return {
            "doc_ids": docids,
            "company": company,
            "wizard": wizard,
            "accounts_income": income,
            "accounts_expense": expense,
            "accounts_all": accounts,
            "rows_income": [row(a) for a in income],
            "rows_expense": [row(a) for a in expense],
        }

    def _pl_accounts_domain(self, company):
        """Comptes utilisés dans le compte de résultat (produits + charges)."""
        types = _ACCOUNT_TYPES_INCOME + _ACCOUNT_TYPES_EXPENSE
        pl_domain = [("account_type", "in", list(types))]
        Account = self.env["account.account"]
        if hasattr(Account, "_check_company_domain"):
            company_domain = Account._check_company_domain(company)
            return expression.AND([company_domain, pl_domain])
        return expression.AND(
            [
                ["|", ("company_ids", "=", False), ("company_ids", "in", [company.id])],
                pl_domain,
            ]
        )
