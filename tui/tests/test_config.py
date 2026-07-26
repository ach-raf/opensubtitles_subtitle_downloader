from tui.config import ConfigRepository
from tui.domain import EngineMode, Provider

CONFIG_TEXT = """\
# Keep this operator note
general:
  preferred_backend: ask  # preferred provider
  skip_interactive_menu: false
  sync_audio_to_subs: ask
  auto_selection: false
  opt_force_utf8: true
  no_tui: false
  hearing_impaired: include
  show_ai_translated: true
  future_setting: preserved
opensubtitles:
  username: user
  password: pass
  api_key: os-secret
  user_agent: app
  languages:
    English: en
subdl:
  api_key: subdl-secret
  languages:
    English: en
subsource:
  api_key: source-secret
  languages:
    English: en
cleaning_subtitles:
  supported_media: [srt, ass]
  ads:
    separator: ","
    file_path: ""
custom_section:
  untouched: true
"""


def test_config_repository_round_trips_supported_fields_atomically(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    repo = ConfigRepository(path)
    config = repo.load()
    config.general.preferred_backend = EngineMode.SUBDL
    config.providers[Provider.SUBDL].languages["Japanese"] = "ja"

    diff = repo.save(config)
    reloaded = repo.load()

    assert reloaded.general.preferred_backend is EngineMode.SUBDL
    assert reloaded.providers[Provider.SUBDL].languages["Japanese"] == "ja"
    assert "subdl.languages.Japanese" in diff.changed_fields
    assert reloaded.extra["custom_section"]["untouched"] is True
    saved = path.read_text(encoding="utf-8")
    assert "future_setting: preserved" in saved
    assert "# Keep this operator note" in saved
    assert "# preferred provider" in saved
    assert not list(tmp_path.glob("*.tmp"))


def test_config_diff_never_contains_credentials(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    repo = ConfigRepository(path)
    config = repo.load()
    config.providers[Provider.SUBDL].values["api_key"] = "replacement-secret"

    diff = repo.save(config)

    assert "replacement-secret" not in repr(diff)
    assert diff.changed_fields == ["subdl.api_key"]


def test_missing_config_loads_safe_defaults(tmp_path):
    config = ConfigRepository(tmp_path / "missing.yaml").load()

    assert config.general.preferred_backend is EngineMode.ASK
    assert set(config.providers) == set(Provider)
