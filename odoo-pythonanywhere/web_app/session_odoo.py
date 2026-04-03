"""Résolution Odoo selon session (client fixe ; staff selon contexte)."""
from __future__ import annotations

from typing import Any

from flask import current_app, session

from odoo_client import OdooClient

from web_app.odoo_registry import ClientOdooConfig, connect_xmlrpc, load_clients_registry


def _registry() -> dict[str, ClientOdooConfig]:
    return load_clients_registry(current_app.config["TOOLBOX_CLIENTS_PATH"])


def get_config_for_client_session() -> ClientOdooConfig:
    """Compte connecté type client : une seule base (session client_id)."""
    if session.get("role") != "client":
        raise PermissionError("Rôle client requis.")
    cid = session.get("client_id")
    if not cid:
        raise RuntimeError("Session client sans client_id.")
    reg = _registry()
    if cid not in reg:
        raise RuntimeError(f"Client inconnu dans le registre : {cid}")
    return reg[cid]


def get_odoo_client_for_browser_client() -> OdooClient:
    cfg = get_config_for_client_session()
    return OdooClient(cfg.url, cfg.db, cfg.user, cfg.password)


def get_config_by_id(client_id: str) -> ClientOdooConfig:
    reg = _registry()
    if client_id not in reg:
        raise ValueError(f"client_id inconnu : {client_id}")
    return reg[client_id]


def get_xmlrpc_for_staff_client_id(client_id: str) -> tuple[Any, str, int, str]:
    """Pour staff : base choisie explicitement (registre)."""
    if session.get("role") != "staff":
        raise PermissionError("Rôle staff requis.")
    cfg = get_config_by_id(client_id)
    return connect_xmlrpc(cfg)
