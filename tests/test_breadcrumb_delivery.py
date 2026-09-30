"""A busy Markdown writer cannot consume an accepted breadcrumb."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from functools import partial

import flush_memory
import integration_adapter
import iso_time
import post_tool_capture
import pytest
import user_prompt_capture
from markdown_transaction import active_markdown_coordinator
from memory_queue import active_memory_queue

from tests.adopted_capture_vault import adopted_capture_vault, published_intents


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    state_root, _ = adopted_capture_vault(tmp_path, monkeypatch, integration_adapter)
    monkeypatch.setenv("LLM_WIKI_STATE_ROOT", str(state_root))
    monkeypatch.setattr(flush_memory, "STATE_ROOT", state_root)
    monkeypatch.setattr(integration_adapter, "spawn_detached", lambda *a, **k: None)
    monkeypatch.setattr(
        flush_memory,
        "_call_capture_classifier",
        lambda *a: pytest.fail("LLM called for a breadcrumb"),
    )
    root = integration_adapter.ROOT
    return (
        root,
        state_root,
        active_memory_queue(root, state_root),
        active_markdown_coordinator(root, state_root),
    )


def _work(delivery):
    _, _, queue, coordinator = delivery
    processor = partial(flush_memory.process_new_capture, queue, coordinator)
    return flush_memory.run_capture_worker_once(queue, coordinator, process_missing=processor)


def _publish_prompt():
    from breadcrumb_capture import queue_breadcrumb

    return queue_breadcrumb("user_prompt", "demo", "session-a", {"preview": "original"}, "one")


def test_breadcrumb_reuses_its_validated_coordinator(delivery, monkeypatch):
    import markdown_transaction

    opened = []
    original = markdown_transaction.active_markdown_coordinator

    def open_coordinator(*args):
        coordinator = original(*args)
        opened.append(coordinator)
        return coordinator

    monkeypatch.setattr(markdown_transaction, "active_markdown_coordinator", open_coordinator)
    assert _publish_prompt()
    assert len(opened) == 1
    assert len(published_intents(delivery[1])) == 1
    _work(delivery)
    assert "original" in next((delivery[0] / "knowledge/daily").glob("*.md")).read_text()


def test_invalid_coordinator_is_refused_before_accepting_a_breadcrumb(delivery, monkeypatch):
    import markdown_transaction

    def invalid(*args):
        raise ValueError("coordinator validation failed")

    monkeypatch.setattr(markdown_transaction, "active_markdown_coordinator", invalid)
    with pytest.raises(ValueError, match="coordinator validation failed"):
        _publish_prompt()
    assert published_intents(delivery[1]) == []


def test_state_recovery_keeps_the_same_native_operation_id(monkeypatch):
    import capture_operation

    monkeypatch.setattr(capture_operation, "_count_dropped_write", lambda error: None)

    def unavailable(mutate):
        raise OSError("state lock unavailable")

    options = dict(
        namespace="prompt",
        key="same-content",
        prefix="user-prompt",
        source_event_id="native-event",
        rate_limit_seconds=30,
        max_entries=100,
        now=datetime.now(),
    )
    first = capture_operation.claim_operation(unavailable, **options)
    retry = capture_operation.claim_operation(lambda mutate: mutate({}), **options)
    assert first == retry


def test_replay_after_midnight_keeps_original_time_and_only_one_append(delivery, monkeypatch):
    root, state_root, _, _ = delivery
    before = datetime.fromisoformat("2026-09-28T23:59:50+03:00")
    after = datetime.fromisoformat("2026-09-30T01:00:00+03:00")
    monkeypatch.setattr(iso_time, "local_now", lambda: before)
    _publish_prompt()
    original = published_intents(state_root)[0].read_bytes()
    monkeypatch.setattr(iso_time, "local_now", lambda: after)
    _publish_prompt()
    _work(delivery)
    _publish_prompt()
    assert (_work(delivery), published_intents(state_root)[0].read_bytes()) == (None, original)
    daily = root / "knowledge/daily/2026-09-28.md"
    assert (daily.read_text().count("original"), "[23:59:50]" in daily.read_text()) == (1, True)


def test_ready_intent_survives_failed_dispatch_and_is_adopted(delivery, monkeypatch):
    from memory_queue import _QueueV3CandidateReader

    root, state_root, _, _ = delivery
    original = _QueueV3CandidateReader.enqueue_capture_task_replay_safe

    def fail_dispatch(*args, **kwargs):
        raise OSError("publisher stopped after writing the ready intent")

    monkeypatch.setattr(_QueueV3CandidateReader, "enqueue_capture_task_replay_safe", fail_dispatch)
    assert _publish_prompt()
    assert len(published_intents(state_root)) == 1
    monkeypatch.setattr(_QueueV3CandidateReader, "enqueue_capture_task_replay_safe", original)
    _work(delivery)
    assert "original" in next((root / "knowledge/daily").glob("*.md")).read_text()


def test_failure_before_retention_is_not_acknowledged(delivery, monkeypatch):
    def fail_before_publish(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(integration_adapter, "_publish_capture_files_and_task", fail_before_publish)
    with pytest.raises(OSError, match="disk unavailable"):
        _publish_prompt()
    assert published_intents(delivery[1]) == []


def _expire_publisher_lease(delivery, monkeypatch):
    from operational_ownership import OwnershipRegistry

    with sqlite3.connect(delivery[3].database_path) as database:
        expires = database.execute(
            "SELECT expires_at FROM maintenance_owners WHERE role='capture'"
        ).fetchone()[0]
    after = datetime.fromisoformat(expires) + timedelta(seconds=1)
    original = OwnershipRegistry._from_adopted_database.__func__

    def open_after_expiry(cls, *args, **kwargs):
        return original(cls, *args, **{**kwargs, "clock": lambda: after})

    monkeypatch.setattr(OwnershipRegistry, "_from_adopted_database", classmethod(open_after_expiry))


def test_dead_publisher_is_recovered_by_a_fresh_worker(delivery, monkeypatch):
    from capture_adoption import adopt_orphaned_capture_intents

    program = """
