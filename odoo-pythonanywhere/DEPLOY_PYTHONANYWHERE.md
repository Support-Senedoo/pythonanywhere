# Déploiement PythonAnywhere — reprise rapide

Ce fichier sert de **mémoire projet** : les assistants IA n’ont pas de souvenir des sessions passées. Tout ce qui compte pour remettre en ligne ou mettre à jour l’app doit rester **ici** (et dans le Git).

## Dépôt GitHub

- Organisation : **Support-Senedoo**
- Dépôt : **`pythonanywhere`** — https://github.com/Support-Senedoo/pythonanywhere  
- Clone : `git clone https://github.com/Support-Senedoo/pythonanywhere.git`

Le dépôt contient tout le dossier local (dont `odoo-pythonanywhere/`, `import-rapport-odoo/`, etc.). Sur PythonAnywhere, le **fichier WSGI** doit pointer vers le sous-dossier applicatif, par ex.  
`/home/senedoo/pythonanywhere/odoo-pythonanywhere/pythonanywhere_wsgi.py`  
si vous clonez le repo dans `/home/senedoo/pythonanywhere`. (Si vous ne gardez que le sous-dossier `odoo-pythonanywhere` à l’ancien chemin, adaptez le tableau ci-dessous.)

## Ce qui est déployé (état attendu)

- **Application** : Flask « toolbox » (`web_app`), WSGI = **`pythonanywhere_wsgi.py`** ou **`pa_wsgi.py`** (équivalent).
- **Portails** : accueil `/` (client / Senedoo), login, espace client sous `/client/`, staff sous `/staff/`, utilitaires rapports sous `/staff/utilities/` (liste : `utilities` ; P&L SYSCOHADA : `rapports-comptables` / `personalize-report` ; balance 6 col. : `personalize-balance` ; P&L budget : `personalize-pl-budget`).
- **Secrets sur le serveur uniquement** (jamais dans Git) :
  - `toolbox_users.json` — comptes + `password_hash` (Werkzeug)
  - `toolbox_clients.json` — URL / base / user API Odoo par `client_id`
  - Variable **`TOOLBOX_SECRET_KEY`** (onglet Web PythonAnywhere)
- **Version affichée** : incrémenter **`web_app/app_version.py`** (`_DEFAULT_VERSION`, `_DEFAULT_DATE`) à **chaque** livraison avec nouvelle fonctionnalité ou correctif notable — source unique pour l’UI et les utilitaires staff (surcharge possible par **`TOOLBOX_APP_VERSION`** / **`TOOLBOX_APP_DATE`** sur PA, voir ci-dessous).

Si l’interface affiche une **version « 1 »**, **« 1.0.0 »** ou autre valeur incohérente : onglet Web — supprimez **`TOOLBOX_APP_VERSION`** ou mettez une vraie livraison (ex. `1.3.3`). Le code **ignore** `1`, `1.0`, `1.0.0` et toute valeur **sans point**, puis reprend le défaut du dépôt. Après déploiement : **Reload** le site + rechargement forcé du navigateur (**Ctrl+Shift+R**) sur les pages `/staff/…` pour éviter un vieux HTML en cache.

Modèles : `toolbox_users.example.json`, `toolbox_clients.example.json`, `toolbox-env-exemple.txt`.

## Sur PythonAnywhere — référence projet (validé)

| Élément | Valeur |
|--------|--------|
| Utilisateur PA | `senedoo` |
| SSH (Bash / terminal) | `ssh senedoo@ssh.pythonanywhere.com` |
| Dépôt Git (clone) | `/home/senedoo/pythonanywhere` |
| Appli Flask | `/home/senedoo/pythonanywhere/odoo-pythonanywhere` |
| Fichier WSGI (onglet Web) | `/home/senedoo/pythonanywhere/odoo-pythonanywhere/pythonanywhere_wsgi.py` |
| Commande `pip` | adapter à la **même** version Python que le site web (ex. `pip3.10 install --user -r requirements.txt`) |
| URL publique du site | `https://senedoo.pythonanywhere.com/` |

