"""Jetons de réinitialisation de mot de passe (fichier JSON) + envoi e-mail optionnel (SMTP)."""
from __future__ import annotations

import json
import secrets
import smtplib
import tempfile
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

_TOKEN_TTL_SEC = 86400  # 24 h


def _read_tokens(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"tokens": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_tokens(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(text)
        Path(tmp).replace(path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def issue_reset_token(tokens_path: str | Path, login: str) -> str:
    """Crée un jeton unique ; retourne la valeur à mettre dans l’URL (sans révéler si le login existe)."""
    token = secrets.token_urlsafe(32)
    p = Path(tokens_path)
    data = _read_tokens(p)
    rows: list[dict[str, Any]] = list(data.get("tokens", []))
    now = int(time.time())
    rows = [r for r in rows if r.get("exp", 0) > now and not r.get("used")]
    rows.append(
        {
            "login": (login or "").strip(),
            "token": token,
            "exp": now + _TOKEN_TTL_SEC,
            "used": False,
        }
    )
    data["tokens"] = rows
    _write_tokens(p, data)
    return token


def consume_reset_token(tokens_path: str | Path, token: str) -> str | None:
    """Si jeton valide, retourne le login et marque le jeton comme utilisé ; sinon None."""
    p = Path(tokens_path)
    data = _read_tokens(p)
    rows: list[dict[str, Any]] = list(data.get("tokens", []))
    now = int(time.time())
    found_login: str | None = None
    new_rows: list[dict[str, Any]] = []
    for r in rows:
        if r.get("used"):
            continue
        if r.get("exp", 0) <= now:
            continue
        if r.get("token") == token:
            r = {**r, "used": True}
            found_login = (r.get("login") or "").strip() or None
        new_rows.append(r)
    data["tokens"] = new_rows
    _write_tokens(p, data)
    return found_login


def send_reset_email(
    *,
    to_addr: str,
    reset_url: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    mail_from: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = "Senedoo — réinitialisation du mot de passe"
    msg["From"] = mail_from
    msg["To"] = to_addr
    msg.set_content(
        f"Bonjour,\n\n"
        f"Pour choisir un nouveau mot de passe sur le portail Senedoo, ouvrez ce lien (valide 24 h) :\n\n"
        f"{reset_url}\n\n"
        f"Si vous n’avez pas demandé cette réinitialisation, ignorez ce message.\n"
    )
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.starttls()
        if smtp_user:
            smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)
