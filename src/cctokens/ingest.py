"""Parse Claude Code JSONL transcripts into deduped usage rows.

A single billable assistant message is written to the transcript on multiple
lines, all sharing one ``requestId`` with identical usage. Dedup therefore
happens on ``requestId`` (see :mod:`cctokens.storage`, which uses it as a
PRIMARY KEY). This module just yields candidate rows; the storage layer makes
ingestion idempotent.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"


@dataclass
class UsageRow:
    request_id: str
    timestamp: str  # ISO-8601 as written in the transcript
    model: str | None
    project: str  # human-readable project name (cwd basename)
    session_id: str | None
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cache_creation_1h: int
    cache_creation_5m: int


def _project_name(cwd: str | None, transcript_path: Path) -> str:
    """Derive a readable project name from the message's cwd, with fallback."""
    if cwd:
        base = os.path.basename(cwd.rstrip("/"))
        if base:
            return base
    # Fallback: the encoded directory name, de-mangled into something readable.
    return transcript_path.parent.name.strip("-").replace("-", "/") or "unknown"


def iter_usage_rows(path: Path) -> Iterator[UsageRow]:
    """Yield :class:`UsageRow` for every assistant line in one transcript file."""
    try:
        handle = path.open(encoding="utf-8", errors="ignore")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if rec.get("type") != "assistant":
                continue
            message = rec.get("message") or {}
            usage = message.get("usage")
            request_id = rec.get("requestId")
            if not usage or not request_id:
                continue
            creation = usage.get("cache_creation") or {}
            yield UsageRow(
                request_id=request_id,
                timestamp=rec.get("timestamp") or "",
                model=message.get("model"),
                project=_project_name(rec.get("cwd"), path),
                session_id=rec.get("sessionId"),
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_creation_1h=int(creation.get("ephemeral_1h_input_tokens") or 0),
                cache_creation_5m=int(creation.get("ephemeral_5m_input_tokens") or 0),
            )


@dataclass
class TranscriptStat:
    path: Path
    size: int
    mtime: float


def iter_transcripts(projects_dir: Path) -> Iterator[TranscriptStat]:
    """Yield every ``*.jsonl`` transcript under ``projects_dir`` with stat info."""
    if not projects_dir.exists():
        return
    for path in projects_dir.rglob("*.jsonl"):
        try:
            st = path.stat()
        except OSError:
            continue
        yield TranscriptStat(path=path, size=st.st_size, mtime=st.st_mtime)
