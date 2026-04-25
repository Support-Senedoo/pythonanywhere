# Journal agent — reprise entre sessions Cursor

Les assistants **n’ont pas** de mémoire des chats précédents. Ce fichier, **versionné dans Git**, sert à **noter les faits utiles** (déploiements PA, échecs, leçons) pour que la **session suivante** (ou un autre agent) les retrouve en lisant le dépôt.

**Règles** : une ligne par fait important ; **aucun secret** (pas de token API, mot de passe, clé privée, extrait de `toolbox_clients.json`).

---

## Modèle d’entrée (à copier en bas du fichier)

```markdown
### AAAA-MM-JJ — titre court
- **Action** : (ex. commit, push, `bash deploy_to_pa.sh -SkipGitPush`, action Odoo staff)
- **Résultat** : OK | échec
- **Références** : hash Git `…`, version toolbox `…` si pertinent
- **Erreur / leçon** : (vide si OK ; sinon message ou cause racine)
```

---

## Entrées

### 2026-04-23 — Cookie portail odoo.com : variables d’environnement + script Playwright (toolbox 1.10.21)
- **Action** : `TOOLBOX_ODOO_PORTAL_COOKIE` / `TOOLBOX_ODOO_PORTAL_COOKIE_FILE` lus par la toolbox ; fusion sur `/staff/admin/odoo-connexion` et sonde bases ; script `scripts/capture_odoo_portal_cookie_playwright.py` ; `git push` + `bash deploy_to_pa.sh -SkipGitPush`.
- **Résultat** : OK — PA pull `7c9095d..c55429e`, reload Web `{"status":"OK"}`.
- **Références** : commit `c55429e`, toolbox **1.10.21**.
- **Erreur / leçon** : ne jamais committer le cookie ; renouveler quand la session odoo.com expire.

### 2026-04-23 — Connexion Odoo admin : aide captcha + cookie portail visible (toolbox 1.10.20)
- **Action** : `/staff/admin/odoo-connexion` — encadré PythonAnywhere / captcha, champ Cookie en évidence, rappel « étape suivante » si message portail captcha ; `git push` + `bash deploy_to_pa.sh -SkipGitPush`.
- **Résultat** : OK — PA pull jusqu’à `7c9095d`, reload Web `{"status":"OK"}`.
- **Références** : commit `7c9095d`, toolbox **1.10.20**.
- **Erreur / leçon** : le captcha odoo.com depuis PA reste une limite du portail ; l’UI doit orienter vers le cookie navigateur sans le cacher dans un `<details>`.

### 2026-04-23 — Correctif site HS : `staff_selected_client_persist.py` manquant dans Git (toolbox 1.10.19)
- **Action** : ajout du fichier au dépôt (déjà importé par `staff_admin` depuis 1.10.18) ; `git push` + `bash deploy_to_pa.sh -SkipGitPush`.
- **Résultat** : OK — PA pull `e6470d6..3c8cf76`, reload Web `{"status":"OK"}`.
- **Références** : commit `3c8cf76`, toolbox **1.10.19**.
- **Erreur / leçon** : message générique PA « Something went wrong » = vérifier erreur WSGI (import) ; tout module importé par un blueprint doit être versionné ; test local `create_app()` avant push.

### 2026-04-23 — Administration : connexion Odoo, liste des bases, enregistrement (toolbox 1.10.18)
- **Action** : page `/staff/admin/odoo-connexion` (`probe_account_databases`, session fichiers pour mémoriser login/mot de passe, bouton enregistrer + base active) ; liens liste clients / accueil staff / utilitaires ; `git push` + `bash deploy_to_pa.sh -SkipGitPush` (US, clé `~/.ssh/id_ed25519_pa_cursor`).
- **Résultat** : OK — PA fast-forward `188b158..e6470d6`, reload Web `{"status":"OK"}`.
- **Références** : commit `e6470d6`, toolbox **1.10.18**.
- **Erreur / leçon** : régression corrigée en **1.10.19** : import `staff_selected_client_persist` sans fichier dans Git → plantage WSGI jusqu’au correctif.

### 2026-04-19 — CPC wizard : menu assistant invisible → ir.model.access (toolbox 1.10.4)
- **Action** : correction `create_cpc_odoo_wizard.py` — création de règles **ir.model.access** sur `x_cpc_budget_wizard` pour les groupes comptables Odoo (Facturation / Comptable / Responsable + EE `account_accountant` si présent) ; contrôle post-install ; doc écran staff. `git push` + `bash deploy_to_pa.sh -SkipGitPush`.
- **Résultat** : OK — PA pull `63508ac`, reload Web `{"status":"OK"}`.
- **Références** : commit `63508ac`, toolbox **1.10.4**.
- **Erreur / leçon** : un modèle **manuel** sans `ir.model.access` laisse Odoo filtrer le menu pour les non-admins ; le parent `ir.ui.menu` était correct mais l’entrée restait invisible pour les comptables.

### 2026-04-19 — Toolbox 1.10.3 : libellés français (écran P&L analytique / CPC) + PA
- **Action** : `git push origin master` puis `bash deploy_to_pa.sh -SkipGitPush` (Mac, clé `~/.ssh/id_ed25519_pa_cursor`, cible `senedoo@ssh.pythonanywhere.com`).
- **Résultat** : OK — sur PA pull `21611f6` → `91e34e6`, reload Web API `{"status":"OK"}`.
- **Références** : commit `91e34e6`, toolbox **1.10.3** (`app_version.py`, livraison 2026-04-19).
- **Erreur / leçon** : (vide)

