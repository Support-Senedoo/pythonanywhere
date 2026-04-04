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
- **Portails** : accueil `/` (client / Senedoo), login, espace client sous `/client/`, staff sous `/staff/`, utilitaire personnalisation rapport sous `/staff/utilities/personalize-report`.
- **Secrets sur le serveur uniquement** (jamais dans Git) :
  - `toolbox_users.json` — comptes + `password_hash` (Werkzeug)
  - `toolbox_clients.json` — URL / base / user API Odoo par `client_id`
  - Variable **`TOOLBOX_SECRET_KEY`** (onglet Web PythonAnywhere)

Si l’interface affiche une **version « 1 »** : vérifiez l’onglet Web — **`TOOLBOX_APP_VERSION=1` seul est invalide** (à supprimer ou remplacer par ex. `1.3.2`). Depuis avril 2026 le code **ignore** une valeur sans point et reprend le défaut du dépôt.

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

## Déploiement / mise à jour du code

**À chaque modification** : **commit** puis lancer **`deploy_pa.ps1`** depuis votre PC. Le script fait d’abord un **`git push`** vers `origin` (sauf si `-SkipGitPush`), puis sur PA **`deploy_pa.sh`** exécute **`git fetch` + `git pull --ff-only`**, `pip`, et vous rappelle le **Reload**. Sans commit / sans push réussi, le serveur ne verra pas les derniers fichiers.

**Important** : même si le `git pull` sur PA réussit, le site peut **continuer à servir l’ancien code** tant que vous n’avez pas cliqué **Reload** dans l’onglet Web. Un « déploiement raté » côté ressenti est souvent **Reload oublié**, pas un échec du pull.

### Si `deploy_pa.ps1` plante au démarrage (ParserError, accents « cassés »)

Le script **`deploy_pa.ps1` du dépôt** utilise des **messages ASCII** dans le code exécutable (depuis avril 2026) pour éviter ce cas sur **Google Drive / Mon Drive** avec **PowerShell 5.1**. Si vous avez encore une **ancienne copie** ou un fichier ré-enregistré avec accents dans les `Write-Host` / `Write-Error`, le parseur peut mal lire le fichier (erreurs *Argument manquant*). **Le serveur PA n’est pas en cause** : blocage local au `.ps1`.

**Alternatives fiables** (après `git push` depuis la machine où Git fonctionne) :

1. **Console Bash PythonAnywhere** : `cd ~/pythonanywhere && git fetch origin && git pull --ff-only && cd odoo-pythonanywhere && python3.10 -m pip install --user -r requirements.txt` puis **Reload** Web.  
2. **Bloc manuel `scp` + `ssh`** (même principe que dans le script) — voir plus bas.  
3. **MCP Cursor** `execute_command` (SSH) avec la même commande bash ; `privateKeyPath` = clé sans passphrase, ex. `%USERPROFILE%\.ssh\id_ed25519_pa_cursor`.  
4. **Contournement PC** : enregistrer `deploy_pa.ps1` en **UTF-8 avec BOM**, ou copier le script sur un disque local (ex. `C:\temp`) et l’exécuter depuis là.

**Option A — Git (recommandé)**  
Depuis `odoo-pythonanywhere/` : **`.\deploy_pa.ps1`**. Pour ne pas pousser depuis la machine locale : **`.\deploy_pa.ps1 -SkipGitPush`** (à utiliser seulement si le push a déjà été fait ailleurs).

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
- [ ] Déploiement : **`deploy_pa.ps1`** depuis `odoo-pythonanywhere/` **ou**, si le `.ps1` casse (ParserError), **`git pull` sur PA** / **scp+ssh** / **MCP SSH** (voir section « Si deploy_pa.ps1 plante »)
- [ ] `requirements.txt` réinstallé avec la **bonne** version Python du web app
- [ ] `toolbox_users.json` et `toolbox_clients.json` toujours présents sur le serveur
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

- **Deux modes** (voir **`web_app/odoo_account_probe.py`**) :
  - **Sans URL** : session HTTP sur **www.odoo.com** (login + mot de passe + CSRF), page **Mes bases**, extraction des liens `https://*.odoo.com`, déduction du nom de base PostgreSQL depuis l’hôte, puis **XML-RPC** `authenticate` / `object` sur chaque instance.
  - **Avec URL** : `db.list()` sur cette instance si le service `db` existe ; sinon liste vide et message via **`format_db_list_error`** / **`_is_odoo_db_service_disabled`** (dont `KeyError: 'db'` / `repr(Fault)` avec `\'db\'`).
- Variables optionnelles : **`TOOLBOX_ODOO_PORTAL_ORIGIN`**, **`TOOLBOX_ODOO_PORTAL_LANG`** (défaut `https://www.odoo.com`, `/fr_FR`) — voir **`toolbox-env-exemple.txt`**.
- **Login** et **mot de passe** : champs masqués ; mot de passe non réinjecté dans le HTML après POST.
- Version / date affichées : **`app_version.TOOLBOX_APP_VERSION`** / **`TOOLBOX_APP_DATE`**, injectées par **`web_app/blueprints/staff.py`** (`util_version`, `util_date`).

### Utilitaire « Rapports comptables Odoo » (personnalisation / exports)

- Fichier principal : **`web_app/odoo_account_reports.py`**. Les métadonnées **version**, **date** et **auteur** viennent de la même source que le reste de la toolbox : **`web_app/app_version.py`** (`TOOLBOX_APP_VERSION`, `TOOLBOX_APP_DATE`, `TOOLBOX_APP_AUTHOR` — ce dernier surchargeable via env `TOOLBOX_APP_AUTHOR`, voir **`toolbox-env-exemple.txt`**).

### Pistes « demain » possibles

- Fragilité du **parsing HTML** du portail si Odoo change la page Mes bases ; instances hors `*.odoo.com` non détectées par ce mode.
- Vérifier sur PA que le **venv / version Python** de l’onglet Web correspond à celle utilisée pour `pip` dans `deploy_pa.sh` (`PYTHONANYWHERE_PYTHON` si besoin).

---

*Dernière mise à jour de cette section : 4 avril 2026 — sonde bases (version via `app_version`), rapports comptables alignés sur `app_version`, piège `deploy_pa.ps1` / encodage PowerShell sur Mon Drive, rappel Reload Web après `git pull`.*

## Générer un hash mot de passe (utilisateurs toolbox)

```bash
python toolbox_generate_password_hash.py
```

Coller le résultat dans `toolbox_users.json` (`password_hash`).

---

*Intention globale : toolbox Flask unifiée (portails client / staff Senedoo, admin clients & comptes, utilitaires Odoo), registre multi-bases, auth par fichiers JSON.*
