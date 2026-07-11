"""Textual dashboard for cctokens.

Tabs: Today (+ live active session), Trends (30-day chart), Projects, All-time.
A timer re-runs the incremental scan every few seconds so the active session
and today's totals update live while Claude Code is running.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
)

from .storage import Store, Totals

REFRESH_SECONDS = 5.0


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(t: Totals) -> str:
    return (f"${t.cost:,.2f}+" if not t.cost_known else f"${t.cost:,.2f}")


def _utc_today() -> _dt.date:
    return _dt.datetime.now(_dt.timezone.utc).date()


_BREAKDOWN_COLS = ("", "Input", "Output", "Cache W", "Cache R", "Cost")


def _fill_breakdown(table: DataTable, label: str, rows: list[tuple[str, Totals]]) -> None:
    table.clear(columns=True)
    table.add_columns(label, *_BREAKDOWN_COLS[1:])
    for name, t in rows:
        table.add_row(
            name,
            _fmt_tokens(t.input_tokens),
            _fmt_tokens(t.output_tokens),
            _fmt_tokens(t.cache_creation_tokens),
            _fmt_tokens(t.cache_read_tokens),
            _fmt_cost(t),
        )


class CCTokensApp(App):
    CSS = """
    Screen { layout: vertical; }
    #summary { height: auto; padding: 1 2; background: $panel; }
    .panel-title { text-style: bold; color: $accent; padding: 1 0 0 0; }
    DataTable { height: auto; }
    Sparkline { height: 4; margin: 1 0; }
    #trend-caption { color: $text-muted; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("1", "tab('today')", "Today"),
        ("2", "tab('trends')", "Trends"),
        ("3", "tab('projects')", "Projects"),
        ("4", "tab('alltime')", "All-time"),
    ]

    def __init__(self, projects_dir: Path) -> None:
        super().__init__()
        self.projects_dir = projects_dir
        self.store = Store()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="summary")
        with TabbedContent(initial="today"):
            with TabPane("Today", id="today"):
                yield Static(id="today-session", classes="panel-title")
                yield DataTable(id="today-models")
            with TabPane("Trends", id="trends"):
                yield Static("Daily cost — last 30 days", classes="panel-title")
                yield Sparkline([0], id="trend-cost")
                yield Static(id="trend-caption")
                yield DataTable(id="trend-table")
            with TabPane("Projects", id="projects"):
                yield Static("Usage by project (all time)", classes="panel-title")
                yield DataTable(id="projects-table")
            with TabPane("All-time", id="alltime"):
                yield Static(id="alltime-summary", classes="panel-title")
                with Horizontal():
                    with Vertical():
                        yield Static("By year", classes="panel-title")
                        yield DataTable(id="year-table")
                    with Vertical():
                        yield Static("By model", classes="panel-title")
                        yield DataTable(id="model-table")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "cctokens"
        self.sub_title = "Claude Code usage"
        self.refresh_data()
        self.set_interval(REFRESH_SECONDS, self.refresh_data)

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def refresh_data(self) -> None:
        # Incremental scan — cheap when nothing changed.
        self.store.sync(self.projects_dir)

        total = self.store.totals_all()
        day = _utc_today().isoformat()
        today_t = self.store.totals_for_day(day)
        self.query_one("#summary", Static).update(
            f"[b]All-time[/] {_fmt_tokens(total.total_tokens)} tok · "
            f"[green]{_fmt_cost(total)}[/]      "
            f"[b]Today[/] {_fmt_tokens(today_t.total_tokens)} tok · "
            f"[green]{_fmt_cost(today_t)}[/]      "
            f"[dim](r: refresh · auto every {int(REFRESH_SECONDS)}s)[/]"
        )

        # Today tab
        session = self.store.active_session()
        if session:
            sid, st = session
            self.query_one("#today-session", Static).update(
                f"● Active session …{sid[-8:]}  ·  "
                f"{_fmt_tokens(st.total_tokens)} tok  ·  [green]{_fmt_cost(st)}[/]"
            )
        else:
            self.query_one("#today-session", Static).update("No sessions recorded yet.")
        _fill_breakdown(
            self.query_one("#today-models", DataTable),
            "Model",
            self.store.by_model("WHERE day = ?", (day,)),
        )

        # Trends tab
        series = self.store.daily_series(30)
        spark = self.query_one("#trend-cost", Sparkline)
        spark.data = [c for _, c, _ in series] or [0]
        if series:
            peak = max(series, key=lambda r: r[1])
            self.query_one("#trend-caption", Static).update(
                f"peak [green]${peak[1]:,.2f}[/] on {peak[0]} · "
                f"{len(series)} active day(s)"
            )
        trend_tbl = self.query_one("#trend-table", DataTable)
        trend_tbl.clear(columns=True)
        trend_tbl.add_columns("Day", "Tokens", "Cost")
        for d, cost, tok in reversed(series):
            trend_tbl.add_row(d, _fmt_tokens(tok), f"${cost:,.2f}")

        # Projects tab
        _fill_breakdown(
            self.query_one("#projects-table", DataTable),
            "Project",
            self.store.by_project(),
        )

        # All-time tab
        self.query_one("#alltime-summary", Static).update(
            f"All-time: {_fmt_tokens(total.total_tokens)} tokens · "
            f"[green]{_fmt_cost(total)}[/]"
        )
        _fill_breakdown(self.query_one("#year-table", DataTable), "Year", self.store.by_year())
        _fill_breakdown(self.query_one("#model-table", DataTable), "Model", self.store.by_model())

    def on_unmount(self) -> None:
        self.store.close()


def run_tui(projects_dir: Path) -> None:
    CCTokensApp(projects_dir).run()