*Dernière vérification manuelle : avril 2026 (SSH + MCP opérationnels).*

## Pourquoi « ça ne se met pas à jour » alors qu’avant (sans Git) ça marchait

Avec un **déploiement manuel** (upload / édition directe sur PA), vous modifiez **les mêmes fichiers** que ceux que le serveur Web exécute : un seul endroit, pas d’ambiguïté.

Avec **Git** :

1. **`git pull`** met à jour les fichiers **sur le disque** du serveur (dans le clone, ex. `~/pythonanywhere`).
2. Le **processus Python** qui sert le site (WSGI) garde en **mémoire** l’ancien code (modules déjà importés, templates compilés) **jusqu’à un redémarrage**.
3. Sur PythonAnywhere, ce redémarrage = bouton **Reload** de l’onglet **Web** (pas seulement le terminal Bash).

Donc : **pull sans Reload** = disque à jour, **interface encore ancienne** (ex. version `1.0.0` affichée alors que le fichier `app_version.py` sur disque dit `1.3.x`). Ce n’est pas un bug Git : c’est le cycle de vie du worker WSGI.

**À vérifier une fois pour toutes** : dans l’onglet Web, le **chemin du fichier WSGI** pointe bien vers le `pa_wsgi.py` (ou `pythonanywhere_wsgi.py`) **à l’intérieur du clone** (ex. `.../pythonanywhere/odoo-pythonanywhere/`), et non vers une vieille copie hors dépôt.

Les pages staff affichent aussi une **révision dépôt** (hash git lu sur le disque à la requête) : si elle est récente mais la ligne « Version » semble fausse, un **Reload** est nécessaire pour réimporter le code Python.

**Templates HTML** : Jinja mettait en cache les gabarits. Les entrées **`pythonanywhere_wsgi.py`** / **`pa_wsgi.py`** définissent **`TOOLBOX_JINJA_NO_CACHE`** et **`create_app`** applique **`jinja_options["cache_size"] = 0`** sur PythonAnywhere pour que les `.html` sur disque soient pris en compte sans rester « figés ». **Les changements de fichiers `.py`** exigent tout de même un **Reload** du worker (ou le reload API ci-dessous).

**Reload automatique après `deploy_pa.sh`** : le script appelle l’API **reload** si un token est disponible. **Recommandé (SSH / agent sans `.bashrc`)** : sur PA, créer **`~/.pythonanywhere_api_token`** (une ligne = token, `chmod 600`). Compte **EU** : fichier optionnel **`~/.pythonanywhere_api_host`** contenant une ligne `https://eu.pythonanywhere.com`. Alternative : variables d’environnement **`PYTHONANYWHERE_API_TOKEN`** et **`PYTHONANYWHERE_API_HOST`**. Token créé sous **Account → API token** — **jamais** dans Git, l’onglet Web, ni le chat.

## Déploiement / mise à jour du code

**À chaque publication** : **commit** + **push**, puis sur votre PC **`.\deploy_pa.ps1`** (ou **`.\deploy.ps1`** depuis la racine du dépôt). Cela pousse le code sur GitHub, se connecte en SSH à PA et lance **`deploy_pa.sh`** : **`git pull`**, **`pip`**, puis **reload du site** (voir paragraphe précédent : fichier **`~/.pythonanywhere_api_token`** sur PA). Sans ce fichier token, le script vous le rappelle : il faut alors cliquer **Reload** à la main dans l’onglet **Web**.

**Sur la machine du développeur** (PC avec Git + clé SSH PA sans passphrase, ex. `%USERPROFILE%\.ssh\id_ed25519_pa_cursor`) : l’assistant Cursor peut lancer **`.\deploy_pa.ps1 -SkipGitPush`** depuis `odoo-pythonanywhere/` après un **`git push`** — cela exécute sur PA **`deploy_pa.sh`** : **`git pull`**, **`pip`**, **reload API** si `~/.pythonanywhere_api_token` existe. **Sans** cette machine / cette clé, seul **vous** (PowerShell local, Bash PA, ou bouton Reload) déclenchez la mise à jour effective du worker WSGI.

