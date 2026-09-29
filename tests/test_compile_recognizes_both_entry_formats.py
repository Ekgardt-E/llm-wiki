"""Captured headings must compile, resume and remain verifiable after growth."""
from __future__ import annotations

import compile_memory as compiler
import evidence_resolver as evidence
import pytest
from reliable_memory import sha256_bytes


def _day(count: int = 24) -> bytes:
    entries = [f"## [10:{minute:02d}:00] session\n" + "evidence\n" * 400 for minute in range(count)]
    return ("# Daily\n\n" + "\n".join(entries)).encode()


def test_heading_entries_fit_and_cover_the_entire_day() -> None:
    content = _day()
    parts = compiler._daily_parts("knowledge/daily/2026-01-01.md", content)
    assert b"".join(part.content for part in parts) == content
    assert max(len(part.content) for part in parts) <= evidence.MAX_DAILY_PART_BYTES
    evidence._require_recorded_parts([(part.byte_start, part.byte_end) for part in parts], content)


def test_old_committed_whole_part_is_not_compiled_again() -> None:
    content = _day()
    done = lambda _path, digest: digest == sha256_bytes(content)  # noqa: E731
    assert compiler._daily_parts("knowledge/daily/2026-01-01.md", content, done) == []
    assert compiler.daily_is_compiled("knowledge/daily/2026-01-01.md", content, done)


def test_resume_only_offers_uncommitted_parts() -> None:
    path, content = "knowledge/daily/2026-01-01.md", _day()
    parts = compiler._daily_parts(path, content)
    done = lambda _path, digest: digest == parts[0].sha256  # noqa: E731
    remaining = compiler._daily_parts(path, content, done)
    assert remaining == parts[1:]
    assert remaining


def test_an_old_completed_part_and_new_pending_parts_coexist() -> None:
    path = "knowledge/daily/2026-01-01.md"
    completed = _day(6)
    tail = b"<!-- llm-wiki-operation:next -->\n" + _day()
    done = lambda _path, digest: digest == sha256_bytes(completed)  # noqa: E731
    remaining = compiler._daily_parts(path, completed + tail, done)
    assert b"".join(part.content for part in remaining) == tail
    assert max(len(part.content) for part in remaining) <= evidence.MAX_DAILY_PART_BYTES
    assert not compiler.daily_is_compiled(path, completed + tail, done)


def test_a_historical_heading_part_resolves_after_growth() -> None:
    content = _day()
    start = content.index(b"## [10:07:00]")
    end = content.index(b"## [10:11:00]")
    part = content[start:end]
    grown = content + b"\n## [11:00:00] later\nmore evidence\n"
    assert evidence.compile_part_slice(grown, sha256_bytes(part)) == part
    assert evidence.compile_part_slice(grown.replace(b"evidence", b"changed!"), sha256_bytes(part)) is None


def test_heading_day_can_be_packed(tmp_path, monkeypatch) -> None:
    from tests.test_a_split_day_is_archived_with_every_part import _vault

    _root, _state, daily = _vault(tmp_path, monkeypatch)
    daily.write_bytes(_day())
    batches = compiler.pack_compile_batches(compiler.snapshot_compile_inputs([daily]), model=None)
    assert len(batches) > 1


@pytest.mark.parametrize("old_rule", [False, True])
def test_heading_day_archives_with_its_receipts(tmp_path, monkeypatch, old_rule) -> None:
    from tests.test_a_split_day_is_archived_with_every_part import (
        _archive,
        _compile_every_part,
        _vault,
    )

    root, state, daily = _vault(tmp_path, monkeypatch)
    content = _day(6)
    daily.write_bytes(content)
    with monkeypatch.context() as context:
        if old_rule:
            context.setattr(evidence, "MAX_DAILY_PART_BYTES", len(content))
        _compile_every_part(root, state, daily)
    archived = _archive(root, state, daily.stem)
    assert archived.state == "archived"
