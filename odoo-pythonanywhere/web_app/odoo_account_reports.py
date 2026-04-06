"""Liste / filtre des rapports comptables Odoo (account.report) pour l’utilitaire staff."""
from __future__ import annotations

import re
from typing import Any

from odoo_client import normalize_odoo_base_url
from personalize_syscohada_detail import execute_kw
from web_app import app_version

# Titre spécifique à l’écran ; version / date / auteur = source unique app_version.py
UTILITY_TITLE = "Compte de résultat — personnalisation (détail / SYSCOHADA)"
UTILITY_TITLE_BALANCE = "Balance OHADA — 6 colonnes (Senedoo)"
UTILITY_TITLE_PL_BUDGET = "Compte de résultat — analytique et budget"
UTILITY_TITLE_PL_ANALYTIC_API = "Compte de résultat analytique (réalisé / budget / %)"
UTILITY_VERSION = app_version.TOOLBOX_APP_VERSION
UTILITY_DATE = app_version.TOOLBOX_APP_DATE
UTILITY_AUTHOR = app_version.TOOLBOX_APP_AUTHOR


def account_report_odoo_form_url(base_url: str, report_id: int) -> str:
    """Lien backend Odoo vers la fiche technique du rapport (modèle account.report, formulaire)."""
    base = normalize_odoo_base_url(base_url).rstrip("/")
    return f"{base}/web#id={int(report_id)}&model=account.report&view_type=form"


def account_report_odoo_runner_url(base_url: str, report_id: int) -> str:
    """
    Ancienne forme d’URL « courte » vers un enregistrement ``account.report``.

    Sur Odoo 17+, ce lien ouvre surtout la **vue fiche / backend**, pas l’écran d’analyse (grille du rapport).
    Préférer :func:`account_report_execution_url` (action client ``account_report``).
    """
    base = normalize_odoo_base_url(base_url).rstrip("/")
    rid = int(report_id)
    return f"{base}/odoo/account.report/{rid}?model=account.report&resId={rid}"


# Champs ``account.report`` recalculés depuis ``root_report_id`` (addons/account/models/account_report.py).
ACCOUNT_REPORT_OPTION_FIELDS_FROM_VARIANT: tuple[str, ...] = (
    "only_tax_exigible",
    "allow_foreign_vat",
    "default_opening_date_filter",
    "currency_translation",
    "filter_multi_company",
    "filter_date_range",
    "filter_show_draft",
    "filter_unreconciled",
    "filter_unfold_all",
    "filter_hide_0_lines",
    "filter_period_comparison",
    "filter_growth_comparison",
    "filter_journals",
    "filter_analytic",
    "filter_hierarchy",
    "filter_account_type",
    "filter_partner",
    "filter_aml_ir_filters",
    "filter_budgets",
)


def copy_account_report_options_from_source(
    models: Any,
    db: str,
    uid: int,
    password: str,
    source_report_id: int,
    target_report_id: int,
) -> None:
    """Recopie les options de filtre / disponibilité du rapport source vers la cible (copie autonome)."""
    try:
        fg = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "fields_get",
            [],
            {"attributes": ["type"]},
        )
    except Exception:
        return
    names = set(fg.keys())
    fields = [f for f in ACCOUNT_REPORT_OPTION_FIELDS_FROM_VARIANT if f in names]
    for extra in ("availability_condition", "country_id"):
        if extra in names:
            fields.append(extra)
    if not fields:
        return
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[int(source_report_id)]],
        {"fields": fields},
    )
    if not rows:
        return
    vals = {k: rows[0][k] for k in fields if k in rows[0]}
    if vals:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[int(target_report_id)], vals],
        )


def find_account_report_client_action_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> int | None:
    """
    Retourne l’id ``ir.actions.client`` (tag ``account_report``) dont le contexte fixe ce ``report_id``.

    Odoo teste ainsi l’accessibilité menu : ``('context', 'ilike', \"'report_id': %s\")``.
    """
    rid = int(report_id)
    needles = (
        f"'report_id': {rid}",
        f'"report_id": {rid}',
        f"'report_id':{rid}",
    )
    for needle in needles:
        try:
            aids = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.actions.client",
                "search",
                [[("tag", "=", "account_report"), ("context", "ilike", needle)]],
                {"limit": 40},
            )
        except Exception:
            continue
        if not aids:
            continue
        if len(aids) == 1:
            return int(aids[0])
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.actions.client",
            "read",
            [aids],
            {"fields": ["id", "context"]},
        )
        for row in rows:
            ctx = row.get("context") or ""
            if f"{rid}" in str(ctx) and "report_id" in str(ctx):
                return int(row["id"])
    return None


_CTX_REPORT_ID_RE = re.compile(r"""['"]?report_id['"]?\s*:\s*(\d+)""")


