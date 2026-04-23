# -*- coding: utf-8 -*-
"""
Écrit un fichier texte (une ligne : ``client_id`` du registre) lorsque le staff choisit une base Odoo.

``scripts/xmlrpc_toolbox_client.py`` relit ce fichier (même chemin par défaut) pour cibler la base
sans variable d'environnement, alignée sur l'interface staff.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask


def _target_path(app: "Flask") -> Path:
    return Path(app.config["TOOLBOX_STAFF_SELECTED_CLIENT_FILE"])


def persist_staff_selected_client_for_xmlrpc(app: "Flask", client_id: str | None) -> None:
    """Écrit ``client_id`` (nom de base normalisé) si non vide."""
    cid = (client_id or "").strip().lower()
    if not cid:
        return
    path = _target_path(app)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cid + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        app.logger.exception("Impossible d'écrire TOOLBOX_STAFF_SELECTED_CLIENT_FILE (%s)", path)


def clear_staff_selected_client_file(app: "Flask") -> None:
    """Supprime le fichier (déconnexion / connexion staff)."""
    path = _target_path(app)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        app.logger.warning(
            "Impossible de supprimer le fichier base staff XML-RPC (%s)", path, exc_info=True
        )
