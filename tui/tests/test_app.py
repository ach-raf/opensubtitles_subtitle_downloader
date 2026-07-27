import asyncio

import pytest
from textual.widgets import Button, ContentSwitcher, DataTable, Input, Static

from tui.app import ConfirmConfigExit, ConfirmConfigSave, ConfirmQuit, SubsApp
from tui.domain import Candidate, EngineMode, Provider, QueueStatus
from tui.search import CoordinatedSearchResult
from tui.widgets.overlays.engine_switcher import EngineSwitcher
from tui.widgets.overlays.lang_popover import LanguagePopover
from tui.widgets.results_table import ResultsTable
from tui.widgets.views import ConfigView


class FakeCoordinator:
    def __init__(self, candidates):
        self.candidates = candidates
        self.requests = []

    def concrete(self, provider, request):
        self.requests.append(request)
        return CoordinatedSearchResult(
            candidates=list(self.candidates),
            attempted=[provider],
            selected_provider=provider,
        )

    def auto(self, request, health=None):
        self.requests.append(request)
        return CoordinatedSearchResult(candidates=list(self.candidates))

    def merge(self, request, health=None):
        self.requests.append(request)
        return CoordinatedSearchResult(candidates=list(self.candidates))


@pytest.fixture
def configured_app(tmp_path):
    media = tmp_path / "الهيبة.S01E03.mkv"
    media.touch()
    candidates = [
        Candidate(
            provider=Provider.SUBDL,
            provider_id="1",
            release="الهيبة - S01E03 WEB-DL",
            language="ar",
            download_count=2400,
            score=94,
        ),
        Candidate(
            provider=Provider.SUBDL,
            provider_id="2",
            release="Al Hayba S01E03",
            language="ar",
            score=81,
        ),
    ]
    coordinator = FakeCoordinator(candidates)
    app = SubsApp(
        config={
            "general": {
                "preferred_backend": "subdl",
                "skip_interactive_menu": True,
            },
            "subdl": {
                "api_key": "configured",
                "languages": {"Arabic": "ar", "English": "en"},
            },
        },
        media_paths=[str(media)],
        overrides={},
        coordinator=coordinator,
    )
    return app, coordinator


