"""Analyse de fichiers CSV de pointage (prévisualisation, pas d’écriture Odoo ici)."""
from __future__ import annotations

import csv
import io
import re
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 5000
MAX_PREVIEW_ROWS = 80
ALLOWED_SUFFIX = (".csv", ".txt")


def _normalize_fieldnames(names: list[str] | None) -> list[str]:
    if not names:
        return []
    out: list[str] = []
    for n in names:
        s = (n or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def parse_pointage_csv(
    raw: bytes,
) -> tuple[list[str], list[dict[str, str]], list[str], int]:
    """
    Retourne (colonnes, lignes_preview, erreurs, nombre_lignes_données).
    `lignes_preview` est tronquée à MAX_PREVIEW_ROWS.
    """
    errors: list[str] = []
    if len(raw) > MAX_FILE_BYTES:
        return [], [], [f"Fichier trop volumineux (max {MAX_FILE_BYTES // (1024 * 1024)} Mo)."], 0

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("latin-1")
        except Exception as e:  # pragma: no cover
            return [], [], [f"Encodage illisible : {e!s}"], 0

    buf = io.StringIO(text)
    sample = text[: min(8192, len(text))]
    delimiter = ";"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";\t,")
        delimiter = dialect.delimiter
    except csv.Error:
        if sample.count(";") >= sample.count(","):
            delimiter = ";"
        else:
            delimiter = ","

    buf.seek(0)
    reader = csv.DictReader(buf, delimiter=delimiter)
    columns = _normalize_fieldnames(list(reader.fieldnames or []))
    if not columns:
        return [], [], ["Le fichier doit contenir une première ligne d’en-têtes (colonnes)."], 0

    rows_out: list[dict[str, str]] = []
    data_count = 0
    for lineno, row in enumerate(reader, start=2):
        if data_count >= MAX_DATA_ROWS:
            errors.append(f"Import limité à {MAX_DATA_ROWS} lignes de données (coupure à la ligne {lineno}).")
            break
        clean: dict[str, str] = {}
        empty = True
        for k, v in row.items():
            key = (k or "").strip()
            if key not in columns:
                continue
            val = (v or "").strip()
            if val:
                empty = False
            clean[key] = val
        if empty:
            continue
        data_count += 1
        if len(rows_out) < MAX_PREVIEW_ROWS:
            rows_out.append(clean)

    if data_count == 0:
        errors.append("Aucune ligne de données exploitable (toutes vides ?).")

    return columns, rows_out, errors, data_count


def safe_upload_filename(name: str | None) -> str:
    base = (name or "pointage.csv").rsplit("/")[-1].rsplit("\\")[-1]
    base = re.sub(r"[^\w.\-]", "_", base)[:120]
    return base or "pointage.csv"