def _report_id_from_account_report_client_context(ctx: Any) -> int | None:
    """Extrait l’id de rapport depuis le contexte d’une action client ``account_report``."""
    m = _CTX_REPORT_ID_RE.search(str(ctx or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def find_all_account_report_client_action_ids(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> list[int]:
    """
    Toutes les ``ir.actions.client`` (tag ``account_report``) dont le contexte fixe ce ``report_id``.
    """
    rid = int(report_id)
    needles = (
        f"'report_id': {rid}",
        f'"report_id": {rid}',
        f"'report_id':{rid}",
    )
    seen: set[int] = set()
    for needle in needles:
        try:
            aids = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.actions.client",
                "search",
                [[("tag", "=", "account_report"), ("context", "ilike", needle)]],
                {"limit": 120},
            )
        except Exception:
            continue
        for a in aids or []:
            seen.add(int(a))
    if not seen:
        return []
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "ir.actions.client",
        "read",
        [list(seen)],
        {"fields": ["id", "context"]},
    )
    out: list[int] = []
    for row in rows:
        if _report_id_from_account_report_client_context(row.get("context")) == rid:
            out.append(int(row["id"]))
    return out


def _unlink_menus_bound_to_client_action(
    models: Any,
    db: str,
    uid: int,
    password: str,
    client_action_id: int,
) -> int:
    """Supprime les ``ir.ui.menu`` dont l’action est ``ir.actions.client,<id>``. Retourne le nombre supprimé."""
    ref = f"ir.actions.client,{int(client_action_id)}"
    try:
        mids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "search",
            [[("action", "=", ref)]],
            {"limit": 500},
        )
    except Exception:
        return 0
    if not mids:
        return 0
    try:
        execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "unlink",
            [mids],
        )
        return len(mids)
    except Exception:
        return 0


def _unlink_account_report_related_menus_and_client_actions(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> tuple[int, int]:
    """
    Avant suppression d’un ``account.report`` : enlève menus + actions client créés pour l’exécution
    (tag ``account_report``, contexte avec ce ``report_id``).
    """
    aids = find_all_account_report_client_action_ids(models, db, uid, password, report_id)
    menus_total = 0
    actions_total = 0
    for aid in aids:
        menus_total += _unlink_menus_bound_to_client_action(models, db, uid, password, aid)
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "ir.actions.client",
                "unlink",
                [[aid]],
            )
            actions_total += 1
        except Exception:
            pass
    return menus_total, actions_total


def unlink_all_account_report_client_actions_for_report_ids(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_ids: set[int],
) -> tuple[int, int]:
    """
    Parcourt **toutes** les ``ir.actions.client`` (tag ``account_report``) et supprime celles
    dont le contexte référence un ``report_id`` dans ``report_ids``, ainsi que les
    ``ir.ui.menu`` qui y sont liés.

    Utile après coup ou lorsque ``find_all_account_report_client_action_ids`` n’a pas reconnu
    le format de ``context`` (guillemets, espaces, JSON).
    """
    if not report_ids:
        return 0, 0
    rid_set = {int(x) for x in report_ids}
    menus_total = 0
    actions_total = 0
    try:
        aids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.actions.client",
            "search",
            [[("tag", "=", "account_report")]],
            {"limit": 4000},
        )
    except Exception:
        return 0, 0
    if not aids:
        return 0, 0
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "ir.actions.client",
        "read",
        [aids],
        {"fields": ["id", "context"]},
    )
    target_aids: list[int] = []
    for row in rows:
        prid = _report_id_from_account_report_client_context(row.get("context"))
        if prid is not None and int(prid) in rid_set:
            target_aids.append(int(row["id"]))
    for aid in target_aids:
        menus_total += _unlink_menus_bound_to_client_action(models, db, uid, password, aid)
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "ir.actions.client",
                "unlink",
                [[aid]],
            )
            actions_total += 1
        except Exception:
            pass
    return menus_total, actions_total


def ensure_account_report_client_action(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    *,
    action_name: str,
) -> int | None:
    """
    Garantit une action client ``account_report`` pour ce rapport (création si aucune trouvée).

    Si l’action existe déjà, met à jour son **nom** pour rester aligné avec le rapport / le menu.
    Les droits d’écriture sur ``ir.actions.client`` sont requis pour la création et la mise à jour.
    """
    found = find_account_report_client_action_id(models, db, uid, password, report_id)
    name = (action_name or f"Rapport comptable {report_id}").strip()[:255] or f"Rapport {report_id}"
    if found:
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "ir.actions.client",
                "write",
                [[int(found)], {"name": name}],
            )
        except Exception:
            pass
        return found
    ctx = repr({"report_id": int(report_id)})
    vals: dict[str, Any] = {
        "name": name,
        "tag": "account_report",
        "target": "current",
        "context": ctx,
    }
    try:
        return int(
            execute_kw(
                models,
                db,
                uid,
                password,
                "ir.actions.client",
                "create",
                [vals],
            )
        )
    except Exception:
        return None


