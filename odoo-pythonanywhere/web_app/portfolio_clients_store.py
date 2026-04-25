"""Clients portefeuille (sociétés) — fichier JSON distinct des bases Odoo (toolbox_clients.json)."""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from web_app.odoo_registry import normalize_registry_db_key


@dataclass(frozen=True)
class PortfolioClient:
    id: str
    name: str


def normalize_portfolio_client_id(raw: str) -> str:
    """Même contraintes que le nom de base : slug stable en minuscules."""
    return normalize_registry_db_key(str(raw or "").strip())


def read_portfolio_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"clients": []}
    return json.loads(p.read_text(encoding="utf-8"))


def write_portfolio_file(path: str | Path, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(p.parent))
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(text)
        Path(tmp).replace(p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_portfolio_clients(path: str | Path) -> dict[str, PortfolioClient]:
    data = read_portfolio_file(path)
    out: dict[str, PortfolioClient] = {}
    for row in data.get("clients", []):
        if not isinstance(row, dict):
            continue
        try:
            pid = normalize_portfolio_client_id(str(row.get("id", "")))
        except ValueError:
            continue
        name = str(row.get("name", "")).strip() or pid
        out[pid] = PortfolioClient(id=pid, name=name)
    return out


def portfolio_client_exists(path: str | Path, client_id: str) -> bool:
    try:
        key = normalize_portfolio_client_id(client_id)
    except ValueError:
        return False
    return key in load_portfolio_clients(path)


def upsert_portfolio_client(path: str | Path, client_id: str, name: str) -> None:
    pid = normalize_portfolio_client_id(client_id)
    label = (name or "").strip() or pid
    data = read_portfolio_file(path)
    rows: list[dict[str, Any]] = list(data.get("clients", []))
    found: int | None = None
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        try:
            rid = normalize_portfolio_client_id(str(row.get("id", "")))
        except ValueError:
            continue
        if rid == pid:
            found = i
            break
    entry = {"id": pid, "name": label}
    if found is not None:
        rows[found] = entry
    else:
        rows.append(entry)
    data["clients"] = rows
    write_portfolio_file(path, data)


def delete_portfolio_client(path: str | Path, client_id: str) -> None:
    pid = normalize_portfolio_client_id(client_id)
    data = read_portfolio_file(path)
    before = list(data.get("clients", []))
    rows = []
    for row in before:
        if not isinstance(row, dict):
            continue
        try:
            rid = normalize_portfolio_client_id(str(row.get("id", "")))
        except ValueError:
            continue
        if rid != pid:
            rows.append(row)
    if len(rows) == len(before):
        raise ValueError("Client introuvable.")
    data["clients"] = rows
    write_portfolio_file(path, data)


def portfolio_clients_sorted(path: str | Path) -> list[PortfolioClient]:
    return sorted(load_portfolio_clients(path).values(), key=lambda c: (c.name.casefold(), c.id))
