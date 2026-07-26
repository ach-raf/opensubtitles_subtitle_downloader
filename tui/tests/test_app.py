"""Smoke tests for the Phase 2 main screen using Textual's run_test harness.

These drive the real SubsApp with a mocked SearchWorker so no network/backend
is touched. They lock in: composition of all five widgets, the reactive
results -> table -> detail-pane flow, j/k cursor navigation, and the
multilingual render path.
"""

from __future__ import annotations

import asyncio

import pytest

from tui.app import SubsApp
from tui.widgets.detail_pane import DetailPane
from tui.widgets.query_bar import QueryBar
from tui.widgets.results_table import ResultsTable
from tui.widgets.status_bar import StatusBar
from tui.widgets.topbar import TopBar


def _row(rid: str, release: str, **attr_overrides):
    attrs = {
        "release": release,
        "language": "en",
        "download_count": 10,
        "moviehash_match": False,
        "ai_translated": False,
        "machine_translated": False,
    }
    attrs.update(attr_overrides)
    return {"id": rid, "attributes": attrs}


@pytest.fixture()
def app_with_fake_search(monkeypatch):
    """Build a SubsApp whose SearchWorker returns canned results."""

    canned = [
        _row("1", "Inception.2010.1080p.BluRay", download_count=48000, moviehash_match=True),
        _row("2", "Inception.2010.BluRay.Remux", download_count=22000),
        _row("3", "Inception.2010.1080p.HUN", download_count=9000, ai_translated=True, machine_translated=True),
    ]

    def fake_search(self, state, media_path, engine=None):
        for i, r in enumerate(canned):
            r["_score"] = [96.0, 81.0, 64.0][i]
            r["_source"] = "opensubtitles"
        return list(canned)

    monkeypatch.setattr("tui.services.SearchWorker.search", fake_search)
    # Avoid the real HealthProbe touching the network on mount probes.
    monkeypatch.setattr(
        "tui.services.HealthProbe.probe", lambda self, force=False, only=None: {}
    )

    app = SubsApp(config={}, media_paths=["Inception.2010.1080p.mkv"], overrides={})
    return app, canned


def test_main_screen_mounts_all_widgets(app_with_fake_search):
    app, _ = app_with_fake_search

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert app.query_one(TopBar) is not None
            assert app.query_one(QueryBar) is not None
            assert app.query_one(ResultsTable) is not None
            assert app.query_one(DetailPane) is not None
            assert app.query_one(StatusBar) is not None

    asyncio.run(run())


def test_search_worker_fills_results_table(app_with_fake_search):
    app, canned = app_with_fake_search

    async def run():
        async with app.run_test() as pilot:
            # The on_mount hook kicks off a search; let the worker complete.
            await pilot.pause(0.5)
            assert len(app.results) == 3
            table = app.query_one(ResultsTable)
            assert table.row_count == 3
            # Sorted by score desc -> row 1 is the hash-match 96.
            assert "Inception.2010.1080p.BluRay" in str(app.results[0])

    asyncio.run(run())


def test_cursor_navigation_updates_detail_pane(app_with_fake_search):
    app, _ = app_with_fake_search

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            detail = app.query_one(DetailPane)
            # Cursor starts on row 0.
            assert app.cursor_index == 0
            first = detail.query_one("#detail-title").content
            # Move down twice.
            await pilot.press("j")
            await pilot.pause(0.1)
            await pilot.press("j")
            await pilot.pause(0.1)
            assert app.cursor_index == 2
            third = detail.query_one("#detail-title").content
            assert first != third
            # Up once.
            await pilot.press("k")
            await pilot.pause(0.1)
            assert app.cursor_index == 1

    asyncio.run(run())


def test_multilingual_release_renders(monkeypatch):
    """Arabic/CJK release names must reach the detail pane intact (spec §11)."""
    canned = [_row("1", "الهيبة - S01E03", language="ar")]

    def fake_search(self, state, media_path, engine=None):
        canned[0]["_score"] = 90.0
        canned[0]["_source"] = "opensubtitles"
        return list(canned)

    monkeypatch.setattr("tui.services.SearchWorker.search", fake_search)
    monkeypatch.setattr("tui.services.HealthProbe.probe", lambda self, force=False, only=None: {})

    app = SubsApp(config={}, media_paths=["الهيبة.mkv"], overrides={})

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            detail = app.query_one(DetailPane)
            content = detail.query_one("#detail-title").content
            assert "الهيبة" in content

    asyncio.run(run())


def test_enter_on_row_triggers_download_intent(app_with_fake_search):
    """Phase 2: Enter surfaces a 'would download' notification, doesn't crash."""
    app, _ = app_with_fake_search

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            await pilot.press("enter")
            await pilot.pause(0.3)
            # No exception means the action handled the no-worker case.

    asyncio.run(run())


def test_search_exception_is_contained(monkeypatch):
    """A backend failure must surface as last_error, not crash the UI."""

    def boom(self, state, media_path, engine=None):
        raise RuntimeError("network down")

    monkeypatch.setattr("tui.services.SearchWorker.search", boom)
    monkeypatch.setattr("tui.services.HealthProbe.probe", lambda self, force=False, only=None: {})

    app = SubsApp(config={}, media_paths=["x.mkv"], overrides={})

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.5)
            # App is still alive; error recorded.
            assert app.last_error is not None
            assert "network down" in app.last_error

    asyncio.run(run())
