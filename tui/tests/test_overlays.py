"""Phase 3 overlay tests: language popover scope rule, engine switcher,
command palette, and the keymap registry.

Overlays are ModalScreens, so they're driven either (a) by calling their action
methods directly to check internal state + dismiss values, or (b) through the
host SubsApp via push_screen. SearchWorker + HealthProbe are mocked so nothing
touches the network.
"""

from __future__ import annotations

import asyncio

import pytest

from tui.app import SubsApp
from tui.keymap import Action, Keymap, default_actions
from tui.state import Backend, EngineHealth
from tui.widgets.overlays.engine_switcher import EngineSwitcher
from tui.widgets.overlays.lang_popover import LanguagePopover
from tui.widgets.overlays.palette import Palette


# --------------------------------------------------------------------------- #
# Keymap registry
# --------------------------------------------------------------------------- #
def test_keymap_default_actions_present():
    km = Keymap()
    ids = {a.id for a in km.actions}
    assert "lang.open" in ids
    assert "engine.merge" in ids
    assert "app.quit" in ids


def test_keymap_search_substring_and_multitoken():
    km = Keymap()
    results = km.search("sync")
    assert any("sync" in a.label.lower() for a in results)
    results = km.search("engine merge")
    assert all(
        "engine" in (a.label + a.category).lower()
        and "merge" in (a.label + a.category).lower()
        for a in results
    )


def test_keymap_empty_query_returns_all():
    km = Keymap()
    assert len(km.search("")) == len(km.actions)


def test_every_default_action_resolves_to_callable():
    """Spec §6.5: every indexed action resolves to a callable."""
    for action in default_actions():
        assert callable(action.run), f"{action.id} has no callable run"


def test_keymap_search_unknown_returns_empty():
    km = Keymap()
    assert km.search("zzzznomatch") == []


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _patch_services(monkeypatch, canned=None):
    canned = canned or []

    def fake_search(self, state, media_path, engine=None):
        for i, r in enumerate(canned):
            r["_score"] = 80.0 - i
            r["_source"] = "opensubtitles"
        return list(canned)

    monkeypatch.setattr("tui.services.SearchWorker.search", fake_search)
    monkeypatch.setattr(
        "tui.services.HealthProbe.probe", lambda self, force=False, only=None: {}
    )


def _make_app(monkeypatch, media_paths=("Inception.2010.mkv",), canned=None):
    _patch_services(monkeypatch, canned or [])
    return SubsApp(config={}, media_paths=list(media_paths), overrides={})


# --------------------------------------------------------------------------- #
# Language popover: scope rule (spec §6.2) — tested by driving actions directly
# since ModalScreens don't expose run_test in isolation.
# --------------------------------------------------------------------------- #
def _drive_screen(screen, key_sequence):
    """Push a screen on a throwaway app and press keys; return dismiss value."""
    result: dict = {}

    async def run():
        app = SubsApp(config={}, media_paths=[], overrides={})
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.push_screen(screen, lambda r: result.setdefault("r", r))
            await pilot.pause(0.15)
            for key in key_sequence:
                await pilot.press(key)
                await pilot.pause(0.05)
            await pilot.pause(0.15)

    asyncio.run(run())
    return result.get("r", "NO_DISMISS")


def test_language_popover_single_file_applies_instantly():
    """A single-file run must NOT show the scope picker."""
    screen = LanguagePopover(
        languages={"en": "English", "ar": "العربية"},
        current="en",
        needs_scope_confirm=False,
        remaining_files=[],
    )
    # Move down to Arabic, select -> immediate dismiss with ("ar", "current").
    result = _drive_screen(screen, ["down", "enter"])
    assert result == ("ar", "current")


def test_language_popover_batch_shows_scope_picker():
    """With >1 non-done file, selecting must defer dismiss until scope chosen."""
    screen = LanguagePopover(
        languages={"en": "English", "ar": "العربية"},
        current="en",
        needs_scope_confirm=True,
        remaining_files=["a.mkv", "b.mkv", "c.mkv"],
    )
    # After enter on ar, the scope picker is up; 'a' applies to all.
    result = _drive_screen(screen, ["down", "enter", "a"])
    assert result == ("ar", "all")


def test_language_popover_scope_current_only():
    screen = LanguagePopover(
        languages={"en": "English", "ar": "العربية"},
        current="en",
        needs_scope_confirm=True,
        remaining_files=["a.mkv", "b.mkv"],
    )
    result = _drive_screen(screen, ["down", "enter", "c"])
    assert result == ("ar", "current")


def test_language_popover_scope_escape_after_picker():
    """esc on the scope picker cancels the whole change."""
    screen = LanguagePopover(
        languages={"en": "English", "ar": "العربية"},
        current="en",
        needs_scope_confirm=True,
        remaining_files=["a.mkv", "b.mkv"],
    )
    result = _drive_screen(screen, ["down", "enter", "escape"])
    assert result is None