def test_all_four_tabs_are_real_views(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            for key, view in (
                ("1", "search"),
                ("2", "queue"),
                ("3", "history"),
                ("4", "config"),
            ):
                await pilot.press(key)
                await pilot.pause()
                assert app.state.active_view == view
                assert (
                    app.query_one("#workspace", ContentSwitcher).current
                    == f"{view}-view"
                )

    asyncio.run(run())


def test_view_shortcuts_focus_each_primary_workspace(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            for key, selector in (
                ("2", "#queue-table"),
                ("3", "#history-table"),
                ("4", "#config-engine"),
                ("1", "#results-table"),
            ):
                await pilot.press(key)
                await pilot.pause()
                assert app.focused is app.query_one(selector)

    asyncio.run(run())


def test_escape_returns_query_focus_to_results(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            await pilot.press("slash")
            assert isinstance(app.focused, Input)

            await pilot.press("escape")
            await pilot.pause()
            assert app.focused is app.query_one(ResultsTable)

    asyncio.run(run())


def test_all_providers_choice_updates_engine_label_and_search_mode(configured_app):
    app, coordinator = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            app._engine_chosen((EngineMode.AUTO, True))
            await pilot.pause()

            assert app.merge_mode is True
            assert app.application_config.general.merge_results is True
            assert "ENGINE All providers" in str(
                app.query_one("#chip-engine", Button).label
            )
            assert coordinator.requests

    asyncio.run(run())


def test_repeated_view_switching_does_not_rebuild_unchanged_tables(
    configured_app,
):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            tables = [
                app.query_one(ResultsTable),
                app.query_one("#queue-table", DataTable),
                app.query_one("#history-table", DataTable),
            ]
            clear_counts = [0, 0, 0]
            for index, table in enumerate(tables):
                original_clear = table.clear

                def tracked_clear(
                    *args,
                    _index=index,
                    _clear=original_clear,
                    **kwargs,
                ):
                    clear_counts[_index] += 1
                    return _clear(*args, **kwargs)

                table.clear = tracked_clear

            for _ in range(8):
                await pilot.press("2", "down", "3", "1", "down", "up")
            await pilot.pause(0.1)

            assert clear_counts == [0, 0, 0]
            assert app.focused is app.query_one(ResultsTable)

    asyncio.run(run())


def test_lowercase_engine_and_language_shortcuts_open_choices(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, EngineSwitcher)
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("l")
            await pilot.pause()
            assert isinstance(app.screen, LanguagePopover)

    asyncio.run(run())


def test_query_submit_uses_edited_value(configured_app):
    app, coordinator = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await pilot.press("slash")
            query = app.query_one("#query-input", Input)
            query.value = "Director Cut"
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert app.last_search_request.query == "Director Cut"
            assert coordinator.requests[-1].query == "Director Cut"

    asyncio.run(run())


def test_results_and_multilingual_detail_are_visible(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert app.query_one(ResultsTable).row_count == 2
            assert "الهيبة" in app.query_one("#detail-title", Static).content
            detail = str(app.query_one("#detail-kv", Static).content)
            assert "Match" in detail
            assert "94" in detail
            assert detail.count("\n") <= 3
            assert str(app.query_one("#download-selected", Button).label) == "Get  ↵"
            assert str(app.query_one("#preview-selected", Button).label) == "View  p"
            assert str(app.query_one("#copy-url", Button).label) == "URL  y"

    asyncio.run(run())


def test_command_deck_chrome_matches_compact_visual_contract(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause(0.3)

            assert app.query_one("TopBar").region.height == 3
            assert app.query_one("QueryBar").region.height == 3
            assert "ENGINE" in str(app.query_one("#chip-engine", Button).label)
            assert "LANG" in str(app.query_one("#chip-language", Button).label)
            assert app.query_one("#chip-command", Button).label
            assert app.query_one("#chip-health", Static).content

            status = app.query_one("#status-settings", Static).content
            assert "engine" in status
            assert "lang" in status
            assert "utf-8" in status
            assert "clean" in status
            assert "sync" in status
            assert "HI" in status

    asyncio.run(run())


def test_search_workbench_exposes_mockup_panel_content(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause(0.3)

            results_panel = app.query_one("#results-panel")
            detail_panel = app.query_one("#detail-panel")
            assert results_panel.region.width >= detail_panel.region.width * 2
            assert 30 <= detail_panel.region.width <= 42
            assert "RESULTS" in app.query_one("#results-heading", Static).content
            assert "sorted by match" in app.query_one(
                "#results-heading", Static
            ).content.lower()
            assert "PREVIEW" in app.query_one("#preview-heading", Static).content
            assert app.query_one("#preview-selected", Button)
            assert app.query_one("#copy-url", Button)

    asyncio.run(run())


def test_results_table_keeps_release_and_numeric_score_visible(configured_app):
    app, coordinator = configured_app
    coordinator.candidates = [
        Candidate(
            provider=Provider.SUBDL,
            provider_id="long-release",
            release=(
                "Inception.2010.2160p.UHD.BluRay.REMUX."
                "HDR.HEVC.TrueHD.Atmos-FullReleaseName"
            ),
            language="en",
            download_count=48213,
            score=96,
        )
    ]

    async def run():
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause(0.3)

            table = app.query_one(ResultsTable)
            assert list(table.columns.values())[0].label.plain == "Release"
            release_column = list(table.columns.values())[0]
            assert release_column.width >= 75
            assert table.get_cell_at((0, 1)) == " EN"
            rendered_score = table.get_cell_at((0, len(table.columns) - 1))
            assert rendered_score.plain == " 96"
            assert table.max_scroll_x == 0

    asyncio.run(run())


def test_cursor_navigation_updates_typed_selection(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert app.current_candidate().provider is Provider.SUBDL
            await pilot.press("j")
            await pilot.pause()
            assert app.cursor_index == 1
            assert app.current_candidate().provider_id == "2"

    asyncio.run(run())


def test_completed_search_focuses_results_for_arrow_navigation(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(ResultsTable)
            assert app.focused is table

            await pilot.press("down")
            await pilot.pause()
            assert app.cursor_index == 1
            assert app.current_candidate().provider_id == "2"

    asyncio.run(run())


def test_cursor_change_does_not_rebuild_results_table(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(ResultsTable)
            original_clear = table.clear
            clear_calls = 0

            def tracked_clear(*args, **kwargs):
                nonlocal clear_calls
                clear_calls += 1
                return original_clear(*args, **kwargs)

            table.clear = tracked_clear
            await pilot.press("j")
            await pilot.pause(0.1)

            assert app.cursor_index == 1
            assert clear_calls == 0

    asyncio.run(run())


def test_rapid_cursor_input_does_not_replay_stale_highlights(configured_app):
    app, coordinator = configured_app
    coordinator.candidates = [
        Candidate(
            provider=Provider.SUBDL,
            provider_id=str(index),
            release=f"Release {index:02d}",
            language="ar",
            score=100 - index,
        )
        for index in range(40)
    ]

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            table = app.query_one(ResultsTable)
            move_count = 0
            original_move = table.move_cursor

            def tracked_move(*args, **kwargs):
                nonlocal move_count
                move_count += 1
                return original_move(*args, **kwargs)

            table.move_cursor = tracked_move
            for _ in range(25):
                table.action_cursor_down()
            await pilot.pause(0.1)

            assert table.cursor_row == 25
            assert app.cursor_index == 25
            assert move_count <= 25

    asyncio.run(run())


def test_enter_downloads_highlighted_result_from_focused_table(configured_app):
    app, _ = configured_app
    selected = []
    app.run_download = lambda _item_key, candidate, _overwrite: selected.append(
        candidate.key
    )

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            await pilot.press("down", "enter")
            await pilot.pause()

            assert selected == ["subdl:2"]

    asyncio.run(run())


def test_narrow_terminal_hides_detail_without_hiding_results(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test(size=(100, 32)) as pilot:
            await pilot.pause(0.2)
            assert app.query_one("#detail-panel").display is False
            assert app.query_one(ResultsTable).display is True
            assert app.query_one("#chip-command").display is False
            assert app.query_one("#chip-health").display is False
            assert app.query_one("#status-settings").display is False

    asyncio.run(run())


def test_stale_search_completion_cannot_replace_current_results(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            current = list(app.candidates)
            app._search_finished(
                app.state.active_item.key,
                app.search_generation - 1,
                app.last_search_request,
                CoordinatedSearchResult(candidates=[]),
            )
            assert app.candidates == current

    asyncio.run(run())


def test_auto_selection_uses_best_visible_candidate(configured_app):
    app, _ = configured_app
    calls = []
    app.application_config.general.auto_selection = True
    app.action_download_cursor = lambda: calls.append(app.current_candidate().key)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.3)
            assert calls == ["subdl:1"]

    asyncio.run(run())


def test_provider_failure_marks_item_failed_and_advances(tmp_path):
    first = tmp_path / "first.mkv"
    second = tmp_path / "second.mkv"
    first.touch()
    second.touch()
    fallback = Candidate(
        provider=Provider.SUBDL,
        provider_id="next",
        release="second",
        language="en",
    )

    class FailThenSucceedCoordinator(FakeCoordinator):
        def concrete(self, provider, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return CoordinatedSearchResult(
                    errors={provider: "service unavailable"},
                )
            return CoordinatedSearchResult(candidates=[fallback])

    coordinator = FailThenSucceedCoordinator([])
    app = SubsApp(
        config={
            "general": {
                "preferred_backend": "subdl",
                "skip_interactive_menu": True,
            },
            "subdl": {
                "api_key": "configured",
                "languages": {"English": "en"},
            },
        },
        media_paths=[str(first), str(second)],
        overrides={},
        coordinator=coordinator,
    )

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.4)
            assert app.state.queue[0].status is QueueStatus.FAILED
            assert app.state.queue[0].error == ("SubDL: service unavailable")
            assert app.state.active_item.path == second
            assert app.state.active_item.status is QueueStatus.AWAITING_PICK
            assert len(coordinator.requests) >= 2

    asyncio.run(run())


def test_quit_with_unfinished_queue_requires_confirmation(configured_app):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_request_quit()
            await pilot.pause()
            assert isinstance(app.screen, ConfirmQuit)
            assert app.screen.query_one(Static).region.x > 0
            assert app.screen.query_one(Static).region.y > 0

    asyncio.run(run())


def test_config_draft_survives_refresh_and_blocks_accidental_navigation(
    configured_app,
):
    app, _ = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await pilot.press("4")
            ads = app.query_one("#config-ads", Input)
            ads.value = "draft-ads.txt"
            original_engine = app.state.engine_mode
            original_language = app.state.language
            app._engine_chosen((EngineMode.AUTO, False))
            app._language_provider_scope = {Provider.SUBDL}
            app._language_chosen(("fr", "all"))
            await pilot.pause()
            assert app.query_one(ConfigView).dirty is True
            assert app.state.engine_mode is original_engine
            assert app.state.language == original_language
            assert app.config_draft.general.preferred_backend is EngineMode.AUTO
            assert app.config_draft.general.merge_results is False
            assert app.config_draft_language == "fr"

            app.notice = "background update"
            app._refresh_all()
            assert ads.value == "draft-ads.txt"

            await pilot.press("1")
            assert app.state.active_view == "config"
            assert isinstance(app.screen, ConfirmConfigExit)
            assert app.screen.query_one(Static).region.x > 0
            assert app.screen.query_one(Static).region.y > 0

            await pilot.press("d")
            await pilot.pause()
            assert app.query_one(ConfigView).dirty is False
            assert ads.value == ""
            assert app.state.active_view == "search"
            assert app.state.engine_mode is original_engine
            assert app.state.language == original_language
            assert app.application_config.general.preferred_backend is original_engine

    asyncio.run(run())


def test_confirmed_config_save_applies_engine_and_language_draft(
    configured_app,
):
    app, coordinator = configured_app

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await pilot.press("4")
            app._engine_chosen((EngineMode.AUTO, False))
            app._language_provider_scope = {Provider.SUBDL}
            app._language_chosen(("fr", "all"))

            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmConfigSave)
            assert app.state.engine_mode is not EngineMode.AUTO
            assert app.state.language != "fr"

            await pilot.press("enter")
            await pilot.pause()
            assert app.state.engine_mode is EngineMode.AUTO
            assert app.state.language == "fr"
            assert app.application_config.general.preferred_backend is EngineMode.AUTO
            assert (
                "fr"
                in app.application_config.providers[Provider.SUBDL].languages.values()
            )
            assert coordinator.requests[-1].language == "fr"
            assert len(coordinator.requests) >= 2

    asyncio.run(run())


def test_failed_config_write_keeps_live_state_and_dirty_draft(
    configured_app,
    tmp_path,
):
    app, _ = configured_app
    app.config_path = tmp_path / "config.yaml"

    def fail_save(_draft):
        raise PermissionError("read-only")

    app.config_repository.save = fail_save

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            original_engine = app.state.engine_mode
            await pilot.press("4")
            app._engine_chosen((EngineMode.AUTO, False))
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert app.state.engine_mode is original_engine
            assert app.application_config.general.preferred_backend is original_engine
            assert app.query_one(ConfigView).dirty is True
            assert "Could not save configuration" in app.last_error

    asyncio.run(run())
