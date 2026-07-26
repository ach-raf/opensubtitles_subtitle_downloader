"""Unit tests for tui.state — pure data, no backend calls."""

from __future__ import annotations

import pytest

from tui.state import (
    AppState,
    Backend,
    EngineHealth,
    HistoryEntry,
    QueueItem,
    RunPolicy,
    HI_POLICY_VALUES,
    SYNC_POLICY_VALUES,
    native_name,
)


# --------------------------------------------------------------------------- #
# RunPolicy defaults + validation
# --------------------------------------------------------------------------- #
def test_run_policy_defaults_match_legacy_config():
    p = RunPolicy()
    # The config.yaml.sample defaults: opt_force_utf8 true, sync ask,
    # auto_selection false. clean_ads only makes sense with an ads file.
    assert p.force_utf8 is True
    assert p.audio_sync == "ask"
    assert p.auto_select is False
    assert p.hearing_impaired == "exclude"


@pytest.mark.parametrize("good", SYNC_POLICY_VALUES)
def test_run_policy_accepts_valid_sync(good):
    RunPolicy(audio_sync=good).validate()


def test_run_policy_rejects_invalid_sync():
    with pytest.raises(ValueError):
        RunPolicy(audio_sync="sometimes").validate()


def test_run_policy_rejects_invalid_hi():
    with pytest.raises(ValueError):
        RunPolicy(hearing_impaired="loud").validate()


# --------------------------------------------------------------------------- #
# AppState language scope rule (spec §6.2 + commit 8bab15e rationale)
# --------------------------------------------------------------------------- #
def _item(path: str, status: str = "queued") -> QueueItem:
    return QueueItem(path=path, name=path, status=status)


def test_single_file_run_changes_language_instantly():
    """Scope-confirm must NOT fire for a single file (spec §6.2)."""
    state = AppState(queue=[_item("a.mkv")])
    assert state.needs_language_scope_confirm() is False


def test_multi_file_run_requires_scope_confirm():
    state = AppState(queue=[_item("a.mkv"), _item("b.mkv"), _item("c.mkv")])
    assert state.needs_language_scope_confirm() is True


def test_scope_confirm_ignores_done_items():
    """Only non-done items count toward the >1 threshold."""
    state = AppState(
        queue=[
            _item("a.mkv", status="done"),
            _item("b.mkv", status="queued"),
        ]
    )
    # Only one non-done -> instant change, no confirm.
    assert state.remaining_count() == 1
    assert state.needs_language_scope_confirm() is False


def test_scope_confirm_includes_all_in_flight_statuses():
    """searching/downloading/post all count as 'needs work'."""
    state = AppState(
        queue=[
            _item("a.mkv", status="searching"),
            _item("b.mkv", status="downloading"),
        ]
    )
    assert state.needs_language_scope_confirm() is True


def test_remaining_count_with_mixed_statuses():
    state = AppState(
        queue=[
            _item("a.mkv", status="done"),
            _item("b.mkv", status="failed"),  # terminal
            _item("c.mkv", status="skipped"),  # terminal
            _item("d.mkv", status="queued"),
            _item("e.mkv", status="post"),
        ]
    )
    assert state.remaining_count() == 2


# --------------------------------------------------------------------------- #
# QueueItem / current_item helpers
# --------------------------------------------------------------------------- #
def test_current_item_returns_first_non_done():
    state = AppState(
        queue=[
            _item("a.mkv", status="done"),
            _item("b.mkv", status="queued"),
            _item("c.mkv", status="queued"),
        ]
    )
    assert state.current_item().path == "b.mkv"


def test_current_item_falls_back_to_first_when_all_done():
    state = AppState(queue=[_item("a.mkv", status="done")])
    assert state.current_item().path == "a.mkv"


def test_current_item_none_when_queue_empty():
    assert AppState(queue=[]).current_item() is None


def test_reset_for_research_clears_results_and_cursor():
    state = AppState(
        results=[{"id": 1}, {"id": 2}],
        scores={"1": 90.0},
        cursor_index=1,
    )
    state.reset_for_research()
    assert state.results == []
    assert state.scores == {}
    assert state.cursor_index == 0


# --------------------------------------------------------------------------- #
# Engine health badge
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "health,expected",
    [
        (EngineHealth("opensubtitles", online=True, latency_ms=41), "online"),
        (EngineHealth("subdl", online=False), "offline"),
        (EngineHealth("subsource", online=False, degraded=True), "degraded"),
    ],
)
def test_engine_health_badge(health, expected):
    assert health.badge == expected


# --------------------------------------------------------------------------- #
# Backend enum + labels
# --------------------------------------------------------------------------- #
def test_backend_values_match_config_strings():
    assert Backend("opensubtitles") is Backend.OPENSUBTITLES
    assert Backend.SUBSOURCE.value == "subsource"


def test_backend_labels_human_readable():
    assert Backend.OPENSUBTITLES.label == "OpenSubtitles"
    assert Backend.AUTO.label == "Auto"


# --------------------------------------------------------------------------- #
# Native name map (spec §11)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "code,expected",
    [("en", "English"), ("ar", "العربية"), ("zh", "中文"), ("ja", "日本語")],
)
def test_native_name_known(code, expected):
    assert native_name(code) == expected


def test_native_name_falls_back_to_code():
    assert native_name("xx") == "xx"


def test_native_name_empty():
    assert native_name("") == ""


# --------------------------------------------------------------------------- #
# HistoryEntry shape
# --------------------------------------------------------------------------- #
def test_history_entry_defaults():
    e = HistoryEntry(
        media_path="m.mkv",
        subtitle_path="m.en.srt",
        release="m",
        language="en",
        backend="opensubtitles",
    )
    assert e.cleaned is False
    assert e.synced is False
    assert e.sync_skipped is False
    assert e.error is None
