import asyncio

from tui.app import SubsApp
from tui.domain import EngineMode, HealthResult, Provider
from tui.keymap import Action, Keymap, default_actions
from tui.widgets.overlays.engine_switcher import EngineSwitcher
from tui.widgets.overlays.lang_popover import LanguagePopover
from tui.widgets.overlays.palette import Palette

HOST_CONFIG = {
    "general": {
        "preferred_backend": "subdl",
        "skip_interactive_menu": True,
    },
    "subdl": {
        "api_key": "configured",
        "languages": {"English": "en", "Arabic": "ar"},
    },
}


def _drive_screen(screen, keys):
    result = {}

    async def run():
        app = SubsApp(config=HOST_CONFIG, media_paths=[], overrides={})
        async with app.run_test() as pilot:
            app.push_screen(screen, lambda value: result.setdefault("value", value))
            await pilot.pause()
            for key in keys:
                await pilot.press(key)
                await pilot.pause()

    asyncio.run(run())
    return result.get("value", "NO_DISMISS")


def test_language_popover_single_file_applies_immediately():
    screen = LanguagePopover(
        languages={"en": "English", "ar": "العربية"},
        current="en",
        needs_scope_confirm=False,
        remaining_files=[],
    )

    assert _drive_screen(screen, ["down", "enter"]) == ("ar", "current")


def test_language_popover_batch_requires_explicit_scope():
    screen = LanguagePopover(
        languages={"en": "English", "ar": "العربية"},
        current="en",
        needs_scope_confirm=True,
        remaining_files=["a.mkv", "b.mkv"],
    )

    assert _drive_screen(screen, ["down", "enter", "a"]) == ("ar", "all")


def test_engine_switcher_shows_advisory_health_and_returns_merge():
    screen = EngineSwitcher(
        current=EngineMode.OPENSUBTITLES,
        health={
            Provider.OPENSUBTITLES: HealthResult(
                provider=Provider.OPENSUBTITLES,
                configured=True,
                reachable=True,
                latency_ms=41,
            )
        },
        merge_mode=True,
    )

    assert _drive_screen(screen, ["down", "enter"]) == (
        EngineMode.SUBDL,
        True,
    )


def test_engine_switcher_auto_is_selectable():
    screen = EngineSwitcher(
        current=EngineMode.OPENSUBTITLES,
        health={},
        merge_mode=False,
    )

    assert _drive_screen(
        screen,
        ["down", "down", "down", "enter"],
    ) == (EngineMode.AUTO, False)


def test_palette_filters_and_returns_action():
    result = _drive_screen(Palette(Keymap()), ["q", "u", "i", "t", "enter"])

    assert isinstance(result, Action)
    assert result.id == "app.quit"


def test_keymap_actions_are_callable_and_searchable():
    assert all(callable(action.run) for action in default_actions())
    assert Keymap().search("engine merge")[0].id == "engine.merge"


def test_app_keymap_contains_configured_languages_and_all_engines():
    app = SubsApp(config=HOST_CONFIG, media_paths=[], overrides={})

    assert {"lang.set.en", "lang.set.ar"} <= {
        action.id for action in app.keymap.actions
    }
    assert {
        "engine.set.opensubtitles",
        "engine.set.subdl",
        "engine.set.subsource",
    } <= {action.id for action in app.keymap.actions}


def test_language_picker_uses_active_provider_languages_only():
    app = SubsApp(
        config={
            "general": {
                "preferred_backend": "subdl",
                "skip_interactive_menu": True,
            },
            "opensubtitles": {
                "username": "u",
                "password": "p",
                "api_key": "k",
                "user_agent": "a",
                "languages": {"English": "en"},
            },
            "subdl": {
                "api_key": "k",
                "languages": {"Arabic": "ar"},
            },
        },
        media_paths=[],
        overrides={},
    )

    async def run():
        async with app.run_test() as pilot:
            app.action_open_language()
            await pilot.pause()
            assert app.screen.languages == {"ar": "Arabic"}

    asyncio.run(run())