### Si `deploy_pa.ps1` plante au démarrage (ParserError, accents « cassés »)

Le script **`deploy_pa.ps1` du dépôt** utilise des **messages ASCII** dans le code exécutable (depuis avril 2026) pour éviter ce cas sur **Google Drive / Mon Drive** avec **PowerShell 5.1**. Si vous avez encore une **ancienne copie** ou un fichier ré-enregistré avec accents dans les `Write-Host` / `Write-Error`, le parseur peut mal lire le fichier (erreurs *Argument manquant*). **Le serveur PA n’est pas en cause** : blocage local au `.ps1`.

**Alternatives fiables** (après `git push` depuis la machine où Git fonctionne) :

1. **Console Bash PythonAnywhere** : `cd ~/pythonanywhere && git fetch origin && git pull --ff-only && cd odoo-pythonanywhere && python3.10 -m pip install --user -r requirements.txt` puis **Reload** Web.  
2. **Bloc manuel `scp` + `ssh`** (même principe que dans le script) — voir plus bas.  
3. **MCP Cursor** `execute_command` (SSH) avec la même commande bash ; `privateKeyPath` = clé sans passphrase, ex. `%USERPROFILE%\.ssh\id_ed25519_pa_cursor`.  
4. **Contournement PC** : enregistrer `deploy_pa.ps1` en **UTF-8 avec BOM**, ou copier le script sur un disque local (ex. `C:\temp`) et l’exécuter depuis là.

**Option A — Git (recommandé)**  
Depuis `odoo-pythonanywhere/` : **`.\deploy_pa.ps1`**. Depuis la **racine du dépôt** : **`.\deploy.ps1`**. Push déjà fait ailleurs : **`.\deploy_pa.ps1 -SkipGitPush`**. Sous Cursor : tâche **« Publier sur PythonAnywhere »** (Terminal → Exécuter la tâche…).

### Déploiement sans saisie de phrase secrète (agent / MCP)

1. `.\setup_pa_automation_key.ps1` — crée `%USERPROFILE%\.ssh\id_ed25519_pa_cursor` (sans passphrase, **ne pas commiter**).
2. `.\install_pa_ssh_key.ps1 -IdentityFile "$env:USERPROFILE\.ssh\id_ed25519_pa_cursor"` — mot de passe **compte PA une fois** pour enregistrer la clé sur le serveur.
3. Ensuite **`deploy_pa.ps1`** utilise cette clé tout seul si le fichier existe ; pour MCP, `privateKeyPath` doit pointer vers ce même fichier.

### Déployer / mettre à jour Flask depuis votre PC (avec votre clé SSH)

**Forcer l’usage de la clé privée** (recommandé si plusieurs clés ou agent absent) :

```powershell
cd "...\budget-financier\odoo-pythonanywhere"
.\deploy_pa.ps1
```

Par défaut le script utilise `%USERPROFILE%\.ssh\id_ed25519`. Autre fichier :

```powershell
.\deploy_pa.ps1 -IdentityFile "C:\Users\patri\.ssh\id_rsa"
```

Équivalent manuel (évite le tube `Get-Content | ssh`, qui peut bloquer avec une clé protégée par phrase secrète) :

```powershell
$key = "$env:USERPROFILE\.ssh\id_ed25519"
scp -i $key -o StrictHostKeyChecking=accept-new .\deploy_pa.sh senedoo@ssh.pythonanywhere.com:~/deploy_pa_run.sh
ssh -i $key -o StrictHostKeyChecking=accept-new senedoo@ssh.pythonanywhere.com "chmod +x ~/deploy_pa_run.sh && bash ~/deploy_pa_run.sh; rm -f ~/deploy_pa_run.sh"
```

