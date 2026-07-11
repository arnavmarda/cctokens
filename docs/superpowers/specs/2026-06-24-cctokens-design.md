# cctokens — Claude Code usage CLI + TUI

**Date:** 2026-06-24
**Status:** Approved

## Purpose

A globally-invokable CLI and rich TUI that reports local Claude Code token
usage and estimated cost, replicating the data layer of
[phuryn/claude-usage](https://github.com/phuryn/claude-usage) but replacing its
web dashboard with a Textual TUI.

## Data source

Claude Code writes JSONL transcripts to `~/.claude/projects/**/*.jsonl`. Each
`type: "assistant"` line carries:

- `requestId` — billing dedup key (see below)
- `timestamp` — ISO-8601 UTC
- `cwd` — used to derive the project name
- `sessionId`
- `message.model`
- `message.usage.{input_tokens, output_tokens, cache_creation_input_tokens,
  cache_read_input_tokens}`
- `message.usage.cache_creation.{ephemeral_1h_input_tokens,
  ephemeral_5m_input_tokens}` — the 1h/5m cache-write split

### Dedup invariant (load-bearing)

A single billable assistant message appears on **multiple** JSONL lines with the
**same `requestId`** and **identical usage** (verified empirically: ~9.3k of
13.7k requestIds repeat, always with identical token counts and the same
`message.id`). Therefore usage is counted **once per `requestId`** via
`INSERT OR IGNORE` with `requestId` as PRIMARY KEY. Summing raw lines overcounts
~3×.

## Architecture (5 isolated units)

| Module | Responsibility | Depends on |
|---|---|---|
| `ingest.py` | Walk JSONL, yield deduped usage rows; incremental via (path,size,mtime) | stdlib only |
| `storage.py` | SQLite at `~/.claude/cctokens.db`; tables `usage`, `scanned_files`; query fns | ingest |
| `pricing.py` | model→rate substring map; cost from 4 token buckets | stdlib only |
| `cli.py` | Typer commands; Rich tables | storage, pricing |
| `tui.py` | Textual dashboard; live incremental refresh | storage, pricing |

DB path `~/.claude/cctokens.db` is distinct from the reference's `usage.db` so
both tools coexist.

## Pricing (per 1M tokens)

| Model substring | Input | Output | Cache write (1.25×) | Cache read (0.1×) |
|---|---|---|---|---|
| `fable`/`mythos` | 10 | 50 | 12.50 | 1.00 |
| `opus` | 5 | 25 | 6.25 | 0.50 |
| `sonnet` | 3 | 15 | 3.75 | 0.30 |
| `haiku` | 1 | 5 | 1.25 | 0.10 |
| unknown | — | — | — | shows `n/a` |

Cache-write cost: the `cache_creation_input_tokens` bucket is split into 1h
(2× input rate) and 5m (1.25× input rate) sub-buckets when the transcript
provides `cache_creation.ephemeral_{1h,5m}_input_tokens`; otherwise the whole
bucket is priced at 1.25×. Cache-read priced at 0.1× input rate.

## CLI

```
cctokens                  # launches TUI (no args)
cctokens scan             # force full re-ingest
cctokens today            # today by model
cctokens week             # last 7 days
cctokens month            # last 30 days
cctokens stats            # all-time + yearly rollup
cctokens projects         # per-project table
cctokens tui              # explicit TUI launch
```

Global flag `--projects-dir PATH` (default `~/.claude/projects`).

## TUI (Textual)

Tabbed dashboard: **Today** (+ active-session live counters), **Trends**
(30-day bar chart, model filter), **Projects** (sortable DataTable),
**All-time** (yearly rollup). A 5s timer re-runs the incremental scan so
Today/active panels update live. Keys: `q` quit, `r` refresh, `1–4` tabs.

Plan-progress bar is deferred (panel slot reserved).

## Packaging

`pyproject.toml`, entry point `cctokens = "cctokens.cli:app"`, deps
`typer`, `rich`, `textual`. Install: `uv tool install .`.

## Testing

`pytest` over `ingest` (dedup, incremental), `pricing` (per-model + cache math),
`storage` (aggregations) using synthetic JSONL fixtures.
