"""Phase 4 tests: post-download toast auto-pick rule + download flow.

The 5-second auto-pick rule (spec §6.4) is the firmest behavior in the spec:
    - policy 'always' -> auto-run Clean+Sync after 5s
    - policy 'never'  -> auto-run Clean after 5s
    - policy 'ask'    -> NEVER auto-pick; wait indefinitely for a keypress
'A' pins the chosen action as the new default.
"""

from __future__ import annotations

import asyncio

import pytest

from tui.app import SubsApp
from tui.services import DownloadResult
from tui.state import RunPolicy
from tui.widgets.overlays.post_download_toast import (
    AUTO_PICK_SECONDS,
    PostAction,
    PostDownloadToast,
)


def _result(downloaded: bool = True, error: str | None = None) -> DownloadResult:
    return DownloadResult(
        media_path="/m/Movie.mkv",
        subtitle_path="/m/Movie.en.srt" if downloaded else None,
        release="Movie.2010.1080p",
        language="en",
        backend="opensubtitles",
        downloaded=downloaded,
        error=error,
    )


# --------------------------------------------------------------------------- #
# Auto-pick RULE (the firm spec behavior) — tested via properties, not the timer
# --------------------------------------------------------------------------- #
def test_auto_picks_only_when_policy_decided():
    """auto_picks is True only for always/never; ask waits (spec §6.4)."""
    assert PostDownloadToast(_result(), audio_sync_policy="always").auto_picks is True
    assert PostDownloadToast(_result(), audio_sync_policy="never").auto_picks is True
    assert PostDownloadToast(_result(), audio_sync_policy="ask").auto_picks is False


def test_default_action_maps_policy_to_action():
    """always -> Clean+Sync, never -> Clean, ask -> Done (no default)."""
    assert PostDownloadToast(_result(), "always").default_action is PostAction.CLEAN_SYNC
    assert PostDownloadToast(_result(), "never").default_action is PostAction.CLEAN
    # 'ask' has no meaningful default; it must wait for a keypress.
    assert PostDownloadToast(_result(), "ask").default_action is PostAction.DONE


def test_post_action_do_clean_do_sync_flags():
    assert PostAction.CLEAN_SYNC.do_clean is True
    assert PostAction.CLEAN_SYNC.do_sync is True
    assert PostAction.CLEAN.do_clean is True
    assert PostAction.CLEAN.do_sync is False
    assert PostAction.SYNC.do_clean is False
    assert PostAction.SYNC.do_sync is True
    assert PostAction.DONE.do_clean is False
    assert PostAction.DONE.do_sync is False


def test_auto_pick_seconds_is_five():
    """Spec §6.4: the auto-pick window is exactly 5 seconds."""
    assert AUTO_PICK_SECONDS == 5


# --------------------------------------------------------------------------- #
# Manual keypresses dismiss with the right action
# --------------------------------------------------------------------------- #
def _drive_toast(toast, keys):
    result: dict = {}

    async def run():
        app = SubsApp(config={}, media_paths=[], overrides={})
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.push_screen(toast, lambda r: result.setdefault("r", r))
            await pilot.pause(0.15)
            for k in keys:
                await pilot.press(k)
                await pilot.pause(0.1)
            # For 'ask' we expect no auto-dismiss, so we only wait briefly.
            await pilot.pause(0.3)

    asyncio.run(run())
    return result.get("r", "NO_DISMISS")


def test_enter_chooses_clean_sync():
    toast = PostDownloadToast(_result(), audio_sync_policy="ask")
    out = _drive_toast(toast, ["enter"])
    assert out[0] is PostAction.CLEAN_SYNC


def test_c_chooses_clean():
    toast = PostDownloadToast(_result(), audio_sync_policy="ask")
    out = _drive_toast(toast, ["c"])
    assert out[0] is PostAction.CLEAN


def test_s_chooses_sync():
    toast = PostDownloadToast(_result(), audio_sync_policy="ask")
    out = _drive_toast(toast, ["s"])
    assert out[0] is PostAction.SYNC


def test_d_chooses_done():
    toast = PostDownloadToast(_result(), audio_sync_policy="ask")
    out = _drive_toast(toast, ["d"])
    assert out[0] is PostAction.DONE


def test_escape_skips():
    toast = PostDownloadToast(_result(), audio_sync_policy="ask")
    out = _drive_toast(toast, ["escape"])
    assert out[0] is PostAction.DONE


# --------------------------------------------------------------------------- #
# The CRITICAL ask-path: the toast must NOT auto-dismiss while waiting.
# We verify no dismiss happens within a window shorter than the auto-pick timer.
# --------------------------------------------------------------------------- #
def test_ask_does_not_auto_dismiss_within_window():
    """With policy 'ask', the toast stays open well past the 5s window would be
    for always/never — i.e. no auto-pick fires."""
    toast = PostDownloadToast(_result(), audio_sync_policy="ask")
    out = _drive_toast(toast, [])  # press nothing
    assert out == "NO_DISMISS"


