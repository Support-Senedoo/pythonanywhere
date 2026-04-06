"""Lecture d’informations instance Odoo (version publique + paramètres après authentification)."""
from __future__ import annotations

from typing import Any

import xmlrpc.client

from odoo_client import normalize_odoo_base_url
from personalize_syscohada_detail import execute_kw


def format_server_version_info(info: Any) -> str | None:
    """
    Normalise le tuple ``server_version_info`` renvoyé par ``common.version()`` (ex. ``(19, 0, 1, 0)``).

    Sur Odoo SaaS / récent, c’est souvent la forme la plus stable pour comparer les instances.
    """
    if info is None:
        return None
    if isinstance(info, (list, tuple)) and info:
        parts: list[str] = []
        for x in info[:6]:
            if isinstance(x, bool):
                parts.append("1" if x else "0")
            elif x is None:
                continue
            else:
                parts.append(str(x))
        return ".".join(parts) if parts else None
    return str(info)


def read_public_server_version(base_url: str) -> dict[str, Any]:
    """Appelle xmlrpc/2/common.version() sans authentification (disponible sur la plupart des instances)."""
    try:
        u = normalize_odoo_base_url(base_url).rstrip("/") + "/xmlrpc/2/common"
        common = xmlrpc.client.ServerProxy(u, allow_none=True)
        v = common.version()
        return v if isinstance(v, dict) else {"raw": v}
    except Exception as e:
        return {"_xmlrpc_error": str(e)}


def _get_param(models: Any, db: str, uid: int, password: str, key: str) -> Any:
    try:
        return execute_kw(models, db, uid, password, "ir.config_parameter", "get_param", [key])
    except Exception:
        return None


def collect_authenticated_instance_metadata(
    models: Any,
    db: str,
    uid: int,
    password: str,
    base_url: str,
) -> list[tuple[str, str]]:
    """Paires (libellé, valeur) pour affichage ; champs absents ou vides omis."""
    rows: list[tuple[str, str]] = []
    pub = read_public_server_version(base_url)
    if pub.get("_xmlrpc_error"):
        rows.append(("Version publique (common)", f"— {pub['_xmlrpc_error']}"))
    else:
        if pub.get("server_version"):
            rows.append(("Version annoncée par le serveur (common.version)", str(pub["server_version"])))
        svi = pub.get("server_version_info")
        if svi is not None:
            rows.append(("server_version_info (brut)", str(svi)))
            svi_fmt = format_server_version_info(svi)
            if svi_fmt:
                rows.append(("Version dérivée de server_version_info", svi_fmt))
        serie = pub.get("server_serie") or pub.get("series")
        if serie:
            rows.append(("Série Odoo", str(serie)))

    param_map = [
        ("database.uuid", "UUID base"),
        ("database.expiration_date", "Date limite / expiration"),
        ("database.expiration_reason", "Motif (expiration / abonnement)"),
        ("database.enterprise_code", "Code entreprise"),
        ("database.is_neutralized", "Base neutralisée"),
        ("web.base.url", "URL configurée (web.base.url)"),
    ]
    for k, label in param_map:
        v = _get_param(models, db, uid, password, k)
        if v not in (None, False, ""):
            rows.append((label, str(v)))

    try:
        ent_ids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "search",
            [[("name", "=", "web_enterprise"), ("state", "=", "installed")]],
            {"limit": 1},
        )
        ent = bool(ent_ids)
        rows.append(
            (
                "Type / édition",
                "Enterprise (web_enterprise installé)" if ent else "Community (sans web_enterprise)",
            )
        )
        if ent_ids:
            wer = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.module.module",
                "read",
                [ent_ids],
                {"fields": ["latest_version", "published_version"]},
            )
            if wer:
                w = wer[0]
                if w.get("latest_version"):
                    rows.append(
                        (
                            "Module web_enterprise — version installée (DB)",
                            str(w["latest_version"]),
                        )
                    )
                if w.get("published_version"):
                    rows.append(
                        (
                            "Module web_enterprise — published_version",
                            str(w["published_version"]),
                        )
                    )
    except Exception as e:
        rows.append(("Type / édition", f"— {e}"))

    try:
        cids = execute_kw(models, db, uid, password, "res.company", "search", [[]], {"limit": 1})
        if cids:
            c = execute_kw(
                models,
                db,
                uid,
                password,
                "res.company",
                "read",
                [cids],
                {"fields": ["name"]},
            )
            if c and c[0].get("name"):
                rows.append(("Société principale", str(c[0]["name"])))
    except Exception:
        pass

    # Version « métier » de la base : ir.module.module sur base (latest_version = installée en DB, Odoo 19).
    try:
        mod_fields = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "fields_get",
            [],
            {"attributes": ["type"]},
        )
        base_read_fields = ["latest_version", "published_version"]
        if isinstance(mod_fields, dict) and "installed_version" in mod_fields:
            base_read_fields.append("installed_version")
        bids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.module.module",
            "search",
            [[("name", "=", "base"), ("state", "=", "installed")]],
            {"limit": 1},
        )
        if bids:
            br = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.module.module",
                "read",
                [bids],
                {"fields": base_read_fields},
            )
            if br:
                b0 = br[0]
                if b0.get("latest_version"):
                    rows.append(
                        (
                            "Version Odoo (module base, installée en base)",
                            str(b0["latest_version"]),
                        )
                    )
                if b0.get("published_version"):
                    rows.append(
                        (
                            "Module base — published_version (dépôt / SaaS)",
                            str(b0["published_version"]),
                        )
                    )
                if b0.get("installed_version"):
                    rows.append(
                        (
                            "Module base — installed_version (réf. disque / calcul Odoo)",
                            str(b0["installed_version"]),
                        )
                    )
    except Exception:
        pass

    rows.append(("Nom technique PostgreSQL (db)", db))
    rows.append(("URL instance", normalize_odoo_base_url(base_url)))
    return rows


