"""Chargement de la configuration depuis l'environnement (PythonAnywhere : variables dans le WSGI ou le fichier .env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Charge .env à la racine du projet si présent (pratique en local)
load_dotenv(Path(__file__).resolve().parent / ".env")


def _req(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Variable d'environnement manquante : {name}")
    return v


def get_odoo_settings() -> tuple[str, str, str, str]:
    """Retourne (url_base, database, user, password)."""
    url = _req("ODOO_URL").rstrip("/")
    return (
        url,
        _req("ODOO_DB"),
        _req("ODOO_USER"),
        _req("ODOO_PASSWORD"),
    )
