"""Client Odoo minimal via XML-RPC (stdlib, compatible PythonAnywhere)."""
from __future__ import annotations

import xmlrpc.client
from typing import Any
from urllib.parse import urlparse, urlunparse


def normalize_odoo_base_url(raw: str) -> str:
    """
    Évite les 301 « Moved Permanently » sur XML-RPC (ServerProxy ne les suit pas toujours) :
    - https://odoo.com → https://www.odoo.com
    - http://*.odoo.com → https://… (hébergement SaaS)
    - schéma absent → https://
    """
    s = (raw or "").strip().rstrip("/")
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s.lstrip("/")
    p = urlparse(s)
    host = (p.hostname or "").lower()
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc

    if host == "odoo.com":
        port = p.port
        if port and port not in (80, 443):
            netloc = f"www.odoo.com:{port}"
        else:
            netloc = "www.odoo.com"

    if host == "odoo.com" or host.endswith(".odoo.com"):
        if scheme == "http":
            scheme = "https"
            if netloc.endswith(":80"):
                netloc = netloc[:-3]

    out = urlunparse((scheme, netloc, p.path or "", "", "", ""))
    return out.rstrip("/")


class OdooClient:
    def __init__(self, url: str, db: str, username: str, password: str) -> None:
        self.url = normalize_odoo_base_url(url).rstrip("/")
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
