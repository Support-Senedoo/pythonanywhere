#!/usr/bin/env python3
"""
Export / import d'un rapport comptable (account.report) personnalise entre bases Odoo,
y compris Odoo SaaS (XML-RPC).

- export : produit un fichier JSON (structure du rapport, lignes, expressions, colonnes).
- import : recree le rapport sur une autre base (meme plan comptable / localisation conseille).

Limites Odoo SaaS :
  - Pas d'upload de module ZIP arbitraire sur Odoo Online standard : utiliser ce JSON +
    import par API, ou Odoo.sh si vous packagez un module.
  - La cible doit avoir les memes modules (ex. l10n_syscohada, account_reports) et un
    root_report_id equivalent (recherche par nom si l'id differe).

Usage :
  python account_report_portable.py export --report-id 32 -o mon_rapport.json
  python account_report_portable.py import -i mon_rapport.json

Variables : ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD (ou .env)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore[misc, assignment]


def execute_kw(
    models: Any,
    db: str,
    uid: int,
    password: str,
    model: str,
    method: str,
    args: list[Any],
    kwargs: dict[str, Any] | None = None,
) -> Any:
    return models.execute_kw(db, uid, password, model, method, args, kwargs or {})


def connect(url: str, db: str, user: str, password: str) -> tuple[Any, int]:
    import xmlrpc.client

    base = url.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid_ = common.authenticate(db, user, password, {})
    if not uid_:
        raise RuntimeError("Authentification refusee.")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, int(uid_)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(repr(obj))


def _strip_for_export(
    vals: dict[str, Any],
    drop: frozenset[str],
) -> dict[str, Any]:
    return {k: v for k, v in vals.items() if k not in drop and not k.startswith("_")}


def _display_name_from_report_field(name: Any) -> str:
    """Libellé lisible pour le champ name traduit (account.report, lignes, etc.)."""
    if isinstance(name, dict):
        return str(
            name.get("fr_FR")
            or name.get("fr_BE")
            or name.get("en_US")
            or (next(iter(name.values())) if name else "")
        )
    return str(name or "")


def _writable_fields(
    models: Any,
    db: str,
    uid: int,
    password: str,
    model: str,
) -> list[str]:
    fg = execute_kw(models, db, uid, password, model, "fields_get", [], {"attributes": ["readonly", "required"]})
    out: list[str] = []
    for name, meta in fg.items():
        if meta.get("readonly"):
            continue
        if name in ("id", "create_uid", "create_date", "write_uid", "write_date"):
            continue
        out.append(name)
    return sorted(out)


def topological_line_ids(lines: list[dict[str, Any]]) -> list[int]:
    """Parents avant enfants (parent_id Many2one [id, name] ou False)."""
    by_id = {r["id"]: r for r in lines}
    remaining = set(by_id.keys())
    order: list[int] = []
    while remaining:
        ready: list[int] = []
        for rid in remaining:
            p = by_id[rid].get("parent_id")
            pid = p[0] if p else None
            if pid is None or pid not in remaining:
                ready.append(rid)
        if not ready:
            ready = [min(remaining)]
        for rid in sorted(ready):
            remaining.discard(rid)
            order.append(rid)
    return order


def cmd_export(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    output: Path,
) -> None:
    rep_fields = _writable_fields(models, db, uid, password, "account.report")
    # champs utiles en lecture meme si readonly (root_report_id, custom_handler...)
    read_extra = [
        "line_ids",
        "column_ids",
        "variant_report_ids",
        "section_report_ids",
        "root_report_id",
        "display_name",
        "custom_handler_model_name",
    ]
    read_fields = sorted(set(rep_fields) | set(read_extra) | {"name", "active", "sequence"})
    report = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": read_fields},
    )[0]

    rep_name_fr = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["name"], "context": {"lang": "fr_FR"}},
    )[0]
    report_display_name_fr = _display_name_from_report_field(rep_name_fr.get("name"))

    line_ids = report.get("line_ids") or []
    lines = []
    if line_ids:
        lf = _writable_fields(models, db, uid, password, "account.report.line")
        lf_read = sorted(
            set(lf)
            | {
                "expression_ids",
                "parent_id",
                "children_ids",
                "report_id",
                "display_name",
                "code",
                "name",
            }
        )
        lines = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [line_ids],
            {"fields": lf_read},
        )

    expr_all: list[dict[str, Any]] = []
    ef = _writable_fields(models, db, uid, password, "account.report.expression")
    ef_read = sorted(set(ef) | {"report_line_id", "label", "engine", "formula"})
    for line in lines:
        for eid in line.get("expression_ids") or []:
            ex = execute_kw(
                models,
                db,
                uid,
                password,
                "account.report.expression",
                "read",
                [[eid]],
                {"fields": ef_read},
            )
            expr_all.extend(ex)

    col_ids = report.get("column_ids") or []
    columns = []
    if col_ids:
        cf = _writable_fields(models, db, uid, password, "account.report.column")
        cf_read = sorted(set(cf) | {"report_id", "name", "expression_label"})
        columns = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.column",
            "read",
            [col_ids],
            {"fields": cf_read},
        )

    root = report.get("root_report_id")
    payload = {
        "format_version": 1,
        "source_report_id": report_id,
        "report_display_name_fr": report_display_name_fr,
        "account_report": _strip_for_export(
            report,
            frozenset({"line_ids", "column_ids", "variant_report_ids", "section_report_ids", "display_name", "id"}),
        ),
        "account_report_columns": [
            _strip_for_export(c, frozenset({"id", "report_id", "display_name"})) for c in columns
        ],
        "account_report_lines": [
            _strip_for_export(
                L,
                frozenset(
                    {
                        "id",
                        "report_id",
                        "expression_ids",
                        "children_ids",
                        "display_name",
                    }
                ),
            )
            | {"_export_id": L["id"]}
            for L in lines
        ],
        "account_report_expressions": [
            _strip_for_export(
                e,
                frozenset({"id", "report_line_id", "display_name"}),
            )
            | {"_line_export_id": e["report_line_id"][0] if e.get("report_line_id") else None}
            for e in expr_all
        ],
        "root_report_hint": {"id": root[0], "name": root[1]} if root else None,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    print(f"Exporte : {output} ({len(lines)} lignes, {len(expr_all)} expressions, {len(columns)} colonnes)")


def _resolve_root_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    hint: dict[str, Any] | None,
) -> int | None:
    if not hint:
        return None
    name = hint.get("name")
    if not name:
        return None
    ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [[("name", "=", name)]],
        {"limit": 2},
    )
    if len(ids) == 1:
        return ids[0]
    ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [[("name", "ilike", name[:20])]],
        {"limit": 5},
    )
    return ids[0] if ids else None


def _vals_clean(model: str, vals: dict[str, Any]) -> dict[str, Any]:
    drop = {"id", "_export_id", "_line_export_id", "create_uid", "write_uid", "create_date", "write_date"}
    out = {}
    for k, v in vals.items():
        if k in drop or k.startswith("_"):
            continue
        if v is False and k in (
            "parent_id",
            "root_report_id",
            "country_id",
            "action_id",
            "custom_audit_action_id",
        ):
            out[k] = False
            continue
        out[k] = v
    return out


def _normalize_translated_name(val: Any) -> Any:
    """Corrige un name stocke en chaine repr() au lieu d'un dict de traductions."""
    if isinstance(val, str) and val.strip().startswith("{") and "fr_FR" in val:
        import ast

        try:
            d = ast.literal_eval(val)
            if isinstance(d, dict):
                return d
        except (ValueError, SyntaxError):
            pass
    return val


