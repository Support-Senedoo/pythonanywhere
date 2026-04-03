"""Point d'entrée : test de connexion et lecture légère (version serveur + nombre de partenaires)."""
from __future__ import annotations

from config import get_odoo_settings
from odoo_client import OdooClient


def main() -> None:
    url, db, user, password = get_odoo_settings()
    client = OdooClient(url, db, user, password)
    ver = client.version()
    print("Serveur Odoo :", ver.get("server_version", ver))
    client.authenticate()
    n = client.execute(
        "res.partner",
        "search_count",
        [[]],
    )
    print("Nombre de partenaires (res.partner) :", n)


if __name__ == "__main__":
    main()
