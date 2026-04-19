#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère le module Odoo ``sn_report_budget_analytic`` (dossier installable).

Objectif :
  - champs ``x_analytic_account_id`` sur ``account.report.budget`` et
    ``account.report.budget.item`` (alignés avec le wizard « Budget par projet » Senedoo) ;
  - menus Comptabilité > Reporting : budgets financiers + lignes éditables en liste.

Prérequis cible : Odoo Enterprise (ou équivalent) avec le module ``account_reports``
(modèles ``account.report.budget`` / ``account.report.budget.item``).

Usage :
  python3 scripts/generate_sn_report_budget_analytic_module.py --out examples/sn_report_budget_analytic

Conflit éventuel : si la toolbox a déjà créé des champs **manuels** du même nom sur ces
modèles, supprimez-les (ou désinstallez-les) avant d’installer ce module, sinon Odoo peut
refuser la mise à jour (doublon de champ).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MANIFEST = '''# -*- coding: utf-8 -*-
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
'''

INIT_ROOT = """# -*- coding: utf-8 -*-
from . import models
"""

INIT_MODELS = """# -*- coding: utf-8 -*-
from . import account_report_budget
"""

MODEL_PY = '''# -*- coding: utf-8 -*-
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
'''

# Vues : inherit_id standards Odoo 18/19 account_reports (à ajuster si besoin).
BUDGET_VIEWS_XML = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <!-- Formulaire budget : groupe analytique Senedoo -->
  <record id="view_account_report_budget_form_analytic_senedoo" model="ir.ui.view">
    <field name="name">account.report.budget.form.analytic.senedoo</field>
    <field name="model">account.report.budget</field>
    <field name="inherit_id" ref="account_reports.view_account_report_budget_form"/>
    <field name="arch" type="xml">
      <xpath expr="//sheet" position="inside">
        <group string="Analytique (Senedoo)" name="sn_analytic_budget">
          <field name="x_analytic_account_id"
                 options="{'no_create': True, 'no_create_edit': True}"
                 placeholder="Projet / axe pour le wizard Budget par projet"/>
        </group>
      </xpath>
    </field>
  </record>
</odoo>
'''

# Lignes : hériter de l’arbre standard account_reports (colonnes Odoo) + édition liste + champ analytique.
ITEM_VIEWS_XML = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="view_account_report_budget_item_tree_senedoo_inherit" model="ir.ui.view">
    <field name="name">account.report.budget.item.tree.senedoo.inherit</field>
    <field name="model">account.report.budget.item</field>
    <field name="inherit_id" ref="account_reports.view_account_report_budget_item_tree"/>
    <field name="arch" type="xml">
      <xpath expr="//tree" position="attributes">
        <attribute name="editable">bottom</attribute>
        <attribute name="multi_edit">1</attribute>
      </xpath>
      <xpath expr="//tree" position="inside">
        <field name="x_analytic_account_id" optional="show"
               options="{'no_create': True, 'no_create_edit': True}"/>
      </xpath>
    </field>
  </record>
</odoo>
'''

MENUS_XML = '''<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <record id="action_sn_report_budget_budgets" model="ir.actions.act_window">
    <field name="name">Budgets financiers</field>
    <field name="res_model">account.report.budget</field>
    <field name="view_mode">tree,form</field>
    <field name="help" type="html">
      <p class="o_view_nocontent_smiling_face">Créer un budget financier</p>
      <p>Rattachez un compte analytique pour le wizard « Budget par projet » Senedoo.</p>
    </field>
  </record>

  <record id="action_sn_report_budget_lines" model="ir.actions.act_window">
    <field name="name">Lignes de budget (détail)</field>
    <field name="res_model">account.report.budget.item</field>
    <field name="view_mode">tree,form</field>
    <field name="help" type="html">
      <p class="o_view_nocontent_smiling_face">Ajouter des lignes</p>
      <p>Édition directe en liste ; ouvrez une ligne pour le formulaire détaillé.</p>
    </field>
  </record>

  <menuitem id="menu_sn_report_budget_root"
            name="Budgets financiers (Senedoo)"
            parent="account.menu_finance_reports"
            sequence="18"/>

  <menuitem id="menu_sn_report_budget_budgets"
            name="Budgets et axes analytiques"
            parent="menu_sn_report_budget_root"
            action="action_sn_report_budget_budgets"
            sequence="10"/>

  <menuitem id="menu_sn_report_budget_lines"
            name="Lignes de budget"
            parent="menu_sn_report_budget_root"
            action="action_sn_report_budget_lines"
            sequence="20"/>
</odoo>
'''


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    # newline POSIX
    if not path.read_bytes().endswith(b"\n"):
        path.write_bytes(path.read_bytes() + b"\n")


def generate(out_dir: Path) -> None:
    out_dir = out_dir.resolve()
    write_file(out_dir / "__manifest__.py", MANIFEST.strip() + "\n")
    write_file(out_dir / "__init__.py", INIT_ROOT.strip() + "\n")
    write_file(out_dir / "models" / "__init__.py", INIT_MODELS.strip() + "\n")
    write_file(out_dir / "models" / "account_report_budget.py", MODEL_PY.strip() + "\n")
    write_file(out_dir / "views" / "account_report_budget_views.xml", BUDGET_VIEWS_XML.strip() + "\n")
    write_file(out_dir / "views" / "account_report_budget_item_views.xml", ITEM_VIEWS_XML.strip() + "\n")
    write_file(out_dir / "views" / "menus.xml", MENUS_XML.strip() + "\n")
    readme = out_dir / "README.txt"
    write_file(
        readme,
        """Module généré par scripts/generate_sn_report_budget_analytic_module.py

Installation (Odoo.sh / serveur avec Enterprise) :
  1. Copier le dossier dans addons (ou ZIP et Apps > Importer).
  2. Mettre à jour la liste des applications puis installer « Budgets financiers — analytique (Senedoo) ».
  3. Comptabilité / Facturation > Reporting > Budgets financiers (Senedoo).

Si l’installation échoue sur une vue (inherit_id introuvable) :
  - Vérifier la version du module account_reports et les IDs externes des vues formulaire budget.
  - Adapter views/account_report_budget_views.xml (ref=…).

Si l’héritage de l’arbre des lignes échoue (inherit_id introuvable) :
  - Éditer views/account_report_budget_item_views.xml : ajuster ref="account_reports.…"
    (nom exact de la vue liste ``account.report.budget.item`` sur votre version).

Conflit avec la toolbox (champs manuels x_analytic_account_id) :
  - Supprimer d’abord les champs manuels homonymes sur les modèles concernés, ou ne pas installer
    ce module et continuer à utiliser uniquement la création de champs via la toolbox.

Wizard « Budget par projet » :
  - Le domaine du wizard reconnaît x_analytic_account_id et analytic_account_id sur le budget.
""".strip()
        + "\n",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "examples" / "sn_report_budget_analytic",
        help="Dossier cible du module (sera créé).",
    )
    args = ap.parse_args()
    generate(args.out)
    print(f"OK — module écrit sous : {args.out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
