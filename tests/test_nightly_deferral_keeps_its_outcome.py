"""Deferring post-compile work is not a completed maintenance pass."""

from datetime import datetime, timezone

import doctor
import scheduled_nightly as nightly


def _state(monkeypatch, status="running"):
    state = {
        nightly.DEFERRED_COMPILE_KEY: "old-start",
        "last_compile_started_at": "old-start",
        "last_compile_status": status,
    }
    monkeypatch.setattr(nightly, "_safe_state", lambda: state)
    monkeypatch.setattr(nightly, "update_state", lambda mutate: mutate(state))
    return state


def test_deferred_pass_does_not_claim_success(monkeypatch):
    state = _state(monkeypatch)
    nightly._record_nightly_result("2026-10-01", 0)
    assert state["last_nightly_status"] == "deferred"
    assert "last_nightly_at" not in state
    assert state[nightly.DEFERRED_COMPILE_KEY] == "old-start"
    assert "deferred" in nightly._nightly_completion_line(0)


def test_live_deferred_compiler_is_not_a_lost_run(monkeypatch):
    state = _state(monkeypatch)
    monkeypatch.setattr(nightly, "_compile_running", lambda: True)
    messages = []
    assert nightly._report_deferred_loss(messages.append) == 0
    assert state[nightly.DEFERRED_COMPILE_KEY] == "old-start"
    assert messages == []


def test_previous_compile_loss_is_seen_before_new_start(monkeypatch):
    state = _state(monkeypatch)
    monkeypatch.setattr(nightly, "_compile_running", lambda: False)
    monkeypatch.setattr(nightly, "_wait_for_compile_idle", lambda log: None)
    monkeypatch.setattr(nightly, "_wait_compile_finished", lambda: True)
    monkeypatch.setattr(nightly, "_report_compile_outcome", lambda *args: 0)
    monkeypatch.setattr(nightly, "_post_compile_pass", lambda *args: 0)

    def new_compile():
        state.update(last_compile_started_at="new-start", last_compile_status="ok")
        return 0

    phases = iter((lambda: 0, new_compile))
    monkeypatch.setattr(nightly, "_run_steps", lambda *args: next(phases)())
    messages = []
    log = nightly.StepLog(messages.append)
    assert nightly._nightly_steps(None, log) == 1
    assert any("old-start" in message and "never finished" in message for message in messages)


def test_doctor_names_deferred_work():
    result = doctor._nightly_result(
        {"last_nightly_status": "deferred"}, datetime.now(timezone.utc), {}
    )
    assert result["status"] == "degraded"
    assert "deferred" in result["message"].lower()


def test_context_names_deferred_work(monkeypatch):
    import session_start_context

    monkeypatch.setattr(session_start_context, "_nightly_state", lambda: {"last_nightly_status": "deferred"})
    assert "deferred" in session_start_context._nightly_line().lower()


def test_actual_failure_wins_over_deferral(monkeypatch):
    state = _state(monkeypatch)
    nightly._record_nightly_result("2026-10-01", 2, "real failure")
    assert state["last_nightly_status"] == "failed"
    assert state["last_nightly_failure"]["failures"] == 2
    assert state["last_nightly_failure"]["error"] == "real failure"