import os
from memory_queue import _QueueV3CandidateReader
from breadcrumb_capture import queue_breadcrumb
_QueueV3CandidateReader.enqueue_capture_task_replay_safe = lambda *a, **k: os._exit(86)
queue_breadcrumb('user_prompt', 'demo', 'session-a', {'preview': 'survives process death'}, 'crash:one')
"""
    env = {**os.environ, "PYTHONPATH": str(integration_adapter.SCRIPTS_DIR)}
    exited = subprocess.run(
        [sys.executable, "-c", program],
        env=env,
        capture_output=True,
        timeout=integration_adapter.HOST_HOOK_TIMEOUT_SECONDS,
    )
    assert exited.returncode == 86, exited.stderr.decode()
    adoption = adopt_orphaned_capture_intents(delivery[2], delivery[3], state_root=delivery[1])
    assert adoption["skipped"][0]["reason"] == "OperationalOwnershipError: owner_busy"
    _expire_publisher_lease(delivery, monkeypatch)
    relative = _work(delivery)
    terminal = json.loads((delivery[1] / relative).read_bytes())
    assert terminal["disposition"]["kind"] == "markdown_committed"
    daily = next((delivery[0] / "knowledge/daily").glob("*.md"))
    assert daily.read_text().count("survives process death") == 1


def test_retry_reuses_the_published_renderer_decision(delivery, monkeypatch):
    import breadcrumb_capture
    import memory_queue

    _publish_prompt()
    original = flush_memory._complete_capture_decision

    def interrupted(*args):
        raise RuntimeError("stopped after the decision was saved")

    monkeypatch.setattr(flush_memory, "_complete_capture_decision", interrupted)
    with pytest.raises(RuntimeError, match="decision was saved"):
        _work(delivery)
    with sqlite3.connect(delivery[2].db_path) as database:
        available = database.execute("SELECT available_at FROM tasks").fetchone()[0]
    retry_at = datetime.fromisoformat(available) + timedelta(seconds=1)
    monkeypatch.setattr(memory_queue, "_utc_now", lambda: retry_at)
    monkeypatch.setattr(flush_memory, "_complete_capture_decision", original)
    monkeypatch.setattr(breadcrumb_capture, "_decision", lambda *a: pytest.fail("decision rebuilt"))
    terminal_path = _work(delivery)
    assert (
        json.loads((delivery[1] / terminal_path).read_bytes())["disposition"]["kind"]
        == "markdown_committed"
    )


def test_same_operation_cannot_change_its_payload(delivery):
    from breadcrumb_capture import queue_breadcrumb

    _publish_prompt()
    with pytest.raises(ValueError, match="different content"):
        queue_breadcrumb("user_prompt", "demo", "session-a", {"preview": "replacement"}, "one")
    record = json.loads(published_intents(delivery[1])[0].read_bytes())
    assert "original" in record["evidence"][0]["parts"][0]["text"]


def test_renderer_decision_cannot_change_source_bytes(delivery):
    from breadcrumb_capture import require_decision

    _publish_prompt()
    _work(delivery)
    state_root = delivery[1]
    intent = json.loads(published_intents(state_root)[0].read_bytes())
    decision = json.loads(
        next((state_root / "run/queue-results").glob("capture-decision-*.json")).read_bytes()
    )
    decision["operation_plan"][0]["block"] = "changed source"
    with pytest.raises(RuntimeError, match="does not match"):
        require_decision(decision, intent)


@pytest.mark.parametrize("legacy_id", ["one", "user-prompt:fallback:" + "a" * 64])
def test_completed_synchronous_capture_is_not_duplicated_after_upgrade(
    delivery, monkeypatch, legacy_id
):
    import breadcrumb_capture

    root, state_root, _, _ = delivery
    original = breadcrumb_capture.queue_breadcrumb
    monkeypatch.setattr(breadcrumb_capture, "queue_breadcrumb", lambda *args: False)
    assert user_prompt_capture._append_prompt_tag("demo", "session-a", "original", legacy_id)
    monkeypatch.setattr(breadcrumb_capture, "queue_breadcrumb", original)
    assert original(
        "user_prompt",
        "demo",
        "session-a",
        {"preview": "original"},
        legacy_id.replace(":fallback:", ":", 1),
    )
    daily = next((root / "knowledge/daily").glob("*.md"))
    assert (published_intents(state_root), daily.read_text().count("original")) == ([], 1)


@pytest.mark.shipped_append_budgets
@pytest.mark.parametrize("kind", ["prompt", "tool"])
def test_writer_contention_retains_the_event_for_a_worker(tmp_path, monkeypatch, kind):
    state_root, _ = adopted_capture_vault(tmp_path, monkeypatch, integration_adapter)
    monkeypatch.setenv("LLM_WIKI_STATE_ROOT", str(state_root))
    monkeypatch.setattr(integration_adapter, "spawn_detached", lambda *a, **k: None)
    errors = []
    monkeypatch.setattr(
        user_prompt_capture, "record_capture_failure", lambda *a, **k: errors.append(a)
    )
    monkeypatch.setattr(
        post_tool_capture, "record_capture_failure", lambda *a, **k: errors.append(a)
    )
    coordinator = active_markdown_coordinator(integration_adapter.ROOT, state_root)
    queue = active_memory_queue(integration_adapter.ROOT, state_root)
    calls = {
        "prompt": partial(
            user_prompt_capture._append_prompt_tag,
            "demo",
            "session-a",
            "Keep the original request",
            "prompt:one",
        ),
        "tool": partial(
            post_tool_capture._append_tool_tag,
            "demo",
            "session-a",
            "Edit",
            "src/original.py",
            "tool:one",
        ),
    }
    holder = active_markdown_coordinator(integration_adapter.ROOT, state_root)
    with holder.writer_gate():
        accepted = calls[kind]()
        retained = published_intents(state_root)
    assert (accepted, len(retained)) == (True, 1), errors
    worker = partial(flush_memory.process_new_capture, queue, coordinator)
    flush_memory.run_capture_worker_once(queue, coordinator, process_missing=worker)
    daily = list((integration_adapter.ROOT / "knowledge/daily").glob("*.md"))
    assert len(daily) == 1
