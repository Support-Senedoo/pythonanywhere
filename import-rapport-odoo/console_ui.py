# -*- coding: utf-8 -*-
"""Habillage terminal : cadres, couleurs optionnelles (pip install colorama)."""
from __future__ import annotations

import shutil
import sys
from typing import TextIO

try:
    from colorama import Fore, Style, init as _colorama_init

    _colorama_init(autoreset=True)
    _COLOR = True
except ImportError:

    class _Fore:
        CYAN = GREEN = YELLOW = RED = BLUE = MAGENTA = LIGHTBLACK_EX = WHITE = ""

    class _Style:
        BRIGHT = RESET_ALL = ""
        DIM = ""

    Fore = _Fore()  # type: ignore[misc, assignment]
    Style = _Style()  # type: ignore[misc, assignment]
    _COLOR = False


def term_width() -> int:
    try:
        return max(48, min(78, shutil.get_terminal_size(fallback=(80, 24)).columns - 2))
    except OSError:
        return 72


def hr(ch: str = "─", stream: TextIO = sys.stdout) -> None:
    print(ch * term_width(), file=stream)


def banner(title: str, subtitle: str | None = None) -> None:
    w = term_width()
    print()
    print(f"{Fore.CYAN}╔{'═' * (w - 2)}╗{Style.RESET_ALL}")
    print(f"{Fore.CYAN}║{Style.RESET_ALL}  {Style.BRIGHT}{title}{Style.RESET_ALL}")
    if subtitle:
        print(f"{Fore.CYAN}║{Style.RESET_ALL}  {Style.DIM}{subtitle}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}╚{'═' * (w - 2)}╝{Style.RESET_ALL}")
    print()


def section(title: str) -> None:
    print()
    print(f"{Fore.GREEN}▶ {Style.BRIGHT}{title}{Style.RESET_ALL}")
    hr(Fore.GREEN + "─" + Style.RESET_ALL if _COLOR else "─")


def muted(text: str) -> None:
    print(f"{Style.DIM}{text}{Style.RESET_ALL}")


def info_lines(text: str) -> None:
    for line in text.strip().split("\n"):
        print(f"  {Fore.BLUE}·{Style.RESET_ALL} {line}")


def success(text: str) -> None:
    sym = "✓ " if _COLOR else "[OK] "
    print(f"{Fore.GREEN}{sym}{text}{Style.RESET_ALL}")


def warn(text: str) -> None:
    sym = "⚠ " if _COLOR else "[!] "
    print(f"{Fore.YELLOW}{sym}{text}{Style.RESET_ALL}")


def error(text: str) -> None:
    sym = "✗ " if _COLOR else "[Erreur] "
    print(f"{Fore.RED}{sym}{text}{Style.RESET_ALL}", file=sys.stderr)


def ask(text: str, default: str | None = None) -> str:
    if default is not None and default != "":
        p = f"{Fore.MAGENTA}→{Style.RESET_ALL} {text} {Style.DIM}[{default}]{Style.RESET_ALL} : "
    else:
        p = f"{Fore.MAGENTA}→{Style.RESET_ALL} {text} : "
    s = input(p).strip()
    if not s and default is not None:
        return default
    return s


def menu(items: list[tuple[str, str]]) -> None:
    """Affiche [clé] description."""
    print()
    for key, desc in items:
        print(f"  {Fore.CYAN}{Style.BRIGHT}[{key}]{Style.RESET_ALL}  {desc}")
    print()


def table_reports(rows: list[tuple[int, int, str, str]]) -> None:
    """(index, id_odoo, libellé, chart_template)"""
    print()
    hr()
    hdr = f"  {'N°':>4}  {'Id':>6}  {'Libellé':<42}  {'Plan':<12}"
    print(Style.BRIGHT + hdr + Style.RESET_ALL)
    hr()
    for idx, oid, label, chart in rows:
        lab = (label[:42] + "…") if len(label) > 43 else label
        ch = (chart[:12] + "…") if len(chart) > 12 else chart
        print(f"  {idx:4}  {oid:6}  {lab:<42}  {ch:<12}")
    hr()
    print()