**Note** : un assistant lancé dans un environnement **sans** accès à votre agent SSH / votre session Windows peut échouer avec `Permission denied` même avec `-i` ; dans ce cas exécutez **`deploy_pa.ps1` vous-même** dans PowerShell ou le terminal intégré Cursor **sur votre machine**.

*(Si le dépôt GitHub est **privé**, configurez d’abord un accès `git` sur PA : token HTTPS ou clé déployée — sinon le `git clone`/`pull` échouera.)*

### Déployer depuis la console Bash PythonAnywhere

1. **Files** : uploader `deploy_pa.sh` dans votre répertoire home, ou coller son contenu dans un fichier.  
2. **Bash** :

```bash
chmod +x ~/deploy_pa.sh   # si besoin
bash ~/deploy_pa.sh
```

*(Vous pouvez aussi `bash` directement le fichier du repo après un clone manuel.)*

Fichier script : **[`deploy_pa.sh`](deploy_pa.sh)**.

**Option B — SCP / rsync depuis votre PC**  
Synchroniser le dossier `odoo-pythonanywhere/` vers `/home/senedoo/odoo-pythonanywhere/` (exclure `.venv`, `__pycache__`, `toolbox_*.json` locaux si vous ne voulez pas écraser les secrets du serveur).

**Après chaque mise à jour**  
1. `cd /home/senedoo/odoo-pythonanywhere`  
2. `pip3.X install --user -r requirements.txt`  
3. Onglet **Web** → **Reload**

## Cursor / MCP SSH PythonAnywhere — configuration **une fois** (validée)

L’IA ne « retient » pas votre clé entre deux chats. La config vit dans le **fichier MCP utilisateur** de Cursor (souvent `%USERPROFILE%\.cursor\mcp.json` sous Windows), **pas** dans le dépôt.

### Exemple dans ce dépôt

Fichier **[`mcp-pythonanywhere.example.json`](mcp-pythonanywhere.example.json)** : même structure que la config **qui fonctionne** avec le paquet npm `ssh-mcp-server` (via `npx`).

À faire sur une machine : fusionner ce bloc dans votre `mcp.json` global (ou copier les clés dans l’UI MCP). Adapter le chemin **`command`** si Node.js n’est pas sous `C:\Program Files\nodejs\` (sur Mac/Linux, souvent `"command": "npx"` suffit).

### OpenSSH (recommandé en complément)

Pour que les outils / le terminal trouvent user et clé sans ambiguïté, un bloc dans **`~/.ssh/config`** est utile, par ex. :

```sshconfig
Host pythonanywhere
    HostName ssh.pythonanywhere.com
    User senedoo
    IdentityFile ~/.ssh/id_ed25519