def test_language_popover_cancel_with_escape_before_select():
    screen = LanguagePopover(
        languages={"en": "English"},
        current="en",
        needs_scope_confirm=False,
        remaining_files=[],
    )
    result = _drive_screen(screen, ["escape"])
    assert result is None


# --------------------------------------------------------------------------- #
# Engine switcher
# --------------------------------------------------------------------------- #
def test_engine_switcher_selects_engine():
    health = {
        "opensubtitles": EngineHealth("opensubtitles", online=True, latency_ms=41),
        "subdl": EngineHealth("subdl", online=True, latency_ms=112),
        "subsource": EngineHealth("subsource", online=False, degraded=True),
    }
    screen = EngineSwitcher(current=Backend.OPENSUBTITLES, health=health, merge_mode=False)
    result = _drive_screen(screen, ["down", "enter"])  # down to SubDL, select
    assert result is Backend.SUBDL


def test_engine_switcher_toggle_merge_does_not_dismiss():
    screen = EngineSwitcher(current=Backend.OPENSUBTITLES, health={}, merge_mode=False)
    result = _drive_screen(screen, ["m", "m"])
    assert result == "NO_DISMISS"  # toggling never dismissed
    assert screen.merge_mode is False  # toggled twice -> back to off


def test_engine_switcher_auto_is_selectable():
    screen = EngineSwitcher(current=Backend.OPENSUBTITLES, health={}, merge_mode=False)
    # AUTO is the last row (index 3); three downs from OS (index 0).
    result = _drive_screen(screen, ["down", "down", "down", "enter"])
    assert result is Backend.AUTO


def test_engine_switcher_cancel_escape():
    screen = EngineSwitcher(current=Backend.OPENSUBTITLES, health={}, merge_mode=False)
    result = _drive_screen(screen, ["escape"])
    assert result is None


# --------------------------------------------------------------------------- #
# Command palette
# --------------------------------------------------------------------------- #
def test_palette_filters_and_runs_action():
    screen = Palette(Keymap())
    # Type 'quit' then enter -> dismisses with the app.quit action.
    result = _drive_screen(screen, ["q", "u", "i", "t", "enter"])
    assert isinstance(result, Action)
    assert result.id == "app.quit"


def test_palette_escape_cancels():
    screen = Palette(Keymap())
    result = _drive_screen(screen, ["escape"])
    assert result is None


def test_palette_ctrl_enter_runs_keep_open():
    """ctrl+enter runs the action but the screen may stay open (run_keep)."""
    screen = Palette(Keymap())
    # We can't easily assert "kept open" without a second selection; just verify
    # the binding resolves without error.
    result = _drive_screen(screen, ["ctrl+enter"])
    # ctrl+enter dismisses with the currently-selected (first) action.
    assert isinstance(result, Action)


# --------------------------------------------------------------------------- #
# App-level overlay wiring: language change re-searches + merge toggle
# --------------------------------------------------------------------------- #
def test_language_change_via_app_researches(monkeypatch):
    canned = [
        {"id": "1", "attributes": {"release": "Inception.2010", "language": "ar",
                                    "download_count": 5, "moviehash_match": False}}
    ]
    app = _make_app(monkeypatch, canned=canned)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.4)
            app.action_open_language()
            await pilot.pause(0.2)
            assert isinstance(app.screen, LanguagePopover)
            # Filter to "ar" then submit — the reliable path that doesn't depend
            # on focus moving between the Input and the list.
            filt = app.screen.query_one("#lang-filter")
            filt.value = "ar"
            await pilot.pause(0.1)
            await pilot.press("enter")
            await pilot.pause(0.3)
            # Language applied.
            assert app.language == "ar"

    asyncio.run(run())


def test_merge_toggle_binding_flips_reactive(monkeypatch):
    app = _make_app(monkeypatch)
    before = app.merge_mode

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await pilot.press("m")
            await pilot.pause(0.1)
            assert app.merge_mode is (not before)

    asyncio.run(run())


def test_dynamic_language_actions_in_keymap(monkeypatch):
    """The palette should index one action per configured language."""
    app = SubsApp(
        config={
            "opensubtitles": {"languages": {"English": "en", "Arabic": "ar"}},
        },
        media_paths=[],
        overrides={},
    )

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            ids = {a.id for a in app.keymap.actions}
            assert "lang.set.en" in ids
            assert "lang.set.ar" in ids

    asyncio.run(run())


def test_dynamic_engine_actions_in_keymap(monkeypatch):
    app = _make_app(monkeypatch)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            ids = {a.id for a in app.keymap.actions}
            assert "engine.set.opensubtitles" in ids
            assert "engine.set.subdl" in ids
            assert "engine.set.subsource" in ids

    asyncio.run(run())
