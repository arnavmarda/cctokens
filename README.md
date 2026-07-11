# cctokens

A globally-invokable **CLI + rich TUI** for inspecting your local Claude Code
token usage and estimated cost. It parses the JSONL transcripts Claude Code
writes to `~/.claude/projects/` into a local SQLite cache, then reports usage by
day, week, month, project, model, and year — plus a live-updating Textual
dashboard.

Inspired by [phuryn/claude-usage](https://github.com/phuryn/claude-usage),
with the web dashboard replaced by a terminal TUI.

## Install

```sh
uv tool install .
```

This puts `cctokens` on your PATH so you can run it from anywhere.

## Usage

```sh
cctokens            # launch the interactive TUI dashboard
cctokens today      # today's tokens + cost, by model
cctokens week       # last 7 days
cctokens month      # last 30 days
cctokens projects   # per-project breakdown (all time)
cctokens stats      # all-time totals + per-year + per-model rollup
cctokens scan       # force a full re-ingest
```

Options:

```sh
cctokens today --projects-dir /custom/path/to/projects
```

### TUI keys

`q` quit · `r` refresh · `1`–`4` switch tabs (Today / Trends / Projects / All-time).
The dashboard re-scans every 5 seconds, so the active session and today's totals
update live while Claude Code runs.

## How cost is estimated

Rates are USD per 1M tokens (current Anthropic API pricing), matched by model
substring:

| Model | Input | Output |
|---|---|---|
| fable / mythos | $10 | $50 |
| opus | $5 | $25 |
| sonnet | $3 | $15 |
| haiku | $1 | $5 |

Cache reads are billed at 0.1× the input rate; cache writes at 1.25× (5-minute
TTL) or 2× (1-hour TTL) when the transcript provides the split. Unknown models
show `n/a` / a `+` suffix on aggregated costs.

A single billable assistant message is written to the transcript multiple times
with the same `requestId`; cctokens counts each `requestId` once, so totals
aren't inflated.

## Develop

```sh
uv run pytest
```
