#!/usr/bin/env python3
"""
Réécrit toolbox_clients.json : id et label = nom de base normalisé (clé unique).
Met à jour les client_id des utilisateurs (toolbox_users.json) si fourni.

Usage :
  cd odoo-pythonanywhere
  python scripts/migrate_registry_db_ids.py --clients chemin/toolbox_clients.json
  python scripts/migrate_registry_db_ids.py --clients ... --users chemin/toolbox_users.json

Dry-run (aucune écriture) :
  python scripts/migrate_registry_db_ids.py --clients ... --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from web_app.odoo_registry import migrate_registry_ids_to_database_names  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Migration registre : id = nom de base (db).")
    p.add_argument("--clients", required=True, type=Path, help="Fichier toolbox_clients.json")
    p.add_argument("--users", type=Path, help="Fichier toolbox_users.json (optionnel)")
    p.add_argument("--dry-run", action="store_true", help="Afficher la map sans écrire")
    args = p.parse_args()
    cp = args.clients
    if not cp.is_file():
        print(f"Fichier clients introuvable : {cp}", file=sys.stderr)
        return 1
    if args.dry_run:
        from web_app.odoo_registry import read_clients_raw, normalize_registry_db_key

        data = read_clients_raw(cp)
        mapping: dict[str, str] = {}
        seen: set[str] = set()
        for row in data.get("clients", []):
            try:
                db_key = normalize_registry_db_key(str(row.get("db", "")).strip())
            except ValueError as e:
                print(f"Ligne ignorée : {e}", file=sys.stderr)
                continue
            old_id = str(row.get("id", db_key)).strip().lower()
            if old_id != db_key:
                mapping[old_id] = db_key
            if db_key in seen:
                print(f"Doublon base {db_key!r}", file=sys.stderr)
                return 1
            seen.add(db_key)
        print("Ancien id -> nouveau (db) :")
        for k, v in sorted(mapping.items()):
            print(f"  {k!r} -> {v!r}")
        if not mapping:
            print("  (aucun changement d’id nécessaire)")
        return 0
    up = args.users if args.users and args.users.is_file() else None
    m = migrate_registry_ids_to_database_names(cp, users_path=up)
    print(f"Écrit : {cp}")
    if up:
        print(f"Écrit : {up}")
    if m:
        print("Remplacements id registre -> db :")
        for k, v in sorted(m.items()):
            print(f"  {k!r} -> {v!r}")
    else:
        print("Aucun ancien id à remapper (déjà aligné ou une seule entrée).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