def account_report_execution_url(
    base_url: str,
    client_action_id: int,
    *,
    menu_id: int | None = None,
) -> str:
    """
    URL vers l’écran d’exécution du rapport (client action ``account_report``).

    Avec ``menu_id`` (entrée ``ir.ui.menu`` pointant sur la même action), le client web
    Odoo charge correctement le fil d’Ariane / le menu — souvent nécessaire sur SaaS récents.
    """
    base = normalize_odoo_base_url(base_url).rstrip("/")
    aid = int(client_action_id)
    mid = int(menu_id) if menu_id is not None else None
    if mid is not None and mid > 0:
        return f"{base}/web#menu_id={mid}&action={aid}"
    return f"{base}/web#action={aid}"


def _ir_ui_menu_id_from_xmlid(
    models: Any,
    db: str,
    uid: int,
    password: str,
    module: str,
    name: str,
) -> int | None:
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "ir.model.data",
        "search_read",
        [[("module", "=", module), ("name", "=", name), ("model", "=", "ir.ui.menu")]],
        {"fields": ["res_id"], "limit": 1},
    )
    if not rows or not rows[0].get("res_id"):
        return None
    return int(rows[0]["res_id"])


# Parents possibles pour accrocher un rapport « autonome » (sans root_report_id).
_ACCOUNT_REPORT_MENU_PARENT_XMLIDS: tuple[str, ...] = (
    "account.account_reports_legal_statements_menu",
    "account.menu_finance_reports",
)

# Menu « Balance comptable » / trial balance (Enterprise account_reports, etc.) : même parent = sous-menu
# type Analyse › Grands livres ; on insère la copie juste après cette entrée (séquence + 1).
_TRIAL_BALANCE_MENU_XMLIDS: tuple[str, ...] = (
    "account_reports.menu_action_account_report_trial_balance",
    "account_accountant.menu_action_account_report_trial_balance",
    "account.menu_action_account_report_trial_balance",
)
_TRIAL_BALANCE_DATA_NAME_EXACT = "menu_action_account_report_trial_balance"
_TRIAL_BALANCE_MODULE_PREF: tuple[str, ...] = (
    "account_reports",
    "account_accountant",
    "account",
)


def _menu_m2o_id(val: Any) -> int | None:
    if val in (None, False):
        return None
    if isinstance(val, (list, tuple)) and val:
        try:
            return int(val[0])
        except (TypeError, ValueError):
            return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _next_menu_sequence_under_parent(
    models: Any,
    db: str,
    uid: int,
    password: str,
    parent_menu_id: int,
) -> int:
    """Prochaine séquence libre sous un menu parent (ajout en fin de sous-menu)."""
    try:
        mids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "search",
            [[("parent_id", "=", int(parent_menu_id))]],
            {"limit": 500},
        )
    except Exception:
        return 500
    if not mids:
        return 10
    try:
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "read",
            [mids],
            {"fields": ["sequence"]},
        )
    except Exception:
        return 500
    mx = 0
    for r in rows or []:
        try:
            mx = max(mx, int(r.get("sequence") or 0))
        except (TypeError, ValueError):
            continue
    return mx + 1


# Grand livre général : son ``parent_id`` est le sous-menu **Grands livres** (Analyse › …).
_GENERAL_LEDGER_MENU_XMLIDS: tuple[str, ...] = (
    "account_reports.menu_action_account_report_general_ledger",
    "account_reports.menu_action_account_report_gl",
    "account_accountant.menu_action_account_report_general_ledger",
    "account.menu_action_account_report_general_ledger",
)
_GENERAL_LEDGER_DATA_NAME_EXACT = "menu_action_account_report_general_ledger"
_GENERAL_LEDGER_MODULE_PREF: tuple[str, ...] = (
    "account_reports",
    "account_accountant",
    "account",
)


def _find_general_ledger_menu_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> int | None:
    for xmlid in _GENERAL_LEDGER_MENU_XMLIDS:
        mod, _, name = xmlid.partition(".")
        if not name:
            continue
        mid = _ir_ui_menu_id_from_xmlid(models, db, uid, password, mod, name)
        if mid:
            return mid
    try:
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.model.data",
            "search_read",
            [
                [
                    ("model", "=", "ir.ui.menu"),
                    ("name", "=", _GENERAL_LEDGER_DATA_NAME_EXACT),
                ]
            ],
            {"fields": ["module", "res_id"], "limit": 20},
        )
    except Exception:
        rows = []
    if not rows:
        try:
            rows = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.model.data",
                "search_read",
                [
                    [
                        ("model", "=", "ir.ui.menu"),
                        ("name", "ilike", "%general_ledger%"),
                    ]
                ],
                {"fields": ["module", "res_id"], "limit": 20},
            )
        except Exception:
            rows = []
    if not rows:
        return None

    def _pref_key(mod: str) -> int:
        try:
            return _GENERAL_LEDGER_MODULE_PREF.index(mod)
        except ValueError:
            return len(_GENERAL_LEDGER_MODULE_PREF)

    rows.sort(
        key=lambda r: (_pref_key(str(r.get("module") or "")), str(r.get("name") or ""))
    )
    rid = rows[0].get("res_id")
    return int(rid) if rid else None


