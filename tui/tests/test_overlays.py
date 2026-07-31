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


def test_language_popover_enter_confirms_all_remaining_files():
    screen = LanguagePopover(
        languages={"en": "English", "ar": "العربية"},
        current="en",
        needs_scope_confirm=True,
        remaining_files=["a.mkv", "b.mkv"],
    )

    assert _drive_screen(screen, ["down", "enter", "enter"]) == ("ar", "all")


def test_engine_switcher_reopens_on_current_all_providers_choice():
    screen = EngineSwitcher(
        current=EngineMode.ALL_PROVIDERS,
        health={
            Provider.OPENSUBTITLES: HealthResult(
                provider=Provider.OPENSUBTITLES,
                configured=True,
                reachable=True,
                latency_ms=41,
            )
        },
    )

    assert _drive_screen(screen, ["enter"]) is EngineMode.ALL_PROVIDERS


def test_engine_switcher_auto_is_selectable():
    screen = EngineSwitcher(
        current=EngineMode.OPENSUBTITLES,
        health={},
    )

    assert _drive_screen(
        screen,
        ["down", "down", "down", "enter"],
    ) is EngineMode.AUTO


def test_engine_switcher_all_providers_is_a_first_class_choice():
    screen = EngineSwitcher(
        current=EngineMode.OPENSUBTITLES,
        health={},
    )

    assert _drive_screen(
        screen,
        ["down", "down", "down", "down", "enter"],
    ) is EngineMode.ALL_PROVIDERS


def test_engine_switcher_explains_modes_without_repeating_itself():
    screen = EngineSwitcher(
        current=EngineMode.AUTO,
        health={},
    )

    assert screen.HELP_TEXT == (
        "Choose a provider or search mode.\n"
        "Auto: first match wins  ·  All providers: combined results"
    )
    assert screen._label(EngineMode.AUTO) == (
        "Auto fallback  ·  SubSource → OpenSubtitles → SubDL"
    )
    assert screen._label(EngineMode.ALL_PROVIDERS) == (
        "All providers  ·  search every configured source"
    )


def test_engine_switcher_omits_repeated_unknown_health_status():
    screen = EngineSwitcher(
        current=EngineMode.OPENSUBTITLES,
        health={},
    )

    assert screen._label(EngineMode.OPENSUBTITLES) == "OpenSubtitles"
    assert screen._label(EngineMode.SUBDL) == "SubDL"
    assert screen._label(EngineMode.SUBSOURCE) == "SubSource"


def test_palette_filters_and_returns_action():
    result = _drive_screen(Palette(Keymap()), ["q", "u", "i", "t", "enter"])

    assert isinstance(result, Action)
    assert result.id == "app.quit"


def test_keymap_actions_are_callable_and_searchable():
    actions = default_actions()
    assert all(callable(action.run) for action in actions)
    assert [
        action.shortcut for action in actions if action.id.startswith("view.")
    ] == ["F1", "F2", "F3", "F4"]
    assert Keymap().by_id("engine.open").shortcut == "e"
    assert Keymap().search("engine all providers")[0].id == "engine.all-providers"


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
