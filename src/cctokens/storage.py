"""SQLite cache + queries for Claude Code usage.

The DB lives at ``~/.claude/cctokens.db`` (distinct from the reference tool's
``usage.db`` so both coexist). Ingestion is incremental: a transcript is only
re-parsed when its (size, mtime) changes. Rows are deduped on ``request_id``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import ingest, pricing

DEFAULT_DB_PATH = Path.home() / ".claude" / "cctokens.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    request_id            TEXT PRIMARY KEY,
    ts                    TEXT NOT NULL,          -- ISO-8601 UTC
    day                   TEXT NOT NULL,          -- YYYY-MM-DD (UTC)
    year                  TEXT NOT NULL,          -- YYYY (UTC)
    model                 TEXT,
    project               TEXT NOT NULL,
    session_id            TEXT,
    input_tokens          INTEGER NOT NULL,
    output_tokens         INTEGER NOT NULL,
    cache_creation_tokens INTEGER NOT NULL,
    cache_read_tokens     INTEGER NOT NULL,
    cache_creation_1h     INTEGER NOT NULL,
    cache_creation_5m     INTEGER NOT NULL,
    cost                  REAL                    -- NULL = unknown model
);
CREATE INDEX IF NOT EXISTS idx_usage_day ON usage(day);
CREATE INDEX IF NOT EXISTS idx_usage_project ON usage(project);
CREATE INDEX IF NOT EXISTS idx_usage_session ON usage(session_id);

CREATE TABLE IF NOT EXISTS scanned_files (
    path  TEXT PRIMARY KEY,
    size  INTEGER NOT NULL,
    mtime REAL NOT NULL
);
"""


@dataclass
class Totals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0
    cost_known: bool = True  # False once any unknown-model row is folded in

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