def find_general_ledger_account_report_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> int | None:
    """
    Rapport ``account.report`` du Grand livre / balance générale standard, pour lier une
    variante (``root_report_id``) et disposer des variables ``initial_debit``,
    ``initial_credit``, etc. en moteur ``aggregation``.

    Ordre : xmlid ``account.report`` → menu Grand livre → action ``ir.actions.client`` /
    ``ir.actions.act_window`` → recherche par nom (hors handler balance d’essai Enterprise).
    """
    xmlid_pairs: tuple[tuple[str, str], ...] = (
        ("account_reports", "account_financial_report_general_ledger"),
        ("account_reports", "account_general_ledger_report"),
        ("account_reports", "account_report_general_ledger"),
        ("account", "account_general_ledger_report"),
        ("account", "account_financial_report_general_ledger"),
    )
    for mod, name in xmlid_pairs:
        try:
            rows = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.model.data",
                "search_read",
                [
                    [
                        ("module", "=", mod),
                        ("name", "=", name),
                        ("model", "=", "account.report"),
                    ]
                ],
                {"fields": ["res_id"], "limit": 1},
            )
        except Exception:
            rows = []
        if rows and rows[0].get("res_id"):
            try:
                return int(rows[0]["res_id"])
            except (TypeError, ValueError):
                pass

    gl_mid = _find_general_ledger_menu_id(models, db, uid, password)
    if gl_mid:
        try:
            mrows = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.ui.menu",
                "read",
                [[int(gl_mid)]],
                {"fields": ["action"]},
            )
        except Exception:
            mrows = []
        if mrows:
            act = mrows[0].get("action")
            if isinstance(act, str) and "," in act:
                amodel, _, ares = act.partition(",")
                amodel = amodel.strip()
                try:
                    aid = int(ares.strip())
                except ValueError:
                    aid = None
                if aid:
                    if amodel == "ir.actions.client":
                        try:
                            crows = execute_kw(
                                models,
                                db,
                                uid,
                                password,
                                "ir.actions.client",
                                "read",
                                [[aid]],
                                {"fields": ["tag", "context"]},
                            )
                        except Exception:
                            crows = []
                        if crows and str(crows[0].get("tag") or "") == "account_report":
                            rid = _report_id_from_account_report_client_context(
                                crows[0].get("context")
                            )
                            if rid:
                                return int(rid)
                    elif amodel == "ir.actions.act_window":
                        try:
                            aw_rows = execute_kw(
                                models,
                                db,
                                uid,
                                password,
                                "ir.actions.act_window",
                                "read",
                                [[aid]],
                                {"fields": ["res_model", "res_id"]},
                            )
                        except Exception:
                            aw_rows = []
                        if aw_rows:
                            if aw_rows[0].get("res_model") == "account.report":
                                r = aw_rows[0].get("res_id")
                                if r:
                                    try:
                                        return int(r)
                                    except (TypeError, ValueError):
                                        pass

    for domain in (
        [("name", "ilike", "general ledger")],
        [("name", "ilike", "grand livre")],
        [("name", "ilike", "balance générale")],
    ):
        try:
            rids = execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "search",
                [domain],
                {"limit": 20, "order": "id asc"},
            )
        except Exception:
            rids = []
        for rid in rids or []:
            try:
                row = execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report",
                    "read",
                    [[int(rid)]],
                    {"fields": ["custom_handler_model_name", "name"]},
                )[0]
            except Exception:
                continue
            h = (row.get("custom_handler_model_name") or "").lower()
            if "trial.balance" in h:
                continue
            return int(rid)
    return None


def resolve_parent_menu_in_grands_livres_group(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> tuple[int, int] | None:
    """
    Place le menu sous le groupe **Grands livres** (même parent que le Grand livre général).

    Résolution : menu d’action du rapport Grand livre → ``parent_id`` = dossier Grands livres ;
    séquence = fin de liste des enfants. Repli : ancienne logique « après balance comptable ».
    """
    gl_mid = _find_general_ledger_menu_id(models, db, uid, password)
    if gl_mid:
        try:
            gl_rows = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.ui.menu",
                "read",
                [[gl_mid]],
                {"fields": ["parent_id"]},
            )
        except Exception:
            gl_rows = []
        if gl_rows:
            parent_id = _menu_m2o_id(gl_rows[0].get("parent_id"))
            if parent_id:
                seq = _next_menu_sequence_under_parent(
                    models, db, uid, password, parent_id
                )
                return (parent_id, seq)
    return resolve_parent_menu_below_trial_balance(models, db, uid, password)


