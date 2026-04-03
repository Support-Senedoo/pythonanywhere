#!/usr/bin/env python3
"""Génère une ligne password_hash pour toolbox_users.json (Werkzeug)."""
from __future__ import annotations

import getpass
import sys

from werkzeug.security import generate_password_hash


def main() -> None:
    if len(sys.argv) >= 2:
        plain = sys.argv[1]
    else:
        plain = getpass.getpass("Mot de passe à hacher : ")
    if not plain:
        print("Mot de passe vide.", file=sys.stderr)
        sys.exit(1)
    print(generate_password_hash(plain))


if __name__ == "__main__":
    main()
