#!/usr/bin/env python3
"""
Capture le rendu d’un rapport comptable Odoo affiché dans le navigateur (tableaux HTML),
avec **session persistante** : vous vous connectez **une seule fois**, l’état est enregistré
dans un fichier local (cookies + storage), les lancements suivants réutilisent cette session.

Objectif : éviter les allers-retours « à l’aveugle » entre l’interface et le code : export JSON
des tableaux visibles pour analyse / comparaison avec le calcul API (ex. ``project_pl_analytic_report.py``).

**Non prévu pour PythonAnywhere** : à exécuter sur votre PC (Windows / Linux / macOS).

Installation (une fois) :
    pip install -r requirements-capture-browser.txt
    playwright install chromium

Étape 1 — enregistrer la session (navigateur visible) :
    python capture_odoo_report_view.py --init --base-url https://VOTRE_BASE.odoo.com

    Connectez-vous à Odoo, attendez le backend (menu Comptabilité visible), puis dans le terminal
    appuyez sur Entrée. Un fichier ``odoo_browser_state.json`` est créé (voir ``--state``).

Étape 2 — capturer un rapport déjà ouvert ou via URL complète :
    python capture_odoo_report_view.py \\
        --base-url https://VOTRE_BASE.odoo.com \\
        --report-url "https://VOTRE_BASE.odoo.com/web#action=...&model=account.report&view_type=form"

    Ou coller l’URL copiée depuis la barre d’adresse du navigateur après avoir ouvert le rapport.

Sortie (défaut ``odoo_report_capture.json``) : structure ``tables[]`` avec lignes texte,
plus option ``--html`` pour sauver le HTML du corps de page (debug sélecteurs).

Sécurité : ne commitez jamais ``odoo_browser_state.json`` (contient session). Fichier listé dans ``.gitignore``.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_STATE = _SCRIPT_DIR / "odoo_browser_state.json"
_DEFAULT_OUT = _SCRIPT_DIR / "odoo_report_capture.json"


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: WPS433
    except ImportError as e:
        print(
            "Playwright n'est pas installé. Sur cette machine :\n"
            "  pip install -r requirements-capture-browser.txt\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        raise SystemExit(2) from e
    return sync_playwright


def _extract_tables_from_frame(handle) -> list[dict[str, object]]:
    """Extrait les <table> d'un frame Playwright."""
    tables_out: list[dict[str, object]] = []
    try:
        count = handle.locator("table").count()
    except Exception:
        return tables_out
    for ti in range(count):
        table = handle.locator("table").nth(ti)
        rows_raw = table.evaluate(
            """(el) => {
                const rows = el.querySelectorAll('tr');
                return Array.from(rows).map(r => {
                    const cells = r.querySelectorAll('th, td');
                    return Array.from(cells).map(c => (c.innerText || '').trim().replace(/\\s+/g, ' '));
                });
            }"""
        )
        if not rows_raw:
            continue
        tables_out.append(
            {
                "index": ti,
                "row_count": len(rows_raw),
                "rows": rows_raw,
            }
        )
    return tables_out


def _extract_tables_from_page(page) -> list[dict[str, object]]:
    """Extrait tous les <table> (frame principal puis iframes si vide)."""
    seen: list[dict[str, object]] = _extract_tables_from_frame(page)
    if seen:
        return seen

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            got = _extract_tables_from_frame(frame)
        except Exception:
            continue
        if got:
            for g in got:
                g["frame_url"] = frame.url
            return got

    # Repli : texte brut
    fallback: list[dict[str, object]] = []
    try:
        main = page.locator("main, .o_content, .o_action_manager").first
        if main.count() > 0:
            text = main.inner_text(timeout=15_000)
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            fallback.append(
                {
                    "index": 0,
                    "row_count": len(lines),
                    "rows": [[ln] for ln in lines],
                    "note": "fallback_inner_text_no_table",
                }
            )
    except Exception:
        pass
    return fallback