def _find_trial_balance_menu_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> int | None:
    for xmlid in _TRIAL_BALANCE_MENU_XMLIDS:
        mod, _, name = xmlid.partition(".")
        if not name:
            continue
        mid = _ir_ui_menu_id_from_xmlid(models, db, uid, password, mod, name)
        if mid:
            return mid
    try:
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.model.data",
            "search_read",
            [
                [
                    ("model", "=", "ir.ui.menu"),
                    ("name", "=", _TRIAL_BALANCE_DATA_NAME_EXACT),
                ]
            ],
            {"fields": ["module", "res_id"], "limit": 20},
        )
    except Exception:
        rows = []
    if not rows:
        try:
            rows = execute_kw(
                models,
                db,
                uid,
                password,
                "ir.model.data",
                "search_read",
                [
                    [
                        ("model", "=", "ir.ui.menu"),
                        ("name", "ilike", "%trial_balance%"),
                    ]
                ],
                {"fields": ["module", "res_id"], "limit": 20},
            )
        except Exception:
            rows = []
    if not rows:
        return None

    def _pref_key(mod: str) -> int:
        try:
            return _TRIAL_BALANCE_MODULE_PREF.index(mod)
        except ValueError:
            return len(_TRIAL_BALANCE_MODULE_PREF)

    rows.sort(key=lambda r: (_pref_key(str(r.get("module") or "")), str(r.get("name") or "")))
    rid = rows[0].get("res_id")
    return int(rid) if rid else None


def resolve_parent_menu_below_trial_balance(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> tuple[int, int] | None:
    """
    Parent ``ir.ui.menu`` du menu Balance comptable / trial balance + séquence pour placer une entrée
    juste après (même niveau que Balance comptable, sous Analyse › Grands livres selon la traduction).
    """
    tb_mid = _find_trial_balance_menu_id(models, db, uid, password)
    if not tb_mid:
        return None
    try:
        tb_rows = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "read",
            [[tb_mid]],
            {"fields": ["parent_id", "sequence"]},
        )
    except Exception:
        return None
    if not tb_rows:
        return None
    parent_id = _menu_m2o_id(tb_rows[0].get("parent_id"))
    if not parent_id:
        return None
    seq = tb_rows[0].get("sequence")
    try:
        base_seq = int(seq) if seq is not None else 10
    except (TypeError, ValueError):
        base_seq = 10
    return (parent_id, base_seq + 1)


def resolve_parent_menu_for_account_report(models: Any, db: str, uid: int, password: str) -> int | None:
    """Retourne l’id ``ir.ui.menu`` parent (ex. Reporting > Statement Reports)."""
    for xmlid in _ACCOUNT_REPORT_MENU_PARENT_XMLIDS:
        mod, _, name = xmlid.partition(".")
        if not name:
            continue
        mid = _ir_ui_menu_id_from_xmlid(models, db, uid, password, mod, name)
        if mid:
            return mid
    return None


def find_menu_id_for_client_action(
    models: Any,
    db: str,
    uid: int,
    password: str,
    client_action_id: int,
) -> int | None:
    ref = f"ir.actions.client,{int(client_action_id)}"
    try:
        mids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "search",
            [[("action", "=", ref)]],
            {"limit": 5, "order": "id desc"},
        )
    except Exception:
        return None
    return int(mids[0]) if mids else None


def sync_menu_labels_for_client_action(
    models: Any,
    db: str,
    uid: int,
    password: str,
    client_action_id: int,
    menu_title: str,
) -> None:
    """
    Aligne le libellé de **toutes** les entrées ``ir.ui.menu`` pointant sur cette action client
    (évite un menu obsolète si le rapport a été renommé ou pour doublons).
    """
    label = (menu_title or "").strip()
    if not label:
        return
    if len(label) > 120:
        label = label[:117] + "…"
    ref = f"ir.actions.client,{int(client_action_id)}"
    try:
        mids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "search",
            [[("action", "=", ref)]],
            {"limit": 500},
        )
    except Exception:
        return
    for mid in mids or []:
        try:
            execute_kw(
                models,
                db,
                uid,
                password,
                "ir.ui.menu",
                "write",
                [[int(mid)], {"name": label}],
            )
        except Exception:
            pass


def find_account_report_backend_list_action_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> int | None:
    """Action « liste » des rapports comptables (trouver la copie dans la configuration)."""
    try:
        aids = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.actions.act_window",
            "search",
            [[("res_model", "=", "account.report")]],
            {"limit": 40, "order": "id asc"},
        )
    except Exception:
        return None
    if not aids:
        return None
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "ir.actions.act_window",
        "read",
        [aids],
        {"fields": ["id", "name"]},
    )
    for r in rows:
        n = str(r.get("name") or "").lower()
        if any(k in n for k in ("financial", "report", "statement", "rapport", "compta")):
            return int(r["id"])
    return int(rows[0]["id"])