def parse_odoo_major_version(pub: dict[str, Any] | None) -> int | None:
    """
    Extrait la série majeure (16, 17, 18, 19…) depuis le dict renvoyé par ``common.version()``
    (champs ``server_version_info`` ou ``server_version``).
    """
    if not pub or not isinstance(pub, dict):
        return None
    svi = pub.get("server_version_info")
    if isinstance(svi, (list, tuple)) and len(svi) > 0:
        m = svi[0]
        if isinstance(m, int):
            return m
        try:
            return int(m)
        except (TypeError, ValueError):
            pass
    sv = pub.get("server_version")
    if isinstance(sv, str):
        s = sv.strip()
        if s and s[0].isdigit():
            i = 0
            while i < len(s) and s[i].isdigit():
                i += 1
            try:
                return int(s[:i])
            except ValueError:
                pass
    return None


def is_enterprise_from_instance_rows(rows: list[tuple[str, str]]) -> bool | None:
    """Déduit Enterprise vs Community à partir des lignes ``collect_authenticated_instance_metadata``."""
    for label, val in rows:
        if "édition" in label.lower():
            v = val.lower()
            if "enterprise" in v:
                return True
            if "community" in v:
                return False
    return None


def build_balance_ohada_import_guide(
    *,
    major: int | None,
    version_label: str,
    is_enterprise: bool | None,
) -> dict[str, Any]:
    """
    Textes pour l’écran Balance OHADA — import manuel XML / module ZIP, selon version et édition.

    Retour : clés utilisées par le template Jinja (alert, points, hints).
    """
    vl = (version_label or "").strip() or "—"
    points: list[str] = []
    alert = "neutral"
    if major is None:
        alert = "warning"
        points.append(
            "Version Odoo non détectée : dans Odoo, ouvrez le menu du compte / À propos "
            "ou Paramètres → À propos, et vérifiez que vous êtes en série 17 ou plus pour le "
            "moteur d’expressions utilisé par le gabarit (aggregation + colonnes ohada6_*)."
        )
    elif major < 16:
        alert = "warning"
        points.append(
            f"Série majeure détectée : {major}. Les rapports configurables et les champs "
            f"`account.report.expression` peuvent différer : testez sur une copie de base ou "
            "montez de version avant de compter sur l’import tel quel."
        )
    elif major < 19:
        alert = "success"
        points.append(
            f"Série {major} (Odoo 16–18) : le bouton « Créer Balance OHADA » suffit — la toolbox "
            "crée le rapport uniquement par API, avec l’ancienne voie « domain » (stable sur ces "
            "versions). Aucun import XML n’est nécessaire pour une création standard."
        )
    else:
        alert = "success"
        points.append(
            f"Série {major} (Odoo 19+) : création par API avec priorité au moteur « aggregation » "
            "(repli « domain » automatique si besoin). Les fichiers XML / ZIP ci-dessous restent des "
            "secours (Studio, module, autre base)."
        )

    if is_enterprise is True:
        points.append(
            "Enterprise : le module dépend de « account_reports » (rapports comptables). "
            "Vous pouvez installer le ZIP sur un serveur avec accès aux addons, ou importer "
            "le fichier XML via Studio (Import XML) si vous avez les droits."
        )
        studio_hint = (
            "Activer le mode développeur, puis Studio → import XML (libellé exact selon la langue), "
            "ou ouvrir un formulaire Comptabilité et utiliser l’entrée Studio associée."
        )
        zip_hint = (
            "Applications → mode développeur → Importer un module : déposer sn_balance_ohada_6cols.zip "
            "(dossier décompressé = nom technique sn_balance_ohada_6cols dans le chemin addons)."
        )
    elif is_enterprise is False:
        alert = "warning" if alert != "warning" else alert
        points.append(
            "Community : le module « account_reports » est souvent absent — l’installation du ZIP "
            "peut échouer. Privilégiez la création du rapport via le bouton API ci-dessus, ou un "
            "hébergement Odoo avec rapports financiers complets."
        )
        studio_hint = (
            "Si le module Studio est installé, l’import XML peut quand même créer des enregistrements "
            "partiels ; en cas d’erreur sur account.report, l’API reste l’option la plus fiable."
        )
        zip_hint = (
            "ZIP réservé aux serveurs où « account_reports » est disponible et installable "
            "(souvent Enterprise ou build équivalent)."
        )
    else:
        studio_hint = (
            "Mode développeur → Studio → Import XML du fichier .example.xml, ou import du ZIP "
            "via Applications si votre serveur expose les modules comptables."
        )
        zip_hint = (
            "Si vous ne savez pas si vous êtes en Enterprise : dans Odoo, cherchez "
            "« Rapports comptables » / balance générale configurable ; sans cela, utilisez surtout l’API."
        )

    xml_hint = (
        "Fichier balance_generale_6_col_studio.example.xml : même contenu fonctionnel que le module "
        "(préfixe ohada6_*). En cas d’échec d’import monolithique, importer en deux temps : colonnes puis ligne."
    )

    summary = f"Odoo {vl}"
    if major is not None:
        summary += f" · série {major}"
    if is_enterprise is True:
        summary += " · Enterprise"
    elif is_enterprise is False:
        summary += " · Community"

    return {
        "major": major,
        "version_label": vl,
        "is_enterprise": is_enterprise,
        "alert": alert,
        "summary_line": summary,
        "points": points,
        "studio_hint": studio_hint,
        "zip_hint": zip_hint,
        "xml_hint": xml_hint,
    }