def _resolve_import_names(
    raw_account_report: dict,
    new_name: str | None,
    *,
    report_display_name_fr: str | None = None,
) -> tuple[str, str]:
    """Libellés français et anglais pour le rapport importé (champ name traduit)."""
    raw_name = raw_account_report.get("name")
    fr: str | None = None
    en: str | None = None

    if new_name and str(new_name).strip():
        fr = str(new_name).strip()
        en = fr
    elif report_display_name_fr and str(report_display_name_fr).strip():
        fr = str(report_display_name_fr).strip()
        en = fr
    elif isinstance(raw_name, dict):
        fr = raw_name.get("fr_FR") or raw_name.get("fr_BE")
        en = raw_name.get("en_US") or raw_name.get("en_GB")
    elif isinstance(raw_name, str):
        norm = _normalize_translated_name(raw_name)
        if isinstance(norm, dict):
            fr = norm.get("fr_FR") or norm.get("fr_BE")
            en = norm.get("en_US")
        else:
            s = (norm or raw_name).strip()
            fr = s if s else None
            en = fr

    if not fr:
        fr = "Rapport importé"
    if not en:
        en = fr
    return fr, en


def apply_report_name_translations(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    fr: str,
    en: str,
) -> None:
    """
    Applique le libellé du rapport pour fr_FR et en_US.

    Un seul write {\"name\": ...} sans langue ne met souvent à jour que la traduction
    « active » (souvent en_US sur Odoo.com) : l’interface en français garde alors le
    titre anglais hérité du modèle. D’où deux écritures avec contexte langue explicite.
    """
    fr = (fr or "").strip() or "Rapport"
    en = (en or "").strip() or fr
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], {"name": fr}],
        {"context": {"lang": "fr_FR"}},
    )
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], {"name": en}],
        {"context": {"lang": "en_US"}},
    )