def account_report_backend_list_url(base_url: str, act_window_id: int) -> str:
    """URL backend vers la liste des ``account.report`` (recherche par nom / id)."""
    base = normalize_odoo_base_url(base_url).rstrip("/")
    return f"{base}/web#action={int(act_window_id)}"


def ensure_account_report_reporting_menu(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    menu_title: str,
    *,
    under_trial_balance: bool = False,
) -> tuple[int | None, int | None]:
    """
    Garantit une ``ir.actions.client`` + une entrée ``ir.ui.menu``.

    Par défaut : sous **Reporting** (Statement Reports / Reporting). Avec ``under_trial_balance=True``
    (balance 6 col.) : sous le sous-menu **Grands livres** (parent du **Grand livre général** si
    trouvé ; séquence en fin de groupe), sinon repli après **Balance comptable**.

    Retourne ``(client_action_id, menu_id)``. Si aucun parent menu n’est résolu, retourne
    ``(action_id, None)`` — l’URL ``web#action=`` peut rester insuffisante selon la version Odoo.
    """
    title = (menu_title or f"Rapport {report_id}").strip()
    if len(title) > 120:
        title = title[:117] + "…"
    aid = ensure_account_report_client_action(
        models,
        db,
        uid,
        password,
        int(report_id),
        action_name=title,
    )
    if not aid:
        return None, None
    sync_menu_labels_for_client_action(models, db, uid, password, aid, title)
    ref = f"ir.actions.client,{int(aid)}"
    existing_mid = find_menu_id_for_client_action(models, db, uid, password, aid)

    if under_trial_balance:
        placement = resolve_parent_menu_in_grands_livres_group(models, db, uid, password)
        if placement:
            parent_id, menu_sequence = placement[0], placement[1]
        else:
            parent_id = resolve_parent_menu_for_account_report(models, db, uid, password)
            menu_sequence = 500
    else:
        parent_id = resolve_parent_menu_for_account_report(models, db, uid, password)
        menu_sequence = 500

    if existing_mid:
        if parent_id:
            try:
                cur = execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "ir.ui.menu",
                    "read",
                    [[int(existing_mid)]],
                    {"fields": ["parent_id", "sequence"]},
                )
                if cur:
                    cp = _menu_m2o_id(cur[0].get("parent_id"))
                    cs = cur[0].get("sequence")
                    try:
                        cs_int = int(cs) if cs is not None else 0
                    except (TypeError, ValueError):
                        cs_int = 0
                    if cp != int(parent_id) or cs_int != int(menu_sequence):
                        execute_kw(
                            models,
                            db,
                            uid,
                            password,
                            "ir.ui.menu",
                            "write",
                            [
                                [int(existing_mid)],
                                {
                                    "parent_id": int(parent_id),
                                    "sequence": int(menu_sequence),
                                },
                            ],
                        )
            except Exception:
                pass
        return aid, existing_mid
    if not parent_id:
        return aid, None
    try:
        new_mid = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.ui.menu",
            "create",
            [
                {
                    "name": title,
                    "parent_id": int(parent_id),
                    "action": ref,
                    "sequence": int(menu_sequence),
                }
            ],
        )
        return aid, int(new_mid)
    except Exception:
        return aid, None


def format_report_name(val: Any) -> str:
    """Affichage prioritaire en français (traductions Odoo sur account.report.name)."""
    if isinstance(val, dict):
        for k in ("fr_FR", "fr_BE", "fr_CA", "fr_CH", "fr_LU"):
            if val.get(k):
                return str(val[k])
        for key in sorted(val.keys()):
            if isinstance(key, str) and key.startswith("fr_") and val.get(key):
                return str(val[key])
        for k in ("en_US", "en_GB"):
            if val.get(k):
                return str(val[k])
        for v in val.values():
            if v:
                return str(v)
        return str(val)
    if val is None:
        return "—"
    return str(val)


def read_account_report_label(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> str:
    """Libellé du rapport en français (via contexte RPC)."""
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["name"]},
    )
    if not rows:
        return f"#{report_id}"
    return format_report_name(rows[0].get("name"))


def probe_odoo_reports_access(
    models: Any,
    db: str,
    uid: int,
    password: str,
) -> tuple[bool, str]:
    """Teste l’API sur la base : modèle account.report + comptage."""
    try:
        has_model = execute_kw(
            models,
            db,
            uid,
            password,
            "ir.model",
            "search_count",
            [[("model", "=", "account.report")]],
        )
        if not has_model:
            return False, "Le modèle « account.report » est absent (module Comptabilité / version Odoo ?)."
        n = int(
            execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "search_count",
                [[]],
            )
        )
        return True, f"Connexion OK — {n} rapport(s) comptable(s) référencé(s)."
    except Exception as e:
        return False, str(e)


