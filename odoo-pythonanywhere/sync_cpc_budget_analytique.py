"""
Synchronise les montants de budget analytique vers account.report.external.value
pour le rapport CPC SYSCOHADA — Budget Analytique (Senedoo).

PROBLÈME RÉSOLU :
  Sur Odoo SaaS v16-v19, engine='budget' est masqué quand le filtre analytique est
  actif. Solution : utiliser engine='external' dans le rapport + pré-calculer les
  montants ici et les stocker dans account.report.external.value.

UTILISATION :
  Appelé depuis la Toolbox Flask (web_app/blueprints/staff.py) via l'action
  'sync_cpc_budget_analytique'. L'utilisateur fournit : compte analytique, budget,
  période. Les valeurs sont recalculées et remplacent les précédentes.

ALGORITHME :
  Pour chaque ligne CPC de détail (TA, RA, RB, TB, TC…) :
    1. Récupérer les préfixes de compte depuis l'expression 'balance' (account_codes)
    2. Pour chaque ligne de budget (crossovered.budget.lines) du budget sélectionné,
       vérifier si la position budgétaire (account.budget.post) couvre des comptes
       qui correspondent aux préfixes CPC
    3. Si oui, ajouter le planned_amount entier à cette ligne CPC
    4. Stocker le total dans account.report.external.value

  Les lignes de totaux (codes commençant par X) utilisent engine='aggregation'
  et se calculent automatiquement depuis les lignes de détail — pas de stockage.

Compatible Odoo v16-v19 (gère analytic_account_id ET analytic_distribution).
"""
from __future__ import annotations

from typing import Any

from personalize_syscohada_detail import execute_kw


def _ek(models: Any, db: str, uid: int, password: str,
        model: str, method: str, args: list | None = None,
        kw: dict | None = None) -> Any:
    return execute_kw(models, db, uid, password, model, method, args or [], kw)


def list_crossovered_budgets(
    models: Any, db: str, uid: int, password: str
) -> list[dict]:
    """
    Retourne la liste des budgets (crossovered.budget) disponibles.
    Retourne [] si le module account_budget n'est pas installé.
    """
    try:
        rows = _ek(models, db, uid, password, "crossovered.budget", "search_read",
                   [[]],
                   {"fields": ["id", "name", "state"], "limit": 100,
                    "order": "name asc"})
        return rows or []
    except Exception:
        return []


def _filter_budget_lines_by_analytic(
    budget_lines: list[dict], analytic_account_id: int
) -> list[dict]:
    """
    Filtre les lignes de budget pour ne garder que celles liées au compte analytique.
    Gère les deux modèles Odoo :
      - v16/v17 (selon install) : champ analytic_account_id (Many2one)
      - v17+/v19               : champ analytic_distribution (dict {str(id): pct})
    """
    if not analytic_account_id:
        return budget_lines

    filtered = []
    ana_str = str(analytic_account_id)
    for bl in budget_lines:
        # Cas 1 : analytic_account_id classique
        aid_field = bl.get("analytic_account_id")
        if aid_field:
            ref_id = aid_field[0] if isinstance(aid_field, (list, tuple)) else aid_field
            if int(ref_id) == analytic_account_id:
                filtered.append(bl)
                continue
        # Cas 2 : analytic_distribution (v17+)
        dist = bl.get("analytic_distribution")
        if isinstance(dist, dict) and ana_str in dist:
            filtered.append(bl)
    return filtered


def _build_position_account_codes(
    models: Any, db: str, uid: int, password: str,
    position_ids: list[int]
) -> dict[int, list[str]]:
    """
    Construit un mapping position_id → [account_codes] en batch.
    """
    if not position_ids:
        return {}

    result: dict[int, list[str]] = {}
    try:
        posts = _ek(models, db, uid, password, "account.budget.post", "read",
                    [position_ids], {"fields": ["id", "account_ids"]})
        all_acc_ids: list[int] = []
        pos_acc_map: dict[int, list[int]] = {}
        for p in posts:
            acc_ids = p.get("account_ids") or []
            pos_acc_map[p["id"]] = acc_ids
            all_acc_ids.extend(acc_ids)

        # Récupérer tous les codes de comptes en une seule requête
        if all_acc_ids:
            acc_data = _ek(models, db, uid, password, "account.account", "read",
                           [list(set(all_acc_ids))], {"fields": ["id", "code"]})
            acc_code_by_id = {a["id"]: a["code"] for a in acc_data}
        else:
            acc_code_by_id = {}

        for pos_id, acc_ids in pos_acc_map.items():
            result[pos_id] = [acc_code_by_id[aid] for aid in acc_ids
                              if aid in acc_code_by_id]
    except Exception:
        pass
    return result