def cmd_init(base_url: str, state_path: Path) -> None:
    sync_playwright = _require_playwright()
    base_url = base_url.rstrip("/")
    print(f"Ouverture du navigateur — connectez-vous à {base_url}")
    print("Quand le backend Odoo est prêt (menu visible), revenez ici et appuyez sur Entrée.")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.goto(base_url, wait_until="domcontentloaded", timeout=120_000)
        try:
            input()
        except EOFError:
            print("Entrée impossible (non interactif). Utilisez un terminal interactif.", file=sys.stderr)
            sys.exit(1)
        context.storage_state(path=str(state_path))
        browser.close()
    print(f"Session enregistrée : {state_path.resolve()}")


def cmd_capture(
    base_url: str,
    report_url: str,
    state_path: Path,
    out_path: Path,
    html_path: Path | None,
    timeout_ms: int,
    headless: bool,
    screenshot_path: Path | None,
) -> None:
    sync_playwright = _require_playwright()
    if not state_path.is_file():
        print(
            f"Fichier d'état absent : {state_path}\n"
            f"Lancez d'abord : python {Path(__file__).name} --init --base-url {base_url!r}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=str(state_path),
            viewport={"width": 1400, "height": 900},
            ignore_https_errors=True,
        )
        page = context.new_page()
        dest = report_url.strip() if report_url else base_url.rstrip("/")
        page.goto(dest, wait_until="networkidle", timeout=timeout_ms)
        # Laisser le temps aux widgets OWL / rapport comptable
        page.wait_for_timeout(3_000)
        try:
            page.wait_for_selector("table, .o_account_reports_page, .o_content", timeout=min(60_000, timeout_ms))
        except Exception:
            pass

        tables = _extract_tables_from_page(page)
        payload: dict[str, object] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "url": page.url,
            "requested_url": dest,
            "tables": tables,
        }

        if html_path:
            try:
                html = page.content()
                html_path.write_text(html, encoding="utf-8")
                payload["html_saved"] = str(html_path.resolve())
            except Exception as e:
                payload["html_error"] = str(e)

        if screenshot_path:
            page.screenshot(path=str(screenshot_path), full_page=True)
            payload["screenshot"] = str(screenshot_path.resolve())

        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        browser.close()

    print(f"OK — {len(tables)} tableau(x) exporté(s) vers {out_path.resolve()}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Capture les tableaux du rapport Odoo (session Playwright persistée)."
    )
    p.add_argument("--init", action="store_true", help="Premier lancement : connexion manuelle puis sauvegarde session.")
    p.add_argument("--base-url", required=True, help="URL de base Odoo, ex. https://xxx.odoo.com")
    p.add_argument(
        "--report-url",
        default="",
        help="URL complète du rapport (barre d'adresse). Si vide, reste sur la page d'accueil après chargement session.",
    )
    p.add_argument("--state", type=Path, default=_DEFAULT_STATE, help="Fichier JSON session Playwright.")
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Fichier JSON de sortie.")
    p.add_argument("--html", type=Path, default=None, help="Optionnel : sauver le HTML de la page pour debug.")
    p.add_argument("--screenshot", type=Path, default=None, help="Optionnel : capture pleine page PNG.")
    p.add_argument("--timeout-ms", type=int, default=120_000, help="Timeout navigation / attente.")
    p.add_argument("--headless", action="store_true", help="Sans fenêtre (défaut si --init non utilisé).")
    args = p.parse_args()

    base = args.base_url.rstrip("/")

    if args.init:
        cmd_init(base, args.state)
        return

    cmd_capture(
        base_url=base,
        report_url=args.report_url,
        state_path=args.state,
        out_path=args.out,
        html_path=args.html,
        timeout_ms=max(30_000, args.timeout_ms),
        headless=bool(args.headless),
        screenshot_path=args.screenshot,
    )


if __name__ == "__main__":
    main()