def search_account_reports(
    models: Any,
    db: str,
    uid: int,
    password: str,
    filter_text: str,
    *,
    limit: int = 400,
) -> list[dict[str, Any]]:
    q = (filter_text or "").strip()
    domain: list = []
    if q:
        domain = [("name", "ilike", q)]
    ids = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "search",
        [domain],
        {"limit": limit, "order": "id desc"},
    )
    if not ids:
        return []
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [ids],
        {"fields": ["id", "name"]},
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "name": format_report_name(r.get("name")),
                "name_raw": r.get("name"),
            }
        )
    return out


def unlink_account_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
) -> dict[str, int]:
    """
    Supprime le rapport et, au préalable, les entrées de menu + actions client ``account_report``
    pointant sur ce ``report_id`` (évite les entrées orphelines dans Odoo).
    """
    menus_n, actions_n = _unlink_account_report_related_menus_and_client_actions(
        models, db, uid, password, int(report_id)
    )
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "unlink",
        [[report_id]],
    )
    return {"menus_unlinked": menus_n, "client_actions_unlinked": actions_n}


def _merge_report_name_for_rename(raw_name: Any, new_label: str) -> Any:
    """Met à jour le champ name (traduit ou simple) pour l’affichage liste en français."""
    if isinstance(raw_name, dict):
        out = dict(raw_name)
        touched = False
        for k in list(out.keys()):
            if isinstance(k, str) and (k == "fr_FR" or k.startswith("fr_")):
                out[k] = new_label
                touched = True
        if not touched:
            out["fr_FR"] = new_label
        return out
    return new_label


def write_account_report_name(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    new_label: str,
) -> None:
    """Écrit le libellé du rapport dans Odoo (champ name, y compris traductions fr_*)."""
    label = (new_label or "").strip()
    if not label:
        raise ValueError("Le nouveau nom ne peut pas être vide.")
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[report_id]],
        {"fields": ["name"]},
    )
    if not rows:
        raise ValueError(f"Rapport comptable id={report_id} introuvable.")
    merged = _merge_report_name_for_rename(rows[0].get("name"), label)
    execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "write",
        [[report_id], {"name": merged}],
    )


def _copy_report_display_name(raw_name: Any, suffix: str) -> Any:
    """Construit le nom affiché du rapport dupliqué (traductions Odoo ou chaîne simple)."""
    if isinstance(raw_name, dict):
        out = dict(raw_name)
        for key in ("fr_FR", "fr_BE", "fr_CA", "en_US", "en_GB"):
            v = out.get(key)
            if v and isinstance(v, str) and suffix.strip() not in v:
                out[key] = v.rstrip() + suffix
                return out
        for k, v in list(out.items()):
            if v and isinstance(v, str) and suffix.strip() not in v:
                out[k] = v.rstrip() + suffix
                return out
        return out
    s = str(raw_name or "Rapport").strip()
    return s + suffix if suffix.strip() not in s else s


def _ultimate_root_report_id(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    *,
    max_hops: int = 24,
) -> int:
    """Remonte les ``root_report_id`` jusqu’au rapport racine (menu / variantes Odoo)."""
    cur = int(report_id)
    for _ in range(max_hops):
        rows = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "read",
            [[cur]],
            {"fields": ["root_report_id"]},
        )
        if not rows:
            return cur
        rr = rows[0].get("root_report_id")
        if not rr or not (isinstance(rr, (list, tuple)) and rr[0]):
            return cur
        nxt = int(rr[0])
        if nxt == cur:
            return cur
        cur = nxt
    return cur


def _account_report_has_field(
    models: Any,
    db: str,
    uid: int,
    password: str,
    field_name: str,
) -> bool:
    try:
        fg = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "fields_get",
            [],
            {"attributes": ["type"]},
        )
    except Exception:
        return False
    return field_name in fg


def _link_report_copy_to_root(
    models: Any,
    db: str,
    uid: int,
    password: str,
    new_report_id: int,
    root_report_id: int,
) -> None:
    """Rattache la copie à la balance / racine d’origine (variante du même ``root_report_id``)."""
    if not _account_report_has_field(models, db, uid, password, "root_report_id"):
        return
    if new_report_id == root_report_id:
        return
    try:
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[new_report_id], {"root_report_id": root_report_id}],
        )
    except Exception:
        pass


def _proposed_name_search_strings(proposed: Any) -> list[str]:
    out: list[str] = []
    if isinstance(proposed, dict):
        for k in ("fr_FR", "fr_BE", "fr_CA", "fr_CH", "en_US", "en_GB"):
            v = proposed.get(k)
            if v and str(v).strip():
                out.append(str(v).strip())
        for v in proposed.values():
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
    elif proposed:
        out.append(str(proposed).strip())
    return out or ["Rapport"]


