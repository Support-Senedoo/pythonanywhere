Module généré par scripts/generate_sn_report_budget_analytic_module.py

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