class Store:
    """Owns the SQLite connection, ingestion, and all aggregate queries."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- ingestion ----------------------------------------------------

    def sync(self, projects_dir: Path, *, force: bool = False) -> int:
        """Ingest new/changed transcripts. Returns the number of files parsed."""
        known = {
            r["path"]: (r["size"], r["mtime"])
            for r in self.conn.execute("SELECT path, size, mtime FROM scanned_files")
        }
        parsed = 0
        for stat in ingest.iter_transcripts(projects_dir):
            key = str(stat.path)
            if not force and known.get(key) == (stat.size, stat.mtime):
                continue
            self._ingest_file(stat)
            parsed += 1
        self.conn.commit()
        return parsed

    def _ingest_file(self, stat: ingest.TranscriptStat) -> None:
        rows = []
        for row in ingest.iter_usage_rows(stat.path):
            day = row.timestamp[:10]
            year = row.timestamp[:4]
            cost = pricing.cost_for(
                row.model,
                row.input_tokens,
                row.output_tokens,
                row.cache_creation_tokens,
                row.cache_read_tokens,
                row.cache_creation_1h,
                row.cache_creation_5m,
            )
            rows.append(
                (
                    row.request_id, row.timestamp, day, year, row.model,
                    row.project, row.session_id, row.input_tokens,
                    row.output_tokens, row.cache_creation_tokens,
                    row.cache_read_tokens, row.cache_creation_1h,
                    row.cache_creation_5m, cost,
                )
            )
        # INSERT OR IGNORE: a request_id seen before (in this or another file)
        # is skipped — the dedup invariant in the module docstring.
        self.conn.executemany(
            """
            INSERT OR IGNORE INTO usage (
                request_id, ts, day, year, model, project, session_id,
                input_tokens, output_tokens, cache_creation_tokens,
                cache_read_tokens, cache_creation_1h, cache_creation_5m, cost
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO scanned_files (path, size, mtime) VALUES (?,?,?)",
            (str(stat.path), stat.size, stat.mtime),
        )

    # ---- queries ------------------------------------------------------

    def _aggregate(self, where: str = "", params: tuple = ()) -> Totals:
        sql = f"""
            SELECT
                COALESCE(SUM(input_tokens),0) AS i,
                COALESCE(SUM(output_tokens),0) AS o,
                COALESCE(SUM(cache_creation_tokens),0) AS cc,
                COALESCE(SUM(cache_read_tokens),0) AS cr,
                COALESCE(SUM(cost),0) AS cost,
                SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unknown
            FROM usage {where}
        """
        r = self.conn.execute(sql, params).fetchone()
        return Totals(
            input_tokens=r["i"], output_tokens=r["o"],
            cache_creation_tokens=r["cc"], cache_read_tokens=r["cr"],
            cost=r["cost"] or 0.0, cost_known=(r["unknown"] or 0) == 0,
        )

    def totals_for_day(self, day: str) -> Totals:
        return self._aggregate("WHERE day = ?", (day,))

    def totals_since(self, day: str) -> Totals:
        return self._aggregate("WHERE day >= ?", (day,))

    def totals_all(self) -> Totals:
        return self._aggregate()

    def by_model(self, where: str = "", params: tuple = ()) -> list[tuple[str, Totals]]:
        sql = f"""
            SELECT model,
                COALESCE(SUM(input_tokens),0) AS i,
                COALESCE(SUM(output_tokens),0) AS o,
                COALESCE(SUM(cache_creation_tokens),0) AS cc,
                COALESCE(SUM(cache_read_tokens),0) AS cr,
                COALESCE(SUM(cost),0) AS cost,
                SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unknown
            FROM usage {where}
            GROUP BY model ORDER BY cost DESC
        """
        out = []
        for r in self.conn.execute(sql, params):
            out.append((
                r["model"] or "unknown",
                Totals(r["i"], r["o"], r["cc"], r["cr"], r["cost"] or 0.0,
                       (r["unknown"] or 0) == 0),
            ))
        return out

    def by_project(self, where: str = "", params: tuple = ()) -> list[tuple[str, Totals]]:
        sql = f"""
            SELECT project,
                COALESCE(SUM(input_tokens),0) AS i,
                COALESCE(SUM(output_tokens),0) AS o,
                COALESCE(SUM(cache_creation_tokens),0) AS cc,
                COALESCE(SUM(cache_read_tokens),0) AS cr,
                COALESCE(SUM(cost),0) AS cost,
                SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unknown
            FROM usage {where}
            GROUP BY project ORDER BY cost DESC
        """
        out = []
        for r in self.conn.execute(sql, params):
            out.append((
                r["project"],
                Totals(r["i"], r["o"], r["cc"], r["cr"], r["cost"] or 0.0,
                       (r["unknown"] or 0) == 0),
            ))
        return out

    def by_year(self) -> list[tuple[str, Totals]]:
        sql = """
            SELECT year,
                COALESCE(SUM(input_tokens),0) AS i,
                COALESCE(SUM(output_tokens),0) AS o,
                COALESCE(SUM(cache_creation_tokens),0) AS cc,
                COALESCE(SUM(cache_read_tokens),0) AS cr,
                COALESCE(SUM(cost),0) AS cost,
                SUM(CASE WHEN cost IS NULL THEN 1 ELSE 0 END) AS unknown
            FROM usage GROUP BY year ORDER BY year DESC
        """
        out = []
        for r in self.conn.execute(sql):
            out.append((
                r["year"] or "?",
                Totals(r["i"], r["o"], r["cc"], r["cr"], r["cost"] or 0.0,
                       (r["unknown"] or 0) == 0),
            ))
        return out

    def daily_series(self, days: int) -> list[tuple[str, float, int]]:
        """Return [(day, cost, total_tokens)] for the last ``days`` days, oldest first."""
        sql = """
            SELECT day,
                COALESCE(SUM(cost),0) AS cost,
                COALESCE(SUM(input_tokens+output_tokens+cache_creation_tokens+cache_read_tokens),0) AS tok
            FROM usage GROUP BY day ORDER BY day DESC LIMIT ?
        """
        rows = [(r["day"], r["cost"] or 0.0, r["tok"]) for r in self.conn.execute(sql, (days,))]
        return list(reversed(rows))

    def active_session(self) -> tuple[str, Totals] | None:
        """Most-recently-active session id and its totals, if any usage exists."""
        row = self.conn.execute(
            "SELECT session_id FROM usage WHERE session_id IS NOT NULL "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if not row or not row["session_id"]:
            return None
        sid = row["session_id"]
        return sid, self._aggregate("WHERE session_id = ?", (sid,))