### 2026-04-14 — Déploiement PA après menus CPC (1. / 2.)
- **Action** : `git push origin master` puis `bash deploy_to_pa.sh -SkipGitPush` (Mac, clé `~/.ssh/id_ed25519_pa_cursor`).
- **Résultat** : OK — sur PA pull `078528e` → `5cf5e56`, reload Web API `{"status":"OK"}`.
- **Références** : commit `5cf5e56`, toolbox **1.10.1** (`app_version.py`).
- **Erreur / leçon** : une réponse avait indiqué à tort que le déploiement ne pouvait pas se faire depuis macOS ; le bon script local est **`deploy_to_pa.sh`** (équivalent de **`deploy_pa.ps1`**). Toujours vérifier dans le dépôt avant d’affirmer une contrainte d’OS.

### 2026-04-25 — Liens « Nouvelle base » visibles (toolbox 1.10.25)
- **Action** : `git push` + `bash deploy_to_pa.sh -SkipGitPush` ; PA pull jusqu’à `82adc8c`, reload Web `{"status":"OK"}`.
- **Résultat** : OK — toolbox **1.10.25** (accueil staff + utilitaires).
- **Références** : commit `82adc8c`.
- **Erreur / leçon** : (vide)

### 2026-04-25 — Toolbox 1.10.24 : UI base→utilitaires, accordéons, portefeuille ; déploiement PA
- **Action** : `git push origin master` ; sur PA `git fetch` puis **`git reset --hard origin/master`** (fichier `web_app/__init__.py` modifié localement sur PA — doublon config — bloquait le pull) ; `bash deploy_to_pa.sh -SkipGitPush` ; reload Web `{"status":"OK"}`.
- **Résultat** : OK — PA sur commit **`bf43e81`**, toolbox **1.10.24**.
- **Références** : commit `bf43e81` (remplace `c55429e` côté disque PA).
- **Erreur / leçon** : ne pas éditer à la main sur PA des fichiers versionnés sans commit ; sinon `pull` échoue — préférer stash ou annuler la modif, ou tout aligner sur `origin/master` si pas de travail local à garder.

### 2026-04-14 — Menu wizard CPC invisible (Odoo) : act_window + parent = menu rapport
- **Action** : code `create_cpc_odoo_wizard.py` — menu « 1. Assistant » via **`ir.actions.act_window`** au lieu de **`ir.actions.server`** ; alignement **`parent_id`** du menu assistant sur celui du menu « 2. Rapport ».
- **Résultat** : livré en toolbox **1.10.2** ; après **Mettre à jour Budget par projet** dans Odoo, l’entrée **1.** doit apparaître au même endroit que **2.** (juste au-dessus si séquences 8/9).
- **Leçon** : les menus **`ir.actions.server`** peuvent ne pas s’afficher dans la barre latérale selon édition / droits ; **`ir.actions.act_window`** est le pattern standard des entrées visibles.

### 2026-04-25 — Suggestion automatique URL Odoo depuis le nom de base (toolbox 1.10.26)
- **Action** : auto-remplissage JS sur formulaires de création de base (`db/new_db` -> `https://<db>.odoo.com`) sans écraser une URL modifiée manuellement.
- **Résultat** : OK — saisie plus rapide sur admin + utilitaires.
- **Références** : commit toolbox 1.10.26 (voir historique Git).
- **Erreur / leçon** : garder le comportement en suggestion seulement (pas de forçage).

### 2026-04-25 — Création base : choisir ou créer client portefeuille (toolbox 1.10.27)
- **Action** : formulaires de création de base (admin, connexion Odoo, utilitaires) avec liste de clients portefeuille + création inline (id + nom), puis rattachement automatique.
- **Résultat** : OK — si la liste est vide, création possible sans quitter le formulaire.
- **Références** : commit toolbox 1.10.27 (voir historique Git).
- **Erreur / leçon** : création inline doit rester optionnelle et non bloquante.

### 2026-04-25 — Toolbox 1.10.28 : slug auto portefeuille + fallback identifiants ; déploiement PA
- **Action** : commit minimal `59176fb` (slug client portefeuille généré depuis le nom, plus fallback identifiants pour éviter l'erreur mot de passe introuvable), `git push origin master`, puis `bash deploy_to_pa.sh -SkipGitPush`.
- **Résultat** : OK — PA fast-forward `4e3e06d..59176fb`, reload Web API `{"status":"OK"}`.
- **Références** : commit `59176fb`, toolbox **1.10.28**.
- **Erreur / leçon** : si la version affichée ne bouge pas après merge local, vérifier push + reload PA (une variable Web peut aussi surcharger la version).

### 2026-04-25 — Toolbox 1.10.29 : rattachement portefeuille (upsert) + création client à l’édition ; PA
- **Action** : `UPSERT_PORTFOLIO_UNCHANGED` dans `upsert_client` (éviter d’interpréter `None` comme « conserver » en mise à jour), formulaire édition base aligné sur `_resolve_portfolio_client_from_form()` + bloc « Créer un client portefeuille », colonne portefeuille dans la liste admin ; `git push` + `bash deploy_to_pa.sh -SkipGitPush`.
- **Résultat** : OK — PA pull jusqu’à `8d50ff5`, reload Web `{"status":"OK"}`.
- **Références** : commit `8d50ff5`, toolbox **1.10.29**.
- **Erreur / leçon** : `portfolio_client_id=None` passé au merge devait signifier « détacher » ou « pas de choix » selon le flux ; un sentinelle explicite évite l’ambiguïté sur les ré-enregistrements.