def _copy_name_collides_existing(
    models: Any,
    db: str,
    uid: int,
    password: str,
    exclude_id: int,
    proposed: Any,
    *,
    root_for_sibling_check: int | None,
) -> bool:
    """True si un autre rapport porte déjà ce nom (recherche par langue + variantes même racine)."""
    # Ne pas utiliser fr_BE / fr_CA ici : contexte RPC → Odoo refuse les langues non activées sur la base.
    langs = ("fr_FR", "en_US")
    for s in _proposed_name_search_strings(proposed):
        for lang in langs:
            hits = execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "search",
                [[("id", "!=", exclude_id), ("name", "=", s)]],
                {"limit": 2, "context": {"lang": lang}},
            )
            if hits:
                return True
        hits_plain = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "search",
            [[("id", "!=", exclude_id), ("name", "=", s)]],
            {"limit": 2},
        )
        if hits_plain:
            return True

    prop_display = format_report_name(proposed).strip().lower()
    if prop_display and prop_display != "—" and root_for_sibling_check:
        sib = execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "search",
            [[("root_report_id", "=", root_for_sibling_check), ("id", "!=", exclude_id)]],
            {"limit": 500},
        )
        if sib:
            rows = execute_kw(
                models,
                db,
                uid,
                password,
                "account.report",
                "read",
                [sib],
                {"fields": ["name"]},
            )
            for r in rows:
                if format_report_name(r.get("name")).strip().lower() == prop_display:
                    return True
    return False


def _write_duplicate_unique_name(
    models: Any,
    db: str,
    uid: int,
    password: str,
    new_report_id: int,
    raw_source_name: Any,
    name_suffix: str,
    *,
    root_for_uniqueness: int | None,
) -> None:
    for i in range(50):
        suf = name_suffix if i == 0 else f"{name_suffix} ({i + 1})"
        proposed = _copy_report_display_name(raw_source_name, suf)
        if _copy_name_collides_existing(
            models,
            db,
            uid,
            password,
            new_report_id,
            proposed,
            root_for_sibling_check=root_for_uniqueness,
        ):
            continue
        execute_kw(
            models,
            db,
            uid,
            password,
            "account.report",
            "write",
            [[new_report_id], {"name": proposed}],
        )
        return
    raise ValueError(
        "Impossible d’attribuer un nom de rapport unique après 50 tentatives ; "
        "renommez manuellement dans Odoo."
    )


def duplicate_account_report(
    models: Any,
    db: str,
    uid: int,
    password: str,
    source_report_id: int,
    *,
    name_suffix: str = " — copie Senedoo",
    attach_to_root: bool = True,
) -> int:
    """
    Duplique un account.report (API ``copy``), puis renomme avec suffixe Senedoo.

    Par défaut, rattache la copie au même ``root_report_id`` racine que l’original (variante Odoo).
    Avec ``attach_to_root=False`` (balance 6 colonnes), la copie reste **autonome** : elle apparaît
    comme un rapport à part (menu Comptabilité / Analyse selon la version) et évite les effets de
    bord liés au schéma « racine » (ex. totaux trial balance Enterprise). Les options de filtre
    visibles sur le modèle source sont recopiées sur la copie.
    """
    rows = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "read",
        [[source_report_id]],
        {"fields": ["name"]},
    )
    if not rows:
        raise ValueError(f"Rapport comptable id={source_report_id} introuvable.")
    raw_name = rows[0].get("name")
    root_target = _ultimate_root_report_id(models, db, uid, password, source_report_id)

    new_res = execute_kw(
        models,
        db,
        uid,
        password,
        "account.report",
        "copy",
        [source_report_id],
        {},
    )
    if isinstance(new_res, dict) and new_res.get("id") is not None:
        new_id = int(new_res["id"])
    elif isinstance(new_res, (list, tuple)):
        new_id = int(new_res[0])
    else:
        new_id = int(new_res)

    root_for_unique: int | None = root_target
    if attach_to_root:
        _link_report_copy_to_root(models, db, uid, password, new_id, root_target)
    else:
        root_for_unique = None
        copy_account_report_options_from_source(
            models,
            db,
            uid,
            password,
            int(source_report_id),
            new_id,
        )
        if _account_report_has_field(models, db, uid, password, "root_report_id"):
            try:
                sa_vals: dict[str, Any] = {"root_report_id": False}
                if _account_report_has_field(
                    models, db, uid, password, "section_main_report_ids"
                ):
                    sa_vals["section_main_report_ids"] = [(5, 0, 0)]
                execute_kw(
                    models,
                    db,
                    uid,
                    password,
                    "account.report",
                    "write",
                    [[new_id], sa_vals],
                )
            except Exception:
                pass
    _write_duplicate_unique_name(
        models,
        db,
        uid,
        password,
        new_id,
        raw_name,
        name_suffix,
        root_for_uniqueness=root_for_unique,
    )
    return new_id
