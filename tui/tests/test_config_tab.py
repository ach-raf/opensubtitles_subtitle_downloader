import asyncio

import yaml
from textual.widgets import Input, Select, Switch

from tui.app import ConfirmConfigSave, SubsApp
from tui.domain import EngineMode
from tui.widgets.views import ConfigView

CONFIG_TEXT = """\
general:
  preferred_backend: subdl
  merge_results: false
  skip_interactive_menu: true
  sync_audio_to_subs: ask
  auto_selection: false
  opt_force_utf8: true
  no_tui: false
  hearing_impaired: include
  show_ai_translated: true
subdl:
  api_key: configured
  languages:
    English: en
    Arabic: ar
opensubtitles:
  languages:
    English: en
subsource:
  languages:
    English: en
cleaning_subtitles:
  enabled: true
  supported_media: [srt, ass]
  ads:
    separator: ","
    file_path: ""
unrelated:
  keep: true
"""


def test_config_is_a_real_view_with_all_supported_controls(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    app = SubsApp(
        config=yaml.safe_load(CONFIG_TEXT),
        media_paths=[],
        overrides={},
        config_path=str(path),
    )

    async def run():
        async with app.run_test() as pilot:
            await pilot.press("f4")
            await pilot.pause()
            assert app.state.active_view == "config"
            view = app.query_one(ConfigView)
            assert view.query_one("#config-sync", Select)
            assert view.query_one("#config-hi", Select)
            assert view.query_one("#config-skip", Switch)
            assert view.query_one("#config-no-tui", Switch)
            assert view.query_one("#config-utf8", Switch)
            assert view.query_one("#config-auto", Switch)
            assert view.query_one("#config-ai", Switch)
            assert view.query_one("#config-clean", Switch)
            assert view.query_one("#config-ads", Input)
            assert "draft" in str(view.query_one(".view-subtitle").content).lower()
            assert "Ctrl+S" in str(app.query_one("#status-hints").content)

    asyncio.run(run())


def test_config_keeps_a_usable_scroll_viewport_at_standard_terminal_size(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    app = SubsApp(
        config=yaml.safe_load(CONFIG_TEXT),
        media_paths=[],
        overrides={},
        config_path=str(path),
    )

    async def run():
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("f4")
            await pilot.pause()

            scroll = app.query_one("#config-scroll")
            assert scroll.region.height >= 10
            assert scroll.max_scroll_y < 50

    asyncio.run(run())


def test_config_save_round_trips_every_edited_field_atomically(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    app = SubsApp(
        config=yaml.safe_load(CONFIG_TEXT),
        media_paths=[],
        overrides={},
        config_path=str(path),
    )

    async def run():
        async with app.run_test() as pilot:
            await pilot.press("f4")
            await pilot.pause()
            app._engine_chosen((EngineMode.AUTO, True))
            app.query_one("#config-sync", Select).value = "always"
            app.query_one("#config-hi", Select).value = "only"
            app.query_one("#config-skip", Switch).value = False
            app.query_one("#config-no-tui", Switch).value = True
            app.query_one("#config-utf8", Switch).value = False
            app.query_one("#config-auto", Switch).value = True
            app.query_one("#config-ai", Switch).value = False
            app.query_one("#config-clean", Switch).value = False
            app.query_one("#config-ads", Input).value = str(tmp_path / "custom-ads.txt")
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmConfigSave)
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(run())
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["general"]["sync_audio_to_subs"] is True
    assert saved["general"]["preferred_backend"] == "auto"
    assert saved["general"]["merge_results"] is True
    assert saved["general"]["hearing_impaired"] == "only"
    assert saved["general"]["skip_interactive_menu"] is False
    assert saved["general"]["no_tui"] is True
    assert saved["general"]["opt_force_utf8"] is False
    assert saved["general"]["auto_selection"] is True
    assert saved["general"]["show_ai_translated"] is False
    assert saved["cleaning_subtitles"]["enabled"] is False
    assert saved["cleaning_subtitles"]["ads"]["file_path"].endswith("custom-ads.txt")
    assert saved["unrelated"]["keep"] is True
    assert not list(tmp_path.glob("*.tmp"))
