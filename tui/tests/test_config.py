from ruamel.yaml import YAML

from tui.config import ConfigRepository
from tui.domain import EngineMode, Provider

CONFIG_TEXT = """\
# Keep this operator note
general:
  preferred_backend: ask  # preferred provider
  default_language: ar
  recursive_search: true
  subtitle_output_directory: subtitle-cache
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
    assert config.general.default_language == "ar"
    config.general.preferred_backend = EngineMode.ALL_PROVIDERS
    config.providers[Provider.SUBDL].languages["Japanese"] = "ja"

    diff = repo.save(config)
    reloaded = repo.load()

    assert reloaded.general.preferred_backend is EngineMode.ALL_PROVIDERS
    assert reloaded.general.default_language == "ar"
    assert reloaded.general.recursive_search is True
    assert reloaded.general.subtitle_output_directory == "subtitle-cache"
    assert "general.preferred_backend" in diff.changed_fields
    assert reloaded.providers[Provider.SUBDL].languages["Japanese"] == "ja"
    assert "subdl.languages.Japanese" in diff.changed_fields
    assert reloaded.extra["custom_section"]["untouched"] is True
    saved = path.read_text(encoding="utf-8")
    assert "future_setting: preserved" in saved
    assert "# Keep this operator note" in saved
    assert "# preferred provider" in saved
    assert not list(tmp_path.glob("*.tmp"))

    reloaded.general.default_language = "fr"
    assert "general.default_language" in repo.preview_diff(reloaded).changed_fields


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


def test_all_providers_round_trips_canonically(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "general:\n"
        "  preferred_backend: all-providers\n",
        encoding="utf-8",
    )
    repository = ConfigRepository(path)
    config = repository.load()

    assert config.general.preferred_backend is EngineMode.ALL_PROVIDERS

    repository.save(config)
    saved = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    assert saved["general"]["preferred_backend"] == "all-providers"
    assert set(saved["general"]) == {
        "preferred_backend",
        "default_language",
        "recursive_search",
        "subtitle_output_directory",
        "skip_interactive_menu",
        "sync_audio_to_subs",
        "auto_selection",
        "opt_force_utf8",
        "no_tui",
        "hearing_impaired",
        "show_ai_translated",
    }


def test_save_removes_obsolete_duplicate_backend_key(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "general:\n"
        "  preferred_backend: all-providers\n"
        "  merge_results: true\n",
        encoding="utf-8",
    )
    repository = ConfigRepository(path)

    repository.save(repository.load())

    saved = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    assert saved["general"] == {
        "preferred_backend": "all-providers",
        "default_language": "",
        "recursive_search": False,
        "subtitle_output_directory": "",
        "skip_interactive_menu": False,
        "sync_audio_to_subs": "ask",
        "auto_selection": False,
        "opt_force_utf8": True,
        "no_tui": False,
        "hearing_impaired": "include",
        "show_ai_translated": True,
    }