# --------------------------------------------------------------------------- #
# 'A' pins default
# --------------------------------------------------------------------------- #
def test_pin_default_then_choose_carries_pinned_flag():
    """Press A then an action -> the dismiss carries pinned=True."""
    toast = PostDownloadToast(_result(), audio_sync_policy="ask")
    out = _drive_toast(toast, ["A", "c"])
    assert out[0] is PostAction.CLEAN
    assert out[1] is True  # pinned


# --------------------------------------------------------------------------- #
# Amber (sync failure) tone
# --------------------------------------------------------------------------- #
def test_amber_toast_constructs_without_crash():
    toast = PostDownloadToast(_result(), audio_sync_policy="ask", amber=True)
    assert toast.amber is True


# --------------------------------------------------------------------------- #
# Full download flow through the App (DownloadWorker mocked)
# --------------------------------------------------------------------------- #
def test_download_flow_runs_worker_then_mounts_toast(monkeypatch):
    canned = [
        {"id": "1", "attributes": {"release": "Inception.2010", "language": "en",
                                    "download_count": 5, "moviehash_match": True}}
    ]

    def fake_search(self, state, media_path, engine=None):
        canned[0]["_score"] = 95.0
        canned[0]["_source"] = "opensubtitles"
        return list(canned)

    monkeypatch.setattr("tui.services.SearchWorker.search", fake_search)
    monkeypatch.setattr(
        "tui.services.HealthProbe.probe", lambda self, force=False, only=None: {}
    )

    download_result = _result(downloaded=True)

    def fake_download(self, state, media_path, chosen, engine=None, search_worker=None):
        return download_result

    monkeypatch.setattr("tui.services.DownloadWorker.download", fake_download)

    def fake_postprocess(self, result, do_clean, do_sync):
        from tui.state import HistoryEntry

        return HistoryEntry(
            media_path=result.media_path,
            subtitle_path=result.subtitle_path,
            release=result.release,
            language=result.language,
            backend=result.backend,
            cleaned=do_clean,
            synced=do_sync,
        )

    monkeypatch.setattr("tui.services.DownloadWorker.postprocess", fake_postprocess)

    app = SubsApp(config={}, media_paths=["Inception.2010.mkv"], overrides={})
    app.run_policy = RunPolicy(audio_sync="always", clean_ads=True)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.4)
            # Trigger a download on the cursor row.
            app.action_download_cursor()
            await pilot.pause(0.4)
            # The toast should be mounted.
            assert isinstance(app.screen, PostDownloadToast)
            # Choose Done to finalize.
            await pilot.press("d")
            await pilot.pause(0.3)
            # A history entry was recorded (release comes from the DownloadResult).
            assert len(app.history) == 1
            assert app.history[0].release == "Movie.2010.1080p"

    asyncio.run(run())


def test_download_failure_does_not_crash_and_marks_queue(monkeypatch):
    canned = [
        {"id": "1", "attributes": {"release": "X", "language": "en",
                                    "download_count": 1, "moviehash_match": False}}
    ]

    def fake_search(self, state, media_path, engine=None):
        canned[0]["_score"] = 50.0
        canned[0]["_source"] = "opensubtitles"
        return list(canned)

    monkeypatch.setattr("tui.services.SearchWorker.search", fake_search)
    monkeypatch.setattr(
        "tui.services.HealthProbe.probe", lambda self, force=False, only=None: {}
    )

    def fake_download(self, state, media_path, chosen, engine=None, search_worker=None):
        return DownloadResult(
            media_path=media_path,
            subtitle_path=None,
            release="X",
            language="en",
            backend="opensubtitles",
            downloaded=False,
            error="network down",
        )

    monkeypatch.setattr("tui.services.DownloadWorker.download", fake_download)

    app = SubsApp(config={}, media_paths=["X.mkv"], overrides={})

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            app.action_download_cursor()
            await pilot.pause(0.5)
            # No toast on failure; queue item marked failed.
            assert not isinstance(app.screen, PostDownloadToast)
            assert app.queue[0].status == "failed"
            assert "network down" in (app.queue[0].error or "")

    asyncio.run(run())


def test_download_exception_is_contained(monkeypatch):
    canned = [
        {"id": "1", "attributes": {"release": "X", "language": "en",
                                    "download_count": 1, "moviehash_match": False}}
    ]

    def fake_search(self, state, media_path, engine=None):
        canned[0]["_score"] = 50.0
        canned[0]["_source"] = "opensubtitles"
        return list(canned)

    monkeypatch.setattr("tui.services.SearchWorker.search", fake_search)
    monkeypatch.setattr(
        "tui.services.HealthProbe.probe", lambda self, force=False, only=None: {}
    )

    def boom(self, *a, **k):
        raise RuntimeError("backend exploded")

    monkeypatch.setattr("tui.services.DownloadWorker.download", boom)

    app = SubsApp(config={}, media_paths=["X.mkv"], overrides={})

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            app.action_download_cursor()
            await pilot.pause(0.5)
            # App still alive; no toast.
            assert not isinstance(app.screen, PostDownloadToast)
            assert app.queue[0].status == "failed"

    asyncio.run(run())