def cmd_import(
    models: Any,
    db: str,
    uid: int,
    password: str,
    input_path: Path,
    new_name: str | None,
) -> None:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    if raw.get("format_version") != 1:
        raise SystemExit("format_version non supporte")

    name_fr, name_en = _resolve_import_names(
        raw["account_report"],
        new_name,
        report_display_name_fr=raw.get("report_display_name_fr"),
    )

    root_id = _resolve_root_report(models, db, uid, password, raw.get("root_report_hint"))
    rep_vals = dict(raw["account_report"])
    rep_vals = _vals_clean("account.report", rep_vals)
    # Liens vers d'autres rapports : ids invalides sur une autre base
    rep_vals["section_main_report_ids"] = []
    rep_vals.pop("section_report_ids", None)
    rep_vals.pop("variant_report_ids", None)
    rep_vals.pop("custom_handler_model_id", None)
    # Libellé simple à la création ; les traductions FR/EN sont appliquées ensuite
    rep_vals["name"] = name_fr
    if root_id is not None:
        rep_vals["root_report_id"] = root_id
    else:
        rep_vals.pop("root_report_id", None)

    cols = raw["account_report_columns"]
    lines_in = raw["account_report_lines"]
    order = topological_line_ids(
        [
            {
                "id": x["_export_id"],
                "parent_id": x.get("parent_id"),
            }
            for x in lines_in
        ]
    )
    exprs = raw["account_report_expressions"]
    total_steps = 1 + len(cols) + len(order) + len(exprs) + 1

    pbar = (
        tqdm(
            total=total_steps,
            desc="Import rapport",
            unit="step",
            ascii=True,
            file=sys.stdout,
        )
        if tqdm
        else None
    )

    def _step(msg: str) -> None:
        if pbar:
            pbar.set_description(msg[:60])
        else:
            print(f"  · {msg}", flush=True)

    _step("Création du rapport")
    new_rep_id = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "create",
        [rep_vals],
        {"context": {"lang": "fr_FR"}},
    )
    if pbar:
        pbar.update(1)

    for col in cols:
        _step("Colonnes")
        cv = _vals_clean("account.report.column", dict(col))
        cv["report_id"] = new_rep_id
        execute_kw(models, db, uid, password, "account.report.column", "create", [cv])
        if pbar:
            pbar.update(1)

    old_line_to_new: dict[int, int] = {}
    id_by_export = {x["_export_id"]: x for x in lines_in}
    for eid in order:
        lv = id_by_export.get(eid)
        if not lv:
            if pbar:
                pbar.update(1)
            continue
        lv = dict(lv)
        ex_old = lv.pop("_export_id")
        p = lv.get("parent_id")
        if p:
            pid = p[0]
            lv["parent_id"] = old_line_to_new.get(pid) or False
        _step("Lignes du rapport")
        lv = _vals_clean("account.report.line", lv)
        lv["report_id"] = new_rep_id
        new_lid = execute_kw(models, db, uid, password, "account.report.line", "create", [lv])
        old_line_to_new[ex_old] = int(new_lid) if not isinstance(new_lid, list) else new_lid[0]
        if pbar:
            pbar.update(1)

    for ex in exprs:
        ev = dict(ex)
        old_l = ev.pop("_line_export_id", None)
        ev = _vals_clean("account.report.expression", ev)
        if old_l not in old_line_to_new:
            if pbar:
                pbar.update(1)
            continue
        _step("Expressions")
        ev["report_line_id"] = old_line_to_new[old_l]
        execute_kw(models, db, uid, password, "account.report.expression", "create", [ev])
        if pbar:
            pbar.update(1)

    _step("Libellés français / anglais")
    apply_report_name_translations(models, db, uid, password, new_rep_id, name_fr, name_en)
    if pbar:
        pbar.update(1)
        pbar.close()

    print(
        f"OK — rapport créé id={new_rep_id} ({len(old_line_to_new)} lignes). "
        f"Libellé FR : {name_fr[:60]}{'…' if len(name_fr) > 60 else ''}"
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Export / import account.report (JSON)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("export", help="Exporter un rapport vers JSON")
    pe.add_argument("--report-id", type=int, required=True)
    pe.add_argument("-o", "--output", type=Path, required=True)
    pe.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    pe.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    pe.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    pe.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)

    pi = sub.add_parser("import", help="Importer un JSON (cree un nouveau rapport)")
    pi.add_argument("-i", "--input", type=Path, required=True)
    pi.add_argument("--new-name", default=None, help="Nom du rapport sur la cible")
    pi.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    pi.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    pi.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    pi.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)

    args = p.parse_args()
    url, db, user, pw = args.url, args.db, args.user, args.password
    missing = [n for n, v in [("ODOO_URL", url), ("ODOO_DB", db), ("ODOO_USER", user), ("ODOO_PASSWORD", pw)] if not v]
    if missing:
        print("Manquant:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    models, uid = connect(url, db, user, pw)

    if args.cmd == "export":
        cmd_export(models, db, uid, pw, args.report_id, args.output)
    else:
        cmd_import(models, db, uid, pw, args.input, args.new_name)


if __name__ == "__main__":
    main()
