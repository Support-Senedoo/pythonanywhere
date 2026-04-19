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

### 2026-04-14 — Déploiement PA après menus CPC (1. / 2.)
- **Action** : `git push origin master` puis `bash deploy_to_pa.sh -SkipGitPush` (Mac, clé `~/.ssh/id_ed25519_pa_cursor`).
- **Résultat** : OK — sur PA pull `078528e` → `5cf5e56`, reload Web API `{"status":"OK"}`.
- **Références** : commit `5cf5e56`, toolbox **1.10.1** (`app_version.py`).
- **Erreur / leçon** : une réponse avait indiqué à tort que le déploiement ne pouvait pas se faire depuis macOS ; le bon script local est **`deploy_to_pa.sh`** (équivalent de **`deploy_pa.ps1`**). Toujours vérifier dans le dépôt avant d’affirmer une contrainte d’OS.

### 2026-04-14 — Menu wizard CPC invisible (Odoo) : act_window + parent = menu rapport
- **Action** : code `create_cpc_odoo_wizard.py` — menu « 1. Assistant » via **`ir.actions.act_window`** au lieu de **`ir.actions.server`** ; alignement **`parent_id`** du menu assistant sur celui du menu « 2. Rapport ».
- **Résultat** : livré en toolbox **1.10.2** ; après **Mettre à jour Budget par projet** dans Odoo, l’entrée **1.** doit apparaître au même endroit que **2.** (juste au-dessus si séquences 8/9).
- **Leçon** : les menus **`ir.actions.server`** peuvent ne pas s’afficher dans la barre latérale selon édition / droits ; **`ir.actions.act_window`** est le pattern standard des entrées visibles.