def sync_cpc_budget_to_external_values(
    models: Any,
    db: str,
    uid: int,
    password: str,
    report_id: int,
    analytic_account_id: int,
    budget_id: int,
    date_from: str,
    date_to: str,
) -> dict[str, Any]:
    """
    Calcule les montants de budget par ligne CPC et les stocke dans
    account.report.external.value (lus par engine='external').

    Paramètres :
        report_id           : ID du rapport account.report CPC Budget Analytique
        analytic_account_id : ID du compte analytique (0 = sans filtre analytique)
        budget_id           : ID du budget (crossovered.budget)
        date_from, date_to  : période au format 'YYYY-MM-DD'

    Retourne :
        stored      : nombre de valeurs stockées
        skipped     : lignes sans budget correspondant
        errors      : liste d'erreurs éventuelles
        lines_found : nombre de lignes CPC de détail trouvées
        budget_lines_count : nombre de lignes de budget utilisées
    """
    errors: list[str] = []
    stored = 0
    skipped = 0

    # ── 1. Lignes CPC de détail (hors totaux X*) ─────────────────────────────
    all_report_lines = _ek(
        models, db, uid, password, "account.report.line", "search_read",
        [[["report_id", "=", report_id], ["code", "!=", False]]],
        {"fields": ["id", "code", "name"]},
    )
    detail_lines = [
        rl for rl in (all_report_lines or [])
        if not (rl.get("code") or "").startswith("X")
    ]
    if not detail_lines:
        return {
            "stored": 0, "skipped": 0, "errors": ["Aucune ligne CPC trouvée dans ce rapport."],
            "lines_found": 0, "budget_lines_count": 0,
        }

    # ── 2. Expressions account_codes pour chaque ligne de détail ─────────────
    line_ids = [rl["id"] for rl in detail_lines]
    all_exprs = _ek(
        models, db, uid, password, "account.report.expression", "search_read",
        [[["report_line_id", "in", line_ids], ["label", "=", "balance"],
          ["engine", "=", "account_codes"]]],
        {"fields": ["report_line_id", "formula"]},
    ) or []
    formula_by_line: dict[int, str] = {
        e["report_line_id"][0] if isinstance(e["report_line_id"], (list, tuple))
        else int(e["report_line_id"]): e["formula"]
        for e in all_exprs
    }

    # ── 3. Lignes de budget (crossovered.budget.lines) ───────────────────────
    # Tentative avec filtre analytique v16 dans le domaine
    fields_blines = ["id", "general_budget_id", "planned_amount",
                     "date_from", "date_to",
                     "analytic_account_id", "analytic_distribution"]
    try:
        raw_lines = _ek(
            models, db, uid, password, "crossovered.budget.lines", "search_read",
            [[["crossovered_budget_id", "=", budget_id]]],
            {"fields": fields_blines, "limit": 500},
        ) or []
    except Exception:
        # Fallback sans analytic_distribution (champ peut ne pas exister)
        try:
            raw_lines = _ek(
                models, db, uid, password, "crossovered.budget.lines", "search_read",
                [[["crossovered_budget_id", "=", budget_id]]],
                {"fields": ["id", "general_budget_id", "planned_amount",
                            "date_from", "date_to", "analytic_account_id"],
                 "limit": 500},
            ) or []
        except Exception as e:
            return {
                "stored": 0, "skipped": len(detail_lines),
                "errors": [f"Impossible de lire les lignes de budget : {e}"],
                "lines_found": len(detail_lines), "budget_lines_count": 0,
            }

    # Filtre période (date de la ligne dans ou chevauche la période)
    def _in_period(bl: dict) -> bool:
        df = bl.get("date_from") or ""
        dt = bl.get("date_to") or ""
        if not df or not dt:
            return True
        return df <= date_to and dt >= date_from

    period_lines = [bl for bl in raw_lines if _in_period(bl)]

    # Filtre analytique (Python, gère v16 + v17+)
    if analytic_account_id:
        budget_lines = _filter_budget_lines_by_analytic(period_lines, analytic_account_id)
        if not budget_lines:
            # Aucune ligne avec ce compte analytique → utiliser toutes les lignes
            # (cas où le budget n'a pas de ventilation analytique)
            budget_lines = period_lines
            errors.append(
                "Aucune ligne de budget directement liée au compte analytique — "
                "montants pris globalement (toutes les lignes du budget)."
            )
    else:
        budget_lines = period_lines

    if not budget_lines:
        return {
            "stored": 0, "skipped": len(detail_lines),
            "errors": ["Aucune ligne de budget trouvée pour ce budget et cette période."],
            "lines_found": len(detail_lines), "budget_lines_count": 0,
        }

    # ── 4. Construire mapping position → codes de comptes ────────────────────
    position_ids = list({
        (bl["general_budget_id"][0]
         if isinstance(bl["general_budget_id"], (list, tuple))
         else bl.get("general_budget_id"))
        for bl in budget_lines
        if bl.get("general_budget_id")
    })
    position_ids = [p for p in position_ids if p]
    pos_codes_map = _build_position_account_codes(
        models, db, uid, password, position_ids
    )

    # ── 5. Pour chaque ligne CPC, calculer le montant budget ─────────────────
    # Algorithme : pour chaque ligne de budget, si sa position couvre des comptes
    # qui correspondent aux préfixes de la ligne CPC → ajouter le planned_amount.
    # On ne double-compte pas la même ligne de budget pour la même ligne CPC.
    line_budgets: dict[int, float] = {}  # report_line_id → amount

    for rl in detail_lines:
        line_id = rl["id"]
        formula = formula_by_line.get(line_id, "")
        if not formula:
            skipped += 1
            continue

        prefixes = [p.strip().lstrip("^") for p in formula.split(",") if p.strip()]
        total = 0.0

        for bl in budget_lines:
            pos_ref = bl.get("general_budget_id")
            pos_id = (pos_ref[0] if isinstance(pos_ref, (list, tuple)) else pos_ref)
            if not pos_id:
                continue
            pos_codes = pos_codes_map.get(pos_id, [])
            # Vérifier si au moins un compte de la position correspond à un préfixe CPC
            matched = any(
                acc_code.startswith(pfx)
                for pfx in prefixes
                for acc_code in pos_codes
            )
            if matched:
                total += float(bl.get("planned_amount") or 0.0)

        line_budgets[line_id] = total
        if total == 0:
            skipped += 1

    # ── 6. Supprimer les anciennes external.value pour ce rapport ─────────────
    old_ext = _ek(
        models, db, uid, password, "account.report.external.value", "search",
        [[["report_line_id", "in", line_ids]]],
    )
    if old_ext:
        try:
            _ek(models, db, uid, password, "account.report.external.value",
                "unlink", [old_ext])
        except Exception as e:
            errors.append(f"Nettoyage external.value : {e}")

    # ── 7. Créer les nouvelles external.value ─────────────────────────────────
    company_id = _ek(models, db, uid, password, "res.company", "search", [[]])[0]
    text_note = f"budget={budget_id} / analytique={analytic_account_id or 'all'}"

    for rl in detail_lines:
        line_id = rl["id"]
        amount = line_budgets.get(line_id, 0.0)
        if amount == 0:
            continue
        try:
            _ek(models, db, uid, password, "account.report.external.value", "create",
                [{
                    "report_line_id": line_id,
                    "value":          amount,
                    "date":           date_to,
                    "company_id":     company_id,
                    "text_value":     text_note,
                    "target_move":    "posted",
                }])
            stored += 1
        except Exception as e:
            errors.append(f"Ligne {rl.get('code', line_id)} : {e}")
            skipped += 1

    return {
        "stored":             stored,
        "skipped":            skipped,
        "errors":             errors,
        "lines_found":        len(detail_lines),
        "budget_lines_count": len(budget_lines),
    }
