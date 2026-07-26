"""Phase 5 tests: Config tab toggles + ⌘S save-back to config.yaml.

The save-back must preserve unrelated keys and round-trip the policy. The
confirm modal gates the write (spec §6.6: one-line diff preview before commit).
"""

from __future__ import annotations

import asyncio
import os

import pytest
import yaml

from tui.app import SubsApp
from tui.state import RunPolicy
from tui.widgets.config_tab import ConfigTab


# --------------------------------------------------------------------------- #
# ConfigTab toggle behavior (driven via action methods directly)
# --------------------------------------------------------------------------- #
def test_config_tab_starts_from_current_policy():
    policy = RunPolicy(force_utf8=True, audio_sync="ask", clean_ads=True)
    tab = ConfigTab(policy=policy, ads_file_path="/ads.txt")
    assert tab.policy.force_utf8 is True
    assert tab.policy.audio_sync == "ask"
    assert tab.ads_file_path == "/ads.txt"


def test_config_tab_toggle_bool_flips_value():
    tab = ConfigTab(policy=RunPolicy(force_utf8=False), ads_file_path="")
    # Cursor 0 = Force UTF-8 (bool). Toggle it on.
    assert tab.policy.force_utf8 is False
    tab.action_toggle()
    assert tab.policy.force_utf8 is True
    tab.action_toggle()
    assert tab.policy.force_utf8 is False


def test_config_tab_toggle_sync_cycles_values():
    tab = ConfigTab(policy=RunPolicy(audio_sync="ask"), ads_file_path="")
    # Cursor 2 = Audio sync.
    tab._cursor = 2
    tab.action_toggle()
    assert tab.policy.audio_sync == "always"
    tab.action_toggle()
    assert tab.policy.audio_sync == "never"
    tab.action_toggle()
    assert tab.policy.audio_sync == "ask"


def test_config_tab_cancel_does_not_persist():
    """The App's _on_config_result('cancel', None) is a no-op — no policy write."""
    app = SubsApp(config={}, media_paths=[], overrides={})
    snapshot: dict = {}

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            # Capture the seeded policy AFTER mount (on_mount reseeds from config).
            snapshot["before"] = RunPolicy(**app.run_policy.__dict__)
            # Simulate the ConfigTab dismissing with a cancel.
            app._on_config_result(("cancel", None))
            await pilot.pause(0.1)
            snapshot["after"] = RunPolicy(**app.run_policy.__dict__)

    asyncio.run(run())
    # run_policy unchanged by the cancel.
    assert snapshot["after"].__dict__ == snapshot["before"].__dict__


def test_config_tab_action_cancel_emits_cancel_tuple():
    """The ConfigTab itself dismisses with ('cancel', None) on escape."""
    tab = ConfigTab(policy=RunPolicy(force_utf8=False), ads_file_path="")
    captured = []
    tab.dismiss = lambda r: captured.append(r)
    tab.action_cancel()
    assert captured == [("cancel", None)]


# --------------------------------------------------------------------------- #
# Save-back round-trip through the App (real temp config file)
# --------------------------------------------------------------------------- #
def test_config_save_back_round_trips_and_preserves_keys(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "general:\n"
        "  opt_force_utf8: true\n"
        "  sync_audio_to_subs: ask\n"
        "  auto_selection: false\n"
        "cleaning_subtitles:\n"
        "  ads:\n    file_path: ''\n"
        "opensubtitles:\n  api_key: KEEPME\n",
        encoding="utf-8",
    )
    with open(cfg_path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    app = SubsApp(
        config=config,
        media_paths=[],
        overrides={},
        config_path=str(cfg_path),
    )
    # Seed run_policy from config so the App reflects the file.
    from tui.services import ConfigIO

    app.run_policy = ConfigIO.run_policy_from_config(config)
    app.run_policy.force_utf8 = False
    app.run_policy.audio_sync = "always"

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            # Simulate the save-confirm flow: apply policy, confirm yes.
            new_policy = RunPolicy(
                force_utf8=False,
                audio_sync="always",
                clean_ads=True,
                ads_file_path=None,
            )
            app._on_config_result(("save", new_policy))
            await pilot.pause(0.2)
            # A confirm screen is now up; press 'y' to commit.
            await pilot.press("y")
            await pilot.pause(0.2)

    asyncio.run(run())

    # Reload the file and verify.
    with open(cfg_path, "r", encoding="utf-8") as fh:
        reloaded = yaml.safe_load(fh)
    assert reloaded["general"]["opt_force_utf8"] is False
    assert reloaded["general"]["sync_audio_to_subs"] is True  # always -> true
    # Unrelated key preserved.
    assert reloaded["opensubtitles"]["api_key"] == "KEEPME"


def test_config_save_cancel_does_not_write(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    original = (
        "general:\n  opt_force_utf8: true\n  sync_audio_to_subs: ask\n"
        "  auto_selection: false\ncleaning_subtitles:\n  ads:\n    file_path: ''\n"
    )
    cfg_path.write_text(original, encoding="utf-8")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    app = SubsApp(
        config=config, media_paths=[], overrides={}, config_path=str(cfg_path)
    )

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            new_policy = RunPolicy(force_utf8=False, audio_sync="always")
            app._on_config_result(("save", new_policy))
            await pilot.pause(0.2)
            # Press 'n' to cancel the write.
            await pilot.press("n")
            await pilot.pause(0.2)

    asyncio.run(run())

    # File untouched.
    assert cfg_path.read_text(encoding="utf-8") == original


def test_config_diff_summary_lists_changed_fields():
    app = SubsApp(
        config={"general": {"opt_force_utf8": True}},
        media_paths=[],
        overrides={},
        config_path="/tmp/config.yaml",
    )
    old = RunPolicy(force_utf8=True, audio_sync="ask", auto_select=False)
    app.run_policy = old
    new = RunPolicy(force_utf8=False, audio_sync="always", auto_select=False)
    diff = app._config_diff_summary(new)
    assert "opt_force_utf8" in diff
    assert "sync_audio_to_subs" in diff


def test_config_diff_summary_empty_when_no_changes():
    app = SubsApp(
        config={},
        media_paths=[],
        overrides={},
        config_path="/tmp/config.yaml",
    )
    p = RunPolicy(force_utf8=True, audio_sync="ask", auto_select=False, ads_file_path=None)
    app.run_policy = p
    assert app._config_diff_summary(p) == ""
