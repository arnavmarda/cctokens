import json
from pathlib import Path

from cctokens import ingest
from cctokens.storage import Store


def _line(request_id, ts, model="claude-opus-4-8", cwd="/home/me/proj",
          session="sess-1", inp=10, out=5, cc=2, cr=3, ch=2, cm=0):
    return json.dumps({
        "type": "assistant",
        "requestId": request_id,
        "timestamp": ts,
        "cwd": cwd,
        "sessionId": session,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_creation_input_tokens": cc,
                "cache_read_input_tokens": cr,
                "cache_creation": {
                    "ephemeral_1h_input_tokens": ch,
                    "ephemeral_5m_input_tokens": cm,
                },
            },
        },
    })


def _write(dirpath: Path, name: str, lines: list[str]) -> Path:
    proj = dirpath / "projects" / "-home-me-proj"
    proj.mkdir(parents=True, exist_ok=True)
    f = proj / name
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


def test_iter_skips_non_assistant_and_missing_usage(tmp_path):
    f = _write(tmp_path, "a.jsonl", [
        json.dumps({"type": "user", "message": {"content": "hi"}}),
        json.dumps({"type": "assistant", "requestId": "r1"}),  # no usage
        _line("r2", "2026-06-24T10:00:00.000Z"),
    ])
    rows = list(ingest.iter_usage_rows(f))
    assert len(rows) == 1
    assert rows[0].request_id == "r2"
    assert rows[0].project == "proj"


def test_dedup_by_request_id(tmp_path):
    # Same requestId on three lines (the real-world repetition) -> counted once.
    lines = [_line("dup", "2026-06-24T10:00:00.000Z") for _ in range(3)]
    lines.append(_line("uniq", "2026-06-24T11:00:00.000Z"))
    _write(tmp_path, "a.jsonl", lines)

    store = Store(db_path=tmp_path / "db.sqlite")
    store.sync(tmp_path / "projects")
    total = store.totals_all()
    # 2 distinct requests * (10 in + 5 out + 2 cc + 3 cr) = 2 * 20 = 40
    assert total.total_tokens == 40
    assert store.conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0] == 2
    store.close()


def test_incremental_scan_skips_unchanged(tmp_path):
    _write(tmp_path, "a.jsonl", [_line("r1", "2026-06-24T10:00:00.000Z")])
    store = Store(db_path=tmp_path / "db.sqlite")
    assert store.sync(tmp_path / "projects") == 1
    assert store.sync(tmp_path / "projects") == 0  # unchanged -> skipped
    store.close()


def test_aggregations(tmp_path):
    _write(tmp_path, "a.jsonl", [
        _line("r1", "2026-06-24T10:00:00.000Z", model="claude-opus-4-8", session="s1"),
        _line("r2", "2025-12-01T10:00:00.000Z", model="claude-sonnet-4-6", session="s2"),
    ])
    store = Store(db_path=tmp_path / "db.sqlite")
    store.sync(tmp_path / "projects")

    years = dict((y, t.total_tokens) for y, t in store.by_year())
    assert set(years) == {"2026", "2025"}

    models = dict((m, t.total_tokens) for m, t in store.by_model())
    assert "claude-opus-4-8" in models and "claude-sonnet-4-6" in models

    sess = store.active_session()
    assert sess is not None and sess[0] == "s1"  # latest by ts
    store.close()