```

(adaptez le chemin de `IdentityFile` sous Windows si besoin.)

### Ce qu’il ne faut **jamais** faire

- Commiter le **contenu** d’une clé **privée**, un mot de passe, ou un `mcp.json` personnel contenant des secrets.
- D’autres variantes de MCP peuvent exiger `host` / `username` / `privateKeyPath` **par appel d’outil** : ce dépôt documente surtout le flux **`ssh-mcp-server`** validé en avril 2026.

### Pour la « fois suivante »

- Vous ne refaites **pas** la config tant que vous ne changez pas de PC ni de clé.
- Vous dites à l’assistant : **« Utilise le MCP PythonAnywhere SSH et suis `DEPLOY_PYTHONANYWHERE.md` »** — la règle projet [`.cursor/rules/pythonanywhere-deploy.mdc`](../.cursor/rules/pythonanywhere-deploy.mdc) rappelle déjà de lire ce fichier.

## Checklist « reprise après une pause »

- [ ] Code **commit + push GitHub** (sinon le `git pull` sur PA ne ramène rien)
- [ ] Déploiement : **`deploy_pa.ps1`** depuis `odoo-pythonanywhere/` (après push) ; si le code est déjà sur GitHub : **`.\deploy_pa.ps1 -SkipGitPush`**. Si le `.ps1` casse (ParserError), **`git pull` sur PA** / **scp+ssh** / **MCP SSH** (voir section « Si deploy_pa.ps1 plante »)
- [ ] `requirements.txt` réinstallé avec la **bonne** version Python du web app
- [ ] `toolbox_users.json` et `toolbox_clients.json` toujours présents sur le serveur
- [ ] Staff production : `TOOLBOX_DISABLE_DEV_LOGIN=1` + compte(s) staff dans le JSON avec `password_hash`
- [ ] Réinit. e-mail (si besoin) : `TOOLBOX_PUBLIC_BASE_URL`, `TOOLBOX_SMTP_*`, `TOOLBOX_MAIL_FROM` + test `/forgot-password`
- [ ] `TOOLBOX_SECRET_KEY` toujours défini dans l’onglet Web
- [ ] WSGI pointe toujours vers `pythonanywhere_wsgi.py` (ou `pa_wsgi.py`)
- [ ] **Reload** du site (onglet Web PythonAnywhere)

## Reprise technique — toolbox `odoo-pythonanywhere` (avril 2026)

À lire par l’assistant au prochain fil : évite de réinventer ce qui est déjà en place.

### Déploiement & WSGI

- Racine projet sur PA : typiquement `/home/senedoo/pythonanywhere` ; appli Flask : **`odoo-pythonanywhere/`**. `pythonanywhere_wsgi.py` insère ce dossier dans `sys.path` puis `create_app()`.
- Erreurs applicatives : journal **`/var/log/senedoo.pythonanywhere.com.error.log`** (attention : **point** avant `pythonanywhere` dans le nom du fichier).

### Admin staff (`/staff/admin/…`)

- Plus de module **`web_app.odoo_db_list`** : la logique liste bases / `db.list()` pour les suggestions JSON est **inlinée** dans **`web_app/blueprints/staff_admin.py`** (`managed_databases_from_env`, `_fetch_databases_from_server`, `merge_database_suggestions`) pour éviter tout `ModuleNotFoundError` si un fichier manque au pull.
- Endpoint JSON suggestions bases : route existante sous le blueprint admin (URL préfixée `/admin`).

### Utilitaire « Sonde bases Odoo par compte » (`/staff/utilities/odoo-compte-bases`)

- **Modes** (voir **`web_app/odoo_account_probe.py`**) :
  - **Sans URL, login portail** : session HTTP sur **www.odoo.com** (login + mot de passe + CSRF, en-têtes type navigateur, `Sec-Fetch-*`, léger délai avant POST), page **Mes bases**, etc. **Captcha / Turnstile** : souvent imposé pour les IP **datacenter** (PythonAnywhere) — la toolbox ne peut pas le résoudre seule.
  - **Sans URL, cookie navigateur** : après **connexion manuelle** sur odoo.com (captcha OK), l’utilisateur colle l’en-tête **Cookie** de la requête document vers **Mes bases** (onglet Réseau des outils développeur). Le serveur PA refait un `GET` sur `/my/databases` avec ce cookie pour extraire les liens `*.odoo.com` — pas de login HTTP automatisé. **Risque** : le cookie équivaut à une session complète ; ne pas le partager. Le **login** du formulaire sert surtout à l’**XML-RPC** sur chaque instance (mot de passe souvent encore nécessaire pour les tests API).
  - **Avec URL** : `db.list()` sur cette instance si le service `db` existe ; sinon liste vide et message via **`format_db_list_error`** / **`_is_odoo_db_service_disabled`** (dont `KeyError: 'db'` / `repr(Fault)` avec `\'db\'`).
