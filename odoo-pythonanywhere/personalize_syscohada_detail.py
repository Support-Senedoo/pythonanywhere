#!/usr/bin/env python3
"""
Personnalise une copie du P&L SYSCOHADA (account.report) :
  - lignes feuilles au moteur account_codes : détail par compte (user_groupby=account_id) ;
  - repliable par défaut (foldable) ;
  - désactive « tout déplier » sur le rapport pour respecter foldable.

ATTENTION (Odoo 18 Enterprise + SYSCOHADA) : ce rapport mélange expressions
« custom » (notes) et « account_codes ». Le dépliage avec groupby peut provoquer
RPC_ERROR / ValueError dans _expand_groupby (bug d'expansion). En cas d'erreur
à l'ouverture du rapport, exécuter :

  python personalize_syscohada_detail.py --report-id 32 --revert

Exclut les lignes en moteur « aggregation » seul (sous-totaux) : groupby interdit par Odoo.

Strategie :
  1) Par defaut (--fix-detail) : sur la COPIE uniquement, supprime les expressions
     « custom » (notes) sur les lignes feuilles, puis applique groupby account_id.
     Sans les notes custom, l'expansion Enterprise ne plante plus en general.
  2) --indent-only : ne touche pas au groupby ; active filter_hierarchy=by_default
     (filtre « Groupes de comptes » / structure du plan pour un rendu plus lisible).

Usage :
  python personalize_syscohada_detail.py --report-id 32 --fix-detail
  python personalize_syscohada_detail.py --report-id 32 --indent-only
  python personalize_syscohada_detail.py --report-id 32 --revert

Variables : ODOO_* ou .env (voir duplicate_syscohada_report.py)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Iterable, TypeVar

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore[misc, assignment]

_T = TypeVar("_T")


def _progress(it: Iterable[_T], desc: str, *, unit: str = "lig") -> Iterable[_T]:
    if tqdm is None:
        return it
    return tqdm(
        it,
        desc=desc,
        unit=unit,
        ascii=True,
        file=sys.stdout,
    )


def _rpc_context(kwargs: dict[str, Any] | None) -> dict[str, Any]:
    """Fusionne le contexte Odoo ; langue française par défaut (libellés account.report, etc.)."""
    kw = dict(kwargs or {})
    raw = kw.get("context")
    if raw is None or raw is False:
        ctx: dict[str, Any] = {}
    elif isinstance(raw, dict):
        ctx = dict(raw)
    else:
        ctx = {}
    if "lang" not in ctx:
        ctx["lang"] = (os.environ.get("TOOLBOX_ODOO_LANG") or "fr_FR").strip() or "fr_FR"
    kw["context"] = ctx
    return kw


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
    return models.execute_kw(db, uid, password, model, method, args, _rpc_context(kwargs))


def connect(url: str, db: str, user: str, password: str) -> tuple[Any, int]:
    import xmlrpc.client

    base = url.rstrip("/")
    common = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/common", allow_none=True)
    uid_ = common.authenticate(db, user, password, {})
    if not uid_:
        raise RuntimeError("Authentification refusee.")
    models = xmlrpc.client.ServerProxy(f"{base}/xmlrpc/2/object", allow_none=True)
    return models, int(uid_)


def leaf_line_ids_with_account_codes(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> list[int]:
    """Identifie les lignes feuilles avec au moins une expression account_codes et sans aggregation."""
    line_ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("report_id", "=", report_id)]],
    )
    out: list[int] = []
    for lid in _progress(line_ids, "Personnalisation — repérage feuilles (account_codes)"):
        line = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [[lid]],
            {"fields": ["children_ids", "expression_ids"]},
        )[0]
        if line.get("children_ids"):
            continue
        eids = line.get("expression_ids") or []
        if not eids:
            continue
        exprs = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "read",
            [eids],
            {"fields": ["engine"]},
        )
        engines = {e["engine"] for e in exprs}
        if "aggregation" in engines and "account_codes" not in engines:
            continue
        if "account_codes" not in engines:
            continue
        out.append(lid)
    return out


def strip_custom_expressions_on_leaves(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> int:
    """
    Supprime les account.report.expression en moteur 'custom' sur les lignes feuilles
    qui ont aussi account_codes. Les notes SYSCOHADA ne seront plus affichees sur ces
    lignes (copie de travail uniquement).
    Retourne le nombre d'expressions supprimees.
    """
    removed = 0
    leaves = leaf_line_ids_with_account_codes(models, db, uid, password, report_id)
    for lid in _progress(leaves, "Personnalisation — suppression notes « custom »"):
        line = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "read",
            [[lid]],
            {"fields": ["expression_ids"]},
        )[0]
        eids = line.get("expression_ids") or []
        if not eids:
            continue
        exprs = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.expression",
            "read",
            [eids],
            {"fields": ["id", "engine"]},
        )
        to_unlink = [e["id"] for e in exprs if e["engine"] == "custom"]
        for eid in to_unlink:
            execute_kw(models, db, uid, password, "account.report.expression", "unlink", [[eid]])
            removed += 1
    return removed


def revert_personalization(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> None:
    """Retire groupby/foldable sur toutes les lignes du rapport et rétablit filter_unfold_all."""
    lids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report.line",
        "search",
        [[("report_id", "=", report_id)]],
    )
    for lid in _progress(lids, "Réinitialisation — lignes (groupby / repliable)"):
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "write",
            [[lid], {"user_groupby": False, "groupby": False, "foldable": False}],
        )
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], {"filter_unfold_all": True}],
    )


def apply_groupby_on_leaves(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> None:
    lids = leaf_line_ids_with_account_codes(models, db, uid, password, report_id)
    for lid in _progress(lids, "Personnalisation — groupby compte + repliable"):
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report.line",
            "write",
            [[lid], {"user_groupby": "account_id", "foldable": True}],
        )
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], {"filter_unfold_all": False}],
    )


def personalize_fix_detail_complete(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> None:
    """
    Supprime les notes custom, applique groupby + foldable, filter_hierarchy,
    corrige le nom si chaine cassee (meme logique que --fix-detail).
    """
    n = strip_custom_expressions_on_leaves(models, db, uid, password, report_id)
    if tqdm is None:
        print(f"Expressions 'custom' (notes) supprimees : {n}")
    else:
        print(f"\nExpressions « custom » (notes) supprimées : {n}", flush=True)
    apply_groupby_on_leaves(models, db, uid, password, report_id)
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], {"filter_hierarchy": "by_default"}],
    )
    print("filter_hierarchy=by_default (groupes de comptes).", flush=True)
    rep = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["name"]},
    )[0]["name"]
    if isinstance(rep, str) and rep.strip().startswith("{") and "fr_FR" in rep:
        import ast

        try:
            d = ast.literal_eval(rep)
            if isinstance(d, dict) and "fr_FR" in d:
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report",
                    "write",
                    [[report_id], {"name": d}],
                )
                print("Nom du rapport corrige (traductions).")
        except (ValueError, SyntaxError):
            pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--report-id", type=int, default=32, help="account.report id (copie Senedoo)")
    p.add_argument(
        "--fix-detail",
        action="store_true",
        help="Supprime les notes custom sur les feuilles puis groupby compte (recommandé).",
    )
    p.add_argument(
        "--indent-only",
        action="store_true",
        help="Active seulement la hiérarchie des groupes de comptes (indentation visuelle).",
    )
    p.add_argument(
        "--revert",
        action="store_true",
        help="Annule groupby/foldable (corrige RPC_ERROR au dépliage sur SYSCOHADA).",
    )
    p.add_argument("--url", default=os.environ.get("ODOO_URL", "").strip() or None)
    p.add_argument("--db", default=os.environ.get("ODOO_DB", "").strip() or None)
    p.add_argument("-u", "--user", default=os.environ.get("ODOO_USER", "").strip() or None)
    p.add_argument("-p", "--password", default=os.environ.get("ODOO_PASSWORD", "").strip() or None)
    args = p.parse_args()

    missing = [n for n, v in [("ODOO_URL", args.url), ("ODOO_DB", args.db), ("ODOO_USER", args.user), ("ODOO_PASSWORD", args.password)] if not v]
    if missing:
        print("Manquant:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)

    models, uid = connect(args.url, args.db, args.user, args.password)
    pw = args.password

    if args.indent_only and args.revert:
        print("Choisir soit --indent-only soit --revert.", file=sys.stderr)
        sys.exit(2)

    if args.revert:
        revert_personalization(models, args.db, uid, pw, args.report_id)
        print(
            f"OK — rapport {args.report_id} : groupby/foldable retires, filter_unfold_all reactive."
        )
        return

    if args.indent_only:
        execute_kw(
            models,
            args.db,
            uid,
            pw,
            "account.report",
            "write",
            [[args.report_id], {"filter_hierarchy": "by_default"}],
        )
        print(
            f"OK — rapport {args.report_id} : filter_hierarchy=by_default "
            "(filtre Groupes de comptes actif par defaut pour structurer le plan)."
        )
        return

    if not args.fix_detail:
        print(
            "Indiquez --fix-detail (notes custom supprimees + detail par compte) "
            "ou --indent-only (hiérarchie comptes) ou --revert.",
            file=sys.stderr,
        )
        sys.exit(2)

    personalize_fix_detail_complete(models, args.db, uid, pw, args.report_id)
    nlines = len(
        leaf_line_ids_with_account_codes(models, args.db, uid, pw, args.report_id)
    )
    print(f"Rapport {args.report_id}: {nlines} lignes feuilles -> groupby account_id + foldable")

    print(
        "OK — testez le rapport : detail par compte au depliage. "
        "Si erreur RPC, lancez --revert puis --indent-only."
    )


if __name__ == "__main__":
    main()
