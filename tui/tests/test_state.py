"""Unit tests for tui.state — pure data, no backend calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from tui.config import ConfigRepository
from tui.domain import (
    Candidate,
    EngineMode,
    PostProcessResult,
    Provider,
    QueueStatus,
)
from tui.domain import (
    HistoryEntry as DomainHistoryEntry,
)
from tui.domain import (
    QueueItem as DomainQueueItem,
)
from tui.state import (
    SYNC_POLICY_VALUES,
    AppState,
    Backend,
    EngineHealth,
    HistoryEntry,
    InvalidTransition,
    QueueItem,
    RunPolicy,
    SessionState,
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


def _domain_item(name, language="en"):
    return DomainQueueItem(
        key=name,
        path=Path(name),
        language=language,
        engine_mode=EngineMode.ASK,
    )


def _history(item):
    return DomainHistoryEntry(
        item_key=item.key,
        media_path=item.path,
        candidate_key="subdl:1",
        provider=Provider.SUBDL,
        language=item.language,
        subtitle_path=Path(f"{item.path.stem}.en.srt"),
        postprocess=PostProcessResult(),
    )


def test_ask_backend_remains_ask_until_user_selects(tmp_path):
    config = ConfigRepository(tmp_path / "missing.yaml").load()

    state = SessionState.from_config(config)

    assert state.engine_mode is EngineMode.ASK
    assert state.needs_engine_setup


def test_interactive_startup_requests_language_after_engine(tmp_path):
    config = ConfigRepository(tmp_path / "missing.yaml").load()
    state = SessionState.from_config(config)

    state.choose_engine(EngineMode.SUBDL)

    assert state.needs_language_setup


def test_all_providers_is_a_concrete_engine_choice():
    item = _domain_item("movie.mkv")
    state = SessionState(queue=[item])

    state.choose_engine(EngineMode.ALL_PROVIDERS)

    assert state.engine_mode is EngineMode.ALL_PROVIDERS
    assert item.engine_mode is EngineMode.ALL_PROVIDERS


def test_completed_item_advances_to_next_non_terminal_item():
    state = SessionState(queue=[_domain_item("a.mkv"), _domain_item("b.mkv")])
    first = state.active_item
    state.begin_search(first.key)
    state.set_candidates(first.key, [])
    state.mark_complete(first.key, _history(first))

    assert state.active_item.path.name == "b.mkv"


def test_language_scope_updates_only_requested_items():
    state = SessionState(
        queue=[
            _domain_item("a.mkv"),
            _domain_item("b.mkv"),
            _domain_item("c.mkv"),
        ]
    )

    state.set_language("ar", scope="current")
    assert [item.language for item in state.queue] == ["ar", "en", "en"]
    state.set_language("fr", scope="remaining")
    assert [item.language for item in state.queue] == ["fr", "fr", "fr"]


def test_invalid_transition_is_rejected():
    item = _domain_item("a.mkv")
    state = SessionState(queue=[item])

    with pytest.raises(InvalidTransition):
        state.begin_download(item.key, "subdl:1")


def test_restart_search_invalidates_old_candidates():
    item = _domain_item("a.mkv")
    state = SessionState(queue=[item])
    state.begin_search(item.key)
    state.set_candidates(
        item.key,
        [
            Candidate(
                provider=Provider.SUBDL,
                provider_id="old",
                release="old result",
                language="en",
            )
        ],
    )

    state.restart_search(item.key)

    assert item.status is QueueStatus.QUEUED
    assert item.candidate_keys == []
    assert item.selected_candidate_key is None
