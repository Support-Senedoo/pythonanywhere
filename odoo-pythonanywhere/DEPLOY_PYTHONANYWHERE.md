# Déploiement PythonAnywhere — reprise rapide

Ce fichier sert de **mémoire projet** : les assistants IA n’ont pas de souvenir des sessions passées. Tout ce qui compte pour remettre en ligne ou mettre à jour l’app doit rester **ici** (et dans le Git).

## Ce qui est déployé (état attendu)

- **Application** : Flask « toolbox » (`web_app`), WSGI = **`pythonanywhere_wsgi.py`** ou **`pa_wsgi.py`** (équivalent).
- **Portails** : accueil `/` (client / Senedoo), login, espace client sous `/client/`, staff sous `/staff/`, utilitaire personnalisation rapport sous `/staff/utilities/personalize-report`.
- **Secrets sur le serveur uniquement** (jamais dans Git) :
  - `toolbox_users.json` — comptes + `password_hash` (Werkzeug)
  - `toolbox_clients.json` — URL / base / user API Odoo par `client_id`
  - Variable **`TOOLBOX_SECRET_KEY`** (onglet Web PythonAnywhere)

Modèles : `toolbox_users.example.json`, `toolbox_clients.example.json`, `toolbox-env-exemple.txt`.

## Sur PythonAnywhere — référence projet (validé)

| Élément | Valeur |
|--------|--------|
| Utilisateur PA | `senedoo` |
| SSH (Bash / terminal) | `ssh senedoo@ssh.pythonanywhere.com` |
| Répertoire projet | `/home/senedoo/odoo-pythonanywhere` |
| Fichier WSGI (onglet Web) | `/home/senedoo/odoo-pythonanywhere/pythonanywhere_wsgi.py` |
| Commande `pip` | adapter à la **même** version Python que le site web (ex. `pip3.10 install --user -r requirements.txt`) |
| URL publique du site | `https://senedoo.pythonanywhere.com/` |

*Dernière vérification manuelle : avril 2026 (SSH + MCP opérationnels).*

## Déploiement / mise à jour du code

**Option A — Git (recommandé)**  
Si le dépôt est cloné sur PA : `git pull` dans le dossier du projet, puis `pip install …`, puis **Reload** du site web.

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

- [ ] Dépôt à jour sur PA (`git pull` ou upload)
- [ ] `requirements.txt` réinstallé avec la **bonne** version Python du web app
- [ ] `toolbox_users.json` et `toolbox_clients.json` toujours présents sur le serveur
- [ ] `TOOLBOX_SECRET_KEY` toujours défini dans l’onglet Web
- [ ] WSGI pointe toujours vers `pythonanywhere_wsgi.py` (ou `pa_wsgi.py`)
- [ ] **Reload** du site

## Générer un hash mot de passe (utilisateurs toolbox)

```bash
python toolbox_generate_password_hash.py
```

Coller le résultat dans `toolbox_users.json` (`password_hash`).

---

*Dernière intention documentée : toolbox Flask unifiée (client La Ripaille + staff Senedoo + personnalisation rapport), registre multi-bases, auth par fichier JSON.*