- Variables optionnelles : **`TOOLBOX_ODOO_PORTAL_ORIGIN`**, **`TOOLBOX_ODOO_PORTAL_LANG`** (défaut `https://www.odoo.com`, `/fr_FR`) — voir **`toolbox-env-exemple.txt`**.
- **Mot de passe** et **cookie** : non réinjectés dans le HTML après POST ; le login peut être mémorisé côté navigateur (localStorage) pour la sonde.
- Version / date affichées : **`app_version.TOOLBOX_APP_VERSION`** / **`TOOLBOX_APP_DATE`**, injectées par **`web_app/blueprints/staff.py`** (`util_version`, `util_date`).

### Métadonnées instance Odoo (version de la **base**)

- Fichier : **`web_app/odoo_instance_info.py`** — fonction **`collect_authenticated_instance_metadata`** (appelée depuis les écrans rapports staff quand la connexion XML-RPC est OK).
- **Version « officielle » installée en base** : module **`base`** (`ir.module.module`, état installé), champ **`latest_version`** — affichée comme *« Version Odoo (module base, installée en base) »*. Compléments : **`common.version()`** (`server_version`, `server_version_info` formaté), **`web_enterprise`** si présent, **`ir.config_parameter`** (UUID, expiration, etc.).

### Utilitaires personnalisation rapports (`account.report`)

- **Suppression depuis la toolbox** : avant `account.report.unlink`, le code retire les **`ir.ui.menu`** pointant sur l’action **`ir.actions.client`** (tag `account_report`, contexte avec ce `report_id`), puis supprime ces actions — évite les entrées de menu orphelines (`web_app/odoo_account_reports.py` : `unlink_account_report`).
- **Balance 6 col. — nom menu = nom rapport** : champ optionnel **`copy_display_name`** sur le formulaire ; renommage de la copie **avant** `ensure_account_report_reporting_menu`. Les actions client existantes sont resynchronisées (`ensure_account_report_client_action` + `sync_menu_labels_for_client_action`).

- Fichier principal : **`web_app/odoo_account_reports.py`**. Métadonnées **version** / **date** / **auteur** : **`web_app/app_version.py`** (et env `TOOLBOX_APP_*`, voir **`toolbox-env-exemple.txt`**).
- **Compte de résultat personnalisé (SYSCOHADA / détail comptes)** : `/staff/utilities/rapports-comptables` (alias `/staff/utilities/personalize-report`) — copie + [`personalize_syscohada_detail.py`](personalize_syscohada_detail.py).
- **Balance 6 colonnes** : `/staff/utilities/personalize-balance` — [`personalize_balance_6cols.py`](personalize_balance_6cols.py). La copie est **`attach_to_root=False`** (rapport **autonome**, limite les `KeyError` Enterprise type `sn_open_deb` / trial balance). Le script **vide `root_report_id` et `section_main_report_ids`** (« Section de ») en premier, puis réécrit les options depuis la racine si besoin ; la duplication autonome fait de même après recopie des options. Réécriture **autonome** répétée en fin de script. **Handler trial balance** : **conservé** (sans lui, erreur « Méthode invalide `_report_custom_engine_trial_balance` » sur les lignes concernées). Le post-processeur Enterprise attend des libellés de colonne du type `debit` / `credit` / `balance` pour les blocs initial/période : des libellés `sn_*` peuvent encore provoquer un `KeyError` ; **alternative** documentée sur la page staff (Odoo v19 : moteur `aggregation`, `subformula` `positive` / `negative`, option **Inclure le solde initial**, `groupby` compte ; gabarit XML [`examples/balance_generale_6_col_studio.example.xml`](examples/balance_generale_6_col_studio.example.xml)). Copie déjà cassée (handler vide) : refaire une copie avec la toolbox à jour ou réaligner le handler sur la balance standard ; on peut aussi vider **Racine du rapport** / **Section de** depuis les rapports comptables. Après succès : création **`ir.actions.client`** + entrée **`ir.ui.menu`** dans le sous-menu **Grands livres** (parent = celui du **Grand livre général** si xmlid `menu_action_account_report_general_ledger` ; fin de liste des enfants ; repli après balance comptable puis **Reporting**), lien **`/web#menu_id=…&action=…`**, liste **`account.report`** en secours. Plus de confirmation « OUI » sur les formulaires copie (le bouton suffit).
- **P&L analytique et budget (Odoo SaaS)** : `/staff/utilities/personalize-pl-budget` — même détail comptes, puis options `filter_analytic` / `filter_budget` via [`personalize_pl_analytic_budget.py`](personalize_pl_analytic_budget.py). **Sonde budget / analytique** (lecture seule) sur cette page uniquement.
- **CLI (hors Flask)** : `python personalize_pl_analytic_budget.py --report-id <id>` sur une copie déjà créée ; `--probe-only` pour la sonde seule.

