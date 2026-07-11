"""Typer CLI for cctokens."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import ingest
from .storage import Store, Totals

app = typer.Typer(
    add_completion=False,
    help="Rich CLI + TUI for Claude Code token usage and cost.",
    no_args_is_help=False,
)
console = Console()

_ProjectsDir = typer.Option(
    None,
    "--projects-dir",
    help="Override the Claude projects directory (default ~/.claude/projects).",
)


def _projects_dir(override: Optional[Path]) -> Path:
    return override or ingest.DEFAULT_PROJECTS_DIR


def _utc_today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(t: Totals) -> str:
    if not t.cost_known:
        return f"${t.cost:,.2f}+"  # '+' flags unknown-model rows excluded
    return f"${t.cost:,.2f}"


def _open_store(projects_dir: Optional[Path]) -> Store:
    store = Store()
    store.sync(_projects_dir(projects_dir))
    return store


def _render_breakdown(title: str, rows: list[tuple[str, Totals]], label: str) -> Table:
    table = Table(title=title, header_style="bold cyan", expand=False)
    table.add_column(label, style="bold")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cache W", justify="right")
    table.add_column("Cache R", justify="right")
    table.add_column("Cost", justify="right", style="green")
    for name, t in rows:
        table.add_row(
            name,
            _fmt_tokens(t.input_tokens),
            _fmt_tokens(t.output_tokens),
            _fmt_tokens(t.cache_creation_tokens),
            _fmt_tokens(t.cache_read_tokens),
            _fmt_cost(t),
        )
    return table


def _summary_line(t: Totals) -> str:
    return (
        f"[bold]{_fmt_tokens(t.total_tokens)}[/] tokens  ·  "
        f"in {_fmt_tokens(t.input_tokens)} · out {_fmt_tokens(t.output_tokens)} · "
        f"cache {_fmt_tokens(t.cache_creation_tokens + t.cache_read_tokens)}  ·  "
        f"[green]{_fmt_cost(t)}[/]"
    )


@app.command()
def scan(projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """Force a full re-ingest of all transcripts."""
    store = Store()
    with console.status("Scanning transcripts…"):
        n = store.sync(_projects_dir(projects_dir), force=True)
    total = store.totals_all()
    store.close()
    console.print(f"Scanned [bold]{n}[/] transcript file(s).")
    console.print(_summary_line(total))


@app.command()
def today(projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """Today's usage, broken down by model."""
    store = _open_store(projects_dir)
    day = _utc_today().isoformat()
    total = store.totals_for_day(day)
    rows = store.by_model("WHERE day = ?", (day,))
    store.close()
    console.print(f"[bold]Today[/] ({day} UTC): {_summary_line(total)}")
    if rows:
        console.print(_render_breakdown("By model", rows, "Model"))


@app.command()
def week(projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """Usage over the last 7 days."""
    _range_report(projects_dir, 7, "Last 7 days")


@app.command()
def month(projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """Usage over the last 30 days."""
    _range_report(projects_dir, 30, "Last 30 days")


def _range_report(projects_dir: Optional[Path], days: int, title: str) -> None:
    store = _open_store(projects_dir)
    start = (_utc_today() - _dt.timedelta(days=days - 1)).isoformat()
    total = store.totals_since(start)
    rows = store.by_model("WHERE day >= ?", (start,))
    store.close()
    console.print(f"[bold]{title}[/] (since {start} UTC): {_summary_line(total)}")
    if rows:
        console.print(_render_breakdown("By model", rows, "Model"))


@app.command()
def projects(projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """All-time usage broken down by project."""
    store = _open_store(projects_dir)
    rows = store.by_project()
    store.close()
    if not rows:
        console.print("No usage found.")
        return
    console.print(_render_breakdown("Usage by project (all time)", rows, "Project"))


@app.command()
def stats(projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """All-time totals plus a per-year and per-model rollup."""
    store = _open_store(projects_dir)
    total = store.totals_all()
    years = store.by_year()
    models = store.by_model()
    store.close()
    console.print(f"[bold]All-time[/]: {_summary_line(total)}\n")
    if years:
        console.print(_render_breakdown("By year", years, "Year"))
    if models:
        console.print(_render_breakdown("By model", models, "Model"))


@app.command()
def tui(projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """Launch the rich interactive dashboard."""
    from .tui import run_tui

    run_tui(_projects_dir(projects_dir))


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context, projects_dir: Optional[Path] = _ProjectsDir) -> None:
    """With no subcommand, launch the TUI."""
    if ctx.invoked_subcommand is None:
        from .tui import run_tui

        run_tui(_projects_dir(projects_dir))


if __name__ == "__main__":
    app()
