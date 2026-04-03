"""Client Odoo minimal via XML-RPC (stdlib, compatible PythonAnywhere)."""
from __future__ import annotations

import xmlrpc.client
from typing import Any


class OdooClient:
    def __init__(self, url: str, db: str, username: str, password: str) -> None:
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self._object = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)
        self.uid: int | None = None

    def authenticate(self) -> int:
        uid = self._common.authenticate(self.db, self.username, self.password, {})
        if not uid:
            raise RuntimeError("Échec d'authentification Odoo (identifiants ou base incorrects).")
        self.uid = int(uid)
        return self.uid

    def version(self) -> dict[str, Any]:
        return self._common.version()

    def execute(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        if self.uid is None:
            self.authenticate()
        kw = kwargs or {}
        return self._object.execute_kw(
            self.db,
            self.uid,
            self.password,
            model,
            method,
            args,
            kw,
        )