#### Checklist budget financier × compte analytique (SaaS)

1. **Données** : les lignes de budget financier doivent porter l’**analytique** attendu (répartition ou compte analytique selon la version). La sonde staff indique un ratio « lignes avec analytique / total » ; 0 % signifie qu’il faut compléter la saisie côté Odoo avant d’exiger un budget « par axe » dans le rapport.
2. **Test moteur standard** : ouvrir la **copie** du P&L dans Odoo, choisir la période, un **budget** et un **compte analytique**. Vérifier si la **colonne budget** change quand on change l’analytique. Si **oui**, la configuration (filtres + saisie) suffit en général. Si **non**, le moteur du rapport ne croise pas budget et analytique : envisager **Odoo Studio** (limites selon abonnement), un **rapport analytique** (budget analytique vs réalisé) en complément, ou une évolution validée par Odoo.
3. **Lignes sans mouvement analytique** : utiliser d’abord les options du rapport (**masquer lignes à zéro** / équivalent selon l’UI). Si la structure SYSCOHADA garde des totaux de section non nuls, combiner avec le détail par compte (personnalisation existante) ou ajuster via Studio si nécessaire.
4. **Risque connu** : sur certaines bases Enterprise, le **groupby compte** + notes peut provoquer des erreurs RPC au dépliage — voir `--revert` dans [`personalize_syscohada_detail.py`](personalize_syscohada_detail.py).

### Pistes « demain » possibles

- Fragilité du **parsing HTML** du portail si Odoo change la page Mes bases ; instances hors `*.odoo.com` non détectées par ce mode.
- Vérifier sur PA que le **venv / version Python** de l’onglet Web correspond à celle utilisée pour `pip` dans `deploy_pa.sh` (`PYTHONANYWHERE_PYTHON` si besoin).

---

*Dernière mise à jour de cette section : avril 2026 — balance 6 col. : handler trial balance conservé (évite « Méthode invalide ») ; menu groupe Grands livres (ancrage Grand livre) ; sans confirmation OUI ; détachement racine avant `sn_*` ; `deploy_pa.ps1 -SkipGitPush` ; Reload Web si pas de token API reload.*

## Générer un hash mot de passe (utilisateurs toolbox)

```bash
python toolbox_generate_password_hash.py
```

Coller le résultat dans `toolbox_users.json` (`password_hash`).

## Comptes staff via `toolbox_users.json` (sans dépendre de la démo)

Par défaut, l’app accepte aussi des identifiants **codés en dur pour la démo** (`test` / `passer`, et en staff `support@senedoo.com` / `2026@Senedoo`) tant que **`TOOLBOX_DISABLE_DEV_LOGIN`** n’est **pas** défini. Pour n’utiliser **que** le fichier JSON (recommandé en production) :

1. **Onglet Web** PythonAnywhere → **Variables d’environnement** → ajouter  
   **`TOOLBOX_DISABLE_DEV_LOGIN`** = **`1`** (ou `true` / `yes` / `on`).
2. Créer ou éditer **`toolbox_users.json`** sur le serveur (hors Git), au bon chemin :
   - par défaut : **`/home/senedoo/pythonanywhere/odoo-pythonanywhere/toolbox_users.json`**  
     (même dossier que `pythonanywhere_wsgi.py`, sauf si vous avez défini **`TOOLBOX_USERS_PATH`**).
