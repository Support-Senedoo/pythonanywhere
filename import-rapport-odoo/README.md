# Rapport comptable Odoo — export / import (API)

## En une commande (recommandé)

Ouvrez un terminal **dans ce dossier** `import-rapport-odoo` et lancez :

```text
python menu_rapport.py
```

### Option 1 — Préparer pour une autre base (base **source**)

1. Indiquez l’URL, le **nom de la base**, le login et le mot de passe.
2. Le script liste d’abord les rapports dont le nom **commence par « Compte »** en **français** (lecture avec la langue `fr_FR`). Si Odoo n’a que des libellés anglais en base, une **liste élargie** (SYSCOHADA, résultat, Profit and Loss…) est proposée.
3. Une **copie** du rapport est toujours créée : l’original n’est pas modifié. Vous donnez un nom à cette copie.
4. Vous pouvez appliquer la **personnalisation Senedoo** (détail par compte) sur cette copie.
5. Un fichier **JSON** est enregistré dans **`exports/`** (nom avec date et id du rapport copié).

Vous n’avez **pas** à placer le JSON à la main : il est créé au bon endroit.

### Option 2 — Importer dans la base **cible**

1. Même écran : choisissez **2**.
2. Connexion à la base cible (dont le **nom de la base**).
3. Le script affiche une **liste numérotée** de fichiers `.json` : tapez le **numéro** (1, 2, …) pour en choisir un, **ou** le **chemin complet** d’un fichier qui n’est pas dans la liste (autre dossier, clé USB, etc.).
4. Le rapport est recréé dans la base cible.

## Scripts séparés (avancé)

| Fichier | Usage |
|--------|--------|
| `lancer_import.py` | Import seul, avec chemin vers un `.json`. |
| `lancer_export.py` | Export seul si vous connaissez déjà l’id du rapport. |

Le moteur technique est dans `../odoo-pythonanywhere/account_report_portable.py`.

## Prérequis

- Python 3.
- Dans ce dossier : `pip install -r requirements.txt`  
  (installe `python-dotenv` et `colorama` pour couleurs et cadres dans le terminal ; sans `colorama`, l’affichage reste lisible en noir et blanc).
- Fichier optionnel `.env` (voir `env-exemple.txt`) pour préremplir URL / utilisateur / mot de passe ; le **nom de la base** reste demandé (souvent différent entre source et cible).

## Sécurité

Ne commitez pas `.env` ni des exports JSON sensibles (déjà ignorés par `.gitignore`).
