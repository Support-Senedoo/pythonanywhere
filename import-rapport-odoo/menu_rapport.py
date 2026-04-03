#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Assistant : connexion Odoo, liste des rapports dont le nom commence par « Compte »,
duplication du modèle choisi, suppression optionnelle d’un rapport de la liste,
personnalisation Senedoo optionnelle, export JSON — ou import ailleurs.

  python menu_rapport.py
"""
from __future__ import annotations

import getpass
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_PA = _ROOT / "odoo-pythonanywhere"
if str(_PA) not in sys.path:
    sys.path.insert(0, str(_PA))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv(_PA / ".env")
except ImportError:
    pass

from account_report_portable import (  # noqa: E402
    apply_report_name_translations,
    cmd_export,
    cmd_import,
    connect,
    execute_kw,
)
from console_ui import (  # noqa: E402
    ask,
    banner,
    error,
    info_lines,
    menu,
    muted,
    section,
    success,
    table_reports,
    warn,
)
from personalize_syscohada_detail import personalize_fix_detail_complete  # noqa: E402

_HERE = Path(__file__).resolve().parent
_EXPORTS = _HERE / "exports"
_EXPORTS.mkdir(exist_ok=True)


def _credentials() -> tuple[str, str, str, str]:
    section("Connexion à Odoo")
    info_lines(
        "Indiquez l’URL de votre instance (ex. https://mon-entreprise.odoo.com).\n"
        "Le nom de la base est celui affiché sur l’écran de connexion (souvent proche du sous-domaine)."
    )
    print()

    default_url = os.environ.get("ODOO_URL", "").strip() or "https://votre-instance.odoo.com"
    url = ask("URL (sans / à la fin)", default_url)

    default_db = os.environ.get("ODOO_DB", "").strip()
    db = ask("Nom exact de la base de données", default_db or "")
    if not db:
        error("Le nom de la base est obligatoire.")
        sys.exit(1)

    default_user = os.environ.get("ODOO_USER", "").strip()
    user = ask("Identifiant (e-mail)", default_user or "")

    pw_env = os.environ.get("ODOO_PASSWORD", "").strip()
    if pw_env:
        u = ask("Utiliser le mot de passe enregistré dans .env ?", "O")
        password = pw_env if u.lower() != "n" else getpass.getpass("  Mot de passe ou clé API (saisie masquée) : ")
    else:
        muted("Saisie du mot de passe masquée (rien ne s’affiche pendant la frappe).")
        password = getpass.getpass("  Mot de passe ou clé API Odoo : ")
    if not password:
        error("Mot de passe vide.")
        sys.exit(1)

    return url, db, user, password


def _slugify_for_filename(name: str, max_len: int = 90) -> str:
    """Segment de nom de fichier sûr sous Windows (caractères réservés retirés)."""
    s = (name or "").strip()
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._")
    if not s:
        return "rapport"
    return s[:max_len]


def _report_display_name(name: Any) -> str:
    if isinstance(name, dict):
        return str(
            name.get("fr_FR")
            or name.get("fr_BE")
            or name.get("en_US")
            or (next(iter(name.values())) if name else "")
        )
    return str(name or "")


def _search_reports_starting_compte(models: Any, db: str, uid: int, password: str) -> tuple[list[dict], bool]:
    ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [[("active", "=", True)]],
        {"order": "name", "limit": 500},
    )
    if not ids:
        return [], False

    def _read_lang(lang: str) -> list[dict]:
        return execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "read",
            [ids],
            {"fields": ["id", "name", "chart_template"], "context": {"lang": lang}},
        )

    filtered: list[dict] = []
    for lang in ("fr_FR", "fr_BE"):
        recs = _read_lang(lang)
        filtered = [r for r in recs if _report_display_name(r.get("name")).startswith("Compte")]
        if filtered:
            return filtered, False

    recs = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [ids],
        {"fields": ["id", "name", "chart_template"]},
    )
    filtered = [r for r in recs if _report_display_name(r.get("name")).startswith("Compte")]
    if filtered:
        return filtered, False

    domain = [
        "&",
        ("active", "=", True),
        "|",
        "|",
        "|",
        "|",
        ("name", "ilike", "SYSCOHADA"),
        ("name", "ilike", "résultat"),
        ("name", "ilike", "resultat"),
        ("name", "ilike", "Profit and Loss"),
        ("name", "ilike", "Compte"),
    ]
    ids2 = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [domain],
        {"order": "name", "limit": 100},
    )
    if not ids2:
        return [], False
    recs2 = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [ids2],
        {"fields": ["id", "name", "chart_template"], "context": {"lang": "fr_FR"}},
    )
    return recs2, True


def _delete_report_from_list(
    models: Any,
    db: str,
    uid: int,
    password: str,
    reports: list[dict],
) -> bool:
    """
    Demande un numéro, confirmation, puis unlink sur account.report.
    Retourne True si une suppression a réussi (rafraîchir la liste côté appelant).
    """
    s = ask("Numéro du rapport à supprimer définitivement (Entrée = annuler)", "").strip()
    if not s:
        muted("Suppression annulée.")
        return False
    try:
        n = int(s)
    except ValueError:
        warn("Numéro invalide.")
        return False
    if not (1 <= n <= len(reports)):
        warn("Numéro hors liste.")
        return False
    rep = reports[n - 1]
    rid = int(rep["id"])
    label = _report_display_name(rep.get("name"))
    info_lines(f"Identifiant interne : {rid}\nLibellé : {label}")
    warn(
        "Les rapports livrés avec Odoo peuvent être protégés contre la suppression. "
        "Les copies et rapports personnalisés sont en général supprimables."
    )
    c = ask("Pour confirmer, tapez exactement : SUPPRIMER", "")
    if c != "SUPPRIMER":
        warn("Suppression annulée.")
        return False
    try:
        execute_kw(models, db, uid, password, "account.report", "unlink", [[rid]])
    except Exception as exc:
        error(f"Suppression impossible : {exc}")
        return False
    success(f"Rapport supprimé (id={rid}).")
    return True


def _pick_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    reports: list[dict],
) -> dict | None:
    """
    Affiche la liste et demande un numéro pour dupliquer, ou « s » pour supprimer.
    Retourne None si un rapport a été supprimé (recharger la liste puis rappeler).
    """
    rows: list[tuple[int, int, str, str]] = []
    for i, r in enumerate(reports, 1):
        label = _report_display_name(r.get("name"))
        ct = str(r.get("chart_template") or "")
        rows.append((i, int(r["id"]), label, ct))
    table_reports(rows)
    info_lines(
        "Indiquez le numéro du modèle à dupliquer, ou la lettre « s » pour supprimer "
        "un rapport de cette liste (puis suivez les instructions)."
    )

    while True:
        s = ask("Numéro à dupliquer ou s pour supprimer", "").strip()
        if s.lower() in ("s", "supprimer"):
            if _delete_report_from_list(models, db, uid, password, reports):
                return None
            continue
        try:
            n = int(s)
            if 1 <= n <= len(reports):
                return reports[n - 1]
        except ValueError:
            pass
        warn("Choix invalide : un numéro de la liste, ou s pour supprimer.")


def flow_prepare() -> None:
    section("Étape 1 — Préparer un export (base source)")
    url, db, user, password = _credentials()

    muted("Connexion en cours…")
    models, uid = connect(url, db, user, password)
    success(f"Connecté à « {db} » (utilisateur uid={uid}).")

    reports, liste_elargie = _search_reports_starting_compte(models, db, uid, password)
    if not reports:
        warn(
            "Aucun rapport adapté trouvé. Vérifiez vos droits "
            "(Comptabilité → Configuration → Rapports comptables)."
        )
        sys.exit(1)

    section("Choix du modèle de rapport")
    if liste_elargie:
        info_lines(
            "Aucun nom ne commence par « Compte » en français dans la base "
            "(souvent les libellés sont en anglais : Profit and Loss, etc.).\n"
            "Liste élargie : sélectionnez votre compte de résultat, par ex. … (SYSCOHADA)."
        )
    else:
        info_lines(
            "Rapports dont le libellé français commence par « Compte ». "
            "L’original ne sera pas modifié : une copie sera créée."
        )
    print()

    while True:
        rep = _pick_report(models, db, uid, password, reports)
        if rep is not None:
            break
        reports, liste_elargie = _search_reports_starting_compte(models, db, uid, password)
        if not reports:
            warn("Aucun rapport restant dans la liste.")
            sys.exit(1)
        section("Liste des rapports (mise à jour)")
        print()

    src_id = rep["id"]
    src_label = _report_display_name(rep.get("name"))

    section("Nom de la copie")
    info_lines(
        "Une copie du rapport est créée dans Odoo. Donnez-lui un titre "
        "(visible sous Comptabilité → Rapports comptables)."
    )
    default_name = f"{src_label} — copie Senedoo {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    nm = ask("Nom affiché de la copie", default_name)

    muted("Duplication en cours…")
    new_id = execute_kw(models, db, uid, password, "account.report", "copy", [src_id], {})
    if isinstance(new_id, (list, tuple)):
        new_id = new_id[0]
    rid = int(new_id)
    nm = (nm or "").strip() or default_name
    apply_report_name_translations(models, db, uid, password, rid, nm, nm)
    success(f"Copie créée sous l’identifiant interne id={rid}.")

    section("Personnalisation (optionnel)")
    pers = ask(
        "Appliquer la personnalisation Senedoo (détail par compte, rubriques repliables) ?", "o"
    )
    if pers.lower() != "n":
        muted("Personnalisation en cours (cela peut prendre une minute)…")
        personalize_fix_detail_complete(models, db, uid, password, rid)
        apply_report_name_translations(models, db, uid, password, rid, nm, nm)
        success("Personnalisation appliquée.")
    else:
        muted("Personnalisation ignorée — vous pourrez l’ajuster plus tard dans Odoo.")

    rep_fr = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[rid]],
        {"fields": ["name"], "context": {"lang": "fr_FR"}},
    )[0]
    label_fr = _report_display_name(rep_fr.get("name"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify_for_filename(label_fr)
    out = _EXPORTS / f"{slug}_{rid}_{ts}.json"
    section("Export du fichier JSON")
    info_lines(f"Enregistrement du fichier :\n{out}")
    cmd_export(models, db, uid, password, rid, out)
    success("Export terminé.")
    info_lines(
        "Pour charger ce rapport sur une autre base : relancez ce script, option « Importer », "
        f"ou copiez le fichier depuis le dossier exports/."
    )
    print()


def flow_import() -> None:
    section("Importer dans une base cible")
    url, db, user, password = _credentials()

    files = sorted(_EXPORTS.glob("*.json")) + sorted(_HERE.glob("*.json"))
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in files:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(p)

    section("Fichier à importer")

    if unique:
        print()
        for i, p in enumerate(unique, 1):
            print(f"  {i:3}  {p}")
        print()
        info_lines(
            "Tapez le numéro d’une ligne ci-dessus, ou le chemin complet d’un fichier .json "
            "(clé USB, autre dossier, etc.)."
        )
    else:
        info_lines(
            "Aucun .json dans ce dossier. Indiquez le chemin complet vers votre fichier "
            "(créé par l’option « Préparer » ou copié depuis ailleurs)."
        )

    default_hint = "1" if len(unique) == 1 else ""
    path_s = ask("Numéro ou chemin du fichier .json", default_hint)
    if not path_s and default_hint:
        path_s = default_hint

    if not path_s:
        error("Indiquez un numéro ou un chemin.")
        sys.exit(1)

    json_path: Path
    if path_s.isdigit() and unique:
        idx = int(path_s)
        if 1 <= idx <= len(unique):
            json_path = unique[idx - 1]
        else:
            error(f"Numéro invalide : utilisez 1 à {len(unique)}, ou un chemin complet.")
            sys.exit(1)
    else:
        json_path = Path(path_s)

    if not json_path.is_file():
        error(f"Fichier introuvable : {json_path}")
        sys.exit(1)

    new_name = ask("Nom du rapport sur la base cible (Entrée = contenu du fichier)", "") or None

    muted("Connexion et import…")
    models, uid = connect(url, db, user, password)
    success(f"Connecté à « {db} » (uid={uid}).")
    cmd_import(models, db, uid, password, json_path, new_name)
    success("Import terminé.")
    info_lines("Retrouvez le rapport sous : Comptabilité → Configuration → Rapports comptables.")
    print()


def main() -> None:
    banner(
        "Rapport comptable Odoo",
        "Export / import via l’API (copie, personnalisation Senedoo, fichier JSON)",
    )
    menu(
        [
            ("1", "Préparer — liste des rapports, option suppression, copie, export .json"),
            ("2", "Importer — recréer un rapport à partir d’un .json sur une autre base"),
            ("q", "Quitter"),
        ]
    )
    c = ask("Votre choix", "1")
    if c.lower() == "q":
        muted("À bientôt.")
        return
    if c == "2":
        flow_import()
    else:
        flow_prepare()


if __name__ == "__main__":
    main()