3. Y mettre au moins un utilisateur **`role`: `staff`** avec un **`password_hash`** Werkzeug valide.

**Exemple minimal** (à adapter ; ne pas commiter les vrais secrets) :

```json
{
  "users": [
    {
      "login": "support@senedoo.com",
      "password_hash": "COLLER_ICI_LE_HASH_GENERE",
      "role": "staff"
    }
  ]
}
```

**Générer le hash** (sur votre PC ou dans une **console Bash** PA, depuis `odoo-pythonanywhere/`) :

```bash
cd ~/pythonanywhere/odoo-pythonanywhere
python3.10 toolbox_generate_password_hash.py 'VotreMotDePasseSecurise'
```

Copier la **ligne unique** affichée dans le champ **`password_hash`**.

4. **Reload** du site Web (onglet Web).

Sans démo et sans ligne staff dans le JSON, la connexion équipe échouera : vérifiez le fichier et les droits de lecture du processus WSGI.

## Réinitialisation du mot de passe par e-mail (`/forgot-password`)

L’app envoie un lien (valide **24 h**) si :

- l’identifiant saisi existe dans **`toolbox_users.json`** ;
- **`TOOLBOX_SMTP_HOST`** et **`TOOLBOX_MAIL_FROM`** sont renseignés ;
- l’envoi SMTP réussit (TLS, identifiants corrects).

### Variables à ajouter (onglet Web PythonAnywhere)

| Variable | Exemple / rôle |
|----------|----------------|
| **`TOOLBOX_PUBLIC_BASE_URL`** | `https://senedoo.pythonanywhere.com` — **sans** `/` final. Évite un mauvais lien si le serveur ne devine pas l’URL publique. |
| **`TOOLBOX_SMTP_HOST`** | `smtp.gmail.com`, `smtp.sendgrid.net`, serveur de votre hébergeur mail, etc. |
| **`TOOLBOX_SMTP_PORT`** | `587` (défaut si omis) — STARTTLS, comme dans le code (`starttls` puis login). |
| **`TOOLBOX_SMTP_USER`** | Utilisateur SMTP (souvent l’adresse e-mail du compte). |
| **`TOOLBOX_SMTP_PASSWORD`** | Mot de passe ou **mot de passe d’application** (ex. Gmail avec 2FA). |
| **`TOOLBOX_MAIL_FROM`** | Adresse **expéditeur** visible par le destinataire (souvent identique à `SMTP_USER` ou un alias autorisé par le fournisseur). |

Optionnel : **`TOOLBOX_PASSWORD_RESET_TOKENS_PATH`** — fichier JSON des jetons (défaut : `toolbox_password_reset_tokens.json` dans le **même répertoire que** `toolbox_users.json`). Le fichier est créé automatiquement ; pas besoin de le versionner.

Référence copier-coller : fichier **[`toolbox-env-exemple.txt`](toolbox-env-exemple.txt)** (section « Réinitialisation mot de passe »).

### Après modification des variables

1. **Reload** du site Web.  
2. Tester : page d’accueil ou connexion → **Mot de passe oublié ?** → saisir un **login exact** présent dans `toolbox_users.json`.  
3. Si le serveur répond une erreur SMTP, consulter le **journal d’erreurs** du site (`…error.log` sur PA) et vérifier pare-feu / politique du fournisseur (Gmail : « applications moins sécurisées » remplacé par **mots de passe d’application**).

### Limites PythonAnywhere

Les comptes **gratuits** n’ont pas un service mail intégré pour votre domaine : il faut un **relais externe** (Gmail, SendGrid, Mailgun, SMTP du registrar, etc.). Si aucune variable SMTP n’est configurée, la page « mot de passe oublié » affiche que l’e-mail n’est pas configuré et invite à contacter l’administrateur.

---

*Intention globale : toolbox Flask unifiée (portails client / staff Senedoo, admin clients & comptes, utilitaires Odoo), registre multi-bases, auth par fichiers JSON.*
