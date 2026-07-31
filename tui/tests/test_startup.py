import json
import subprocess
import sys
from pathlib import Path

import pytest

import download_subs
from download_subs import (
    SubtitleBackend,
    _build_arg_parser,
    _resolve_path_options,
)
from tui.headless import HeadlessBatchSummary


def test_cli_accepts_all_providers_backend():
    args = _build_arg_parser().parse_args(
        ["--backend", "all-providers", "movie.mkv"]
    )
    assert args.backend == "all-providers"
    assert download_subs.SubtitleBackend(args.backend) is (
        download_subs.SubtitleBackend.ALL_PROVIDERS
    )


def test_cli_backend_overrides_configured_backend():
    config = {
        "general": {
            "preferred_backend": "subdl",
        }
    }
    assert download_subs._resolve_backend("opensubtitles", config) is (
        SubtitleBackend.OPENSUBTITLES
    )


def test_canonical_all_providers_raw_config_resolves_directly():
    assert download_subs._resolve_backend(
        None,
        {
            "general": {
                "preferred_backend": "all-providers",
            }
        },
    ) is SubtitleBackend.ALL_PROVIDERS


def test_all_providers_language_fallback_uses_first_non_empty_provider():
    config = {
        "general": {},
        "opensubtitles": {"languages": {}},
        "subdl": {"languages": {"French": "fr", "Arabic": "ar"}},
        "subsource": {"languages": {"English": "en"}},
    }

    assert download_subs._resolve_language(
        None,
        config,
        SubtitleBackend.ALL_PROVIDERS,
    ) == ("fr", "provider")


@pytest.mark.parametrize(
    ("cli_language", "general", "want"),
    [
        (" AR ", {"default_language": "fr"}, ("ar", "cli")),
        (None, {"default_language": " FR "}, ("fr", "config")),
        (None, {}, ("en", "provider")),
    ],
)
def test_language_resolution_precedence(cli_language, general, want):
    config = {
        "general": general,
        "subdl": {"languages": {"English": "en", "Arabic": "ar"}},
    }

    assert download_subs._resolve_language(
        cli_language,
        config,
        download_subs.SubtitleBackend.SUBDL,
    ) == want


def test_language_resolution_reports_missing_provider_default():
    assert download_subs._resolve_language(
        None,
        {"general": {}, "subdl": {"languages": {}}},
        download_subs.SubtitleBackend.SUBDL,
    ) == ("", "missing")


def test_language_resolution_treats_whitespace_cli_value_as_absent():
    assert download_subs._resolve_language(
        "   ",
        {
            "general": {"default_language": " FR "},
            "subdl": {"languages": {"English": "en"}},
        },
        download_subs.SubtitleBackend.SUBDL,
    ) == ("fr", "config")


def test_tui_entry_import_does_not_load_legacy_providers():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; import download_subs; "
                "print(json.dumps(sorted(name for name in sys.modules "
                "if name in {'library.OpenSubtitles', 'library.SubDL', "
                "'library.SubSource', 'library.subtitle_utils', 'thefuzz'})))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []


def test_path_options_use_config_defaults_relative_to_config_file(tmp_path):
    config_path = tmp_path / "settings" / "config.yaml"
    args = _build_arg_parser().parse_args(["movie.mkv"])

    recursive, output_directory = _resolve_path_options(
        args,
        {
            "general": {
                "recursive_search": True,
                "subtitle_output_directory": "subtitle-cache",
            }
        },
        config_path,
    )

    assert recursive is True
    assert output_directory == config_path.parent / "subtitle-cache"


def test_path_options_allow_cli_to_disable_configured_values(tmp_path):
    args = _build_arg_parser().parse_args(
        ["--no-recursive", "--output-next-to-media", "movie.mkv"]
    )

    recursive, output_directory = _resolve_path_options(
        args,
        {
            "general": {
                "recursive_search": True,
                "subtitle_output_directory": str(tmp_path / "configured"),
            }
        },
        tmp_path / "config.yaml",
    )

    assert recursive is False
    assert output_directory is None


def test_path_options_resolve_cli_output_from_working_directory(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    args = _build_arg_parser().parse_args(
        ["--recursive", "--output-dir", "cli-subs", "movie.mkv"]
    )

    recursive, output_directory = _resolve_path_options(
        args,
        {"general": {}},
        Path("elsewhere/config.yaml"),
    )

    assert recursive is True
    assert output_directory == (tmp_path / "cli-subs").resolve()


def test_legacy_expands_recursively_before_provider_dispatch(
    tmp_path,
    monkeypatch,
):
    nested_media = tmp_path / "library" / "Movie" / "movie.mkv"
    nested_media.parent.mkdir(parents=True)
    nested_media.touch()
    output_directory = tmp_path / "subtitles"
    calls = {}

    class FakeDownloader:
        config = {
            "general": {
                "skip_interactive_menu": True,
                "preferred_backend": "subdl",
            },
            "subdl": {"languages": {"English": "en"}},
        }

        def download_subtitles(self, media_paths, language, backend):
            calls["download"] = (media_paths, language, backend)

        def _get_backend_from_config(self):
            return download_subs.SubtitleBackend.SUBDL

    def build_downloader(config_path, *, output_directory=None):
        calls["constructor"] = (config_path, output_directory)
        return FakeDownloader()

    monkeypatch.setattr(download_subs, "SubtitleDownloader", build_downloader)

    download_subs.run_legacy(
        "config.yaml",
        [str(tmp_path / "library")],
        recursive=True,
        output_directory=output_directory,
    )

    assert calls["constructor"] == ("config.yaml", output_directory)
    assert calls["download"][0] == [str(nested_media.resolve())]


def test_legacy_uses_resolved_language_without_opening_language_menu(
    tmp_path,
    monkeypatch,
):
    media = tmp_path / "movie.mkv"
    media.touch()
    calls = {}

    class FakeDownloader:
        config = {
            "general": {"preferred_backend": "subdl"},
            "subdl": {"languages": {"English": "en"}},
        }

        def _get_backend_from_config(self):
            return download_subs.SubtitleBackend.SUBDL

        def interactive_menu(self):
            raise AssertionError("language menu must not open in no-TUI mode")

        def download_subtitles(self, paths, language, backend):
            calls["dispatch"] = (paths, language, backend)

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )

    download_subs.run_legacy(
        "config.yaml",
        [str(media)],
        resolved_language=("ar", "cli"),
    )

    assert calls["dispatch"][1:] == (
        "ar",
        download_subs.SubtitleBackend.SUBDL,
    )


def test_legacy_explicit_backend_controls_dispatch_and_provider_fallback(
    tmp_path,
    monkeypatch,
):
    media = tmp_path / "movie.mkv"
    media.touch()
    calls = {}

    class FakeDownloader:
        config = {
            "general": {"preferred_backend": "opensubtitles"},
            "opensubtitles": {"languages": {"French": "fr"}},
            "subdl": {"languages": {"Arabic": "ar"}},
        }

        def _get_backend_from_config(self):
            return download_subs.SubtitleBackend.OPENSUBTITLES

        def download_subtitles(self, paths, language, backend):
            calls["dispatch"] = (paths, language, backend)

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )

    download_subs.run_legacy(
        "config.yaml",
        [str(media)],
        backend=download_subs.SubtitleBackend.SUBDL,
    )

    assert calls["dispatch"][1:] == (
        "ar",
        download_subs.SubtitleBackend.SUBDL,
    )


def test_legacy_resolves_config_language_without_opening_language_menu(
    tmp_path,
    monkeypatch,
):
    media = tmp_path / "movie.mkv"
    media.touch()
    calls = {}

    class FakeDownloader:
        config = {
            "general": {
                "preferred_backend": "subdl",
                "default_language": " FR ",
                "skip_interactive_menu": False,
            },
            "subdl": {"languages": {"English": "en"}},
        }

        def _get_backend_from_config(self):
            return download_subs.SubtitleBackend.SUBDL

        def interactive_menu(self):
            raise AssertionError("language menu must not open in no-TUI mode")

        def download_subtitles(self, paths, language, backend):
            calls["dispatch"] = (paths, language, backend)

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )

    download_subs.run_legacy("config.yaml", [str(media)])

    assert calls["dispatch"][1:] == (
        "fr",
        download_subs.SubtitleBackend.SUBDL,
    )


def test_legacy_missing_language_reports_cli_and_config_options(
    tmp_path,
    monkeypatch,
    capsys,
):
    media = tmp_path / "movie.mkv"
    media.touch()

    class FakeDownloader:
        config = {
            "general": {"preferred_backend": "subdl"},
            "subdl": {"languages": {}},
        }

        def _get_backend_from_config(self):
            return download_subs.SubtitleBackend.SUBDL

        def interactive_menu(self):
            raise AssertionError("language menu must not open in no-TUI mode")

        def download_subtitles(self, *_args):
            raise AssertionError("download must not start without a language")

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )

    with pytest.raises(SystemExit):
        download_subs.run_legacy("config.yaml", [str(media)])

    output = capsys.readouterr().out
    assert "--lang" in output
    assert "general.default_language" in output


def test_main_passes_resolved_path_options_to_tui(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "general:\n"
        "  recursive_search: false\n"
        "  subtitle_output_directory: configured-subs\n",
        encoding="utf-8",
    )
    media = tmp_path / "movie.mkv"
    media.touch()
    calls = {}

    import tui.app

    monkeypatch.setattr(download_subs, "__file__", str(tmp_path / "download_subs.py"))
    monkeypatch.setattr(tui.app, "run_tui", lambda **kwargs: calls.update(kwargs))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_subs.py",
            "--recursive",
            "--output-dir",
            "cli-subs",
            str(media),
        ],
    )
    monkeypatch.chdir(tmp_path)

    download_subs.main()

    assert calls["recursive_search"] is True
    assert calls["output_directory"] == (tmp_path / "cli-subs").resolve()


@pytest.mark.parametrize("force_no_tui", [False, True])
def test_main_forwards_cli_language_and_backend_consistently(
    tmp_path,
    monkeypatch,
    force_no_tui,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "general:\n"
        "  preferred_backend: opensubtitles\n"
        "  default_language: fr\n"
        "opensubtitles:\n"
        "  languages:\n"
        "    French: fr\n"
        "subdl:\n"
        "  languages:\n"
        "    Arabic: ar\n",
        encoding="utf-8",
    )
    media = tmp_path / "movie.mkv"
    media.touch()
    calls = {}

    import tui.app

    monkeypatch.setattr(download_subs, "__file__", str(tmp_path / "download_subs.py"))
    monkeypatch.setattr(
        download_subs,
        "run_legacy",
        lambda *args, **kwargs: calls.update(
            {"mode": "legacy", "args": args, "kwargs": kwargs}
        ),
    )
    monkeypatch.setattr(
        tui.app,
        "run_tui",
        lambda **kwargs: calls.update({"mode": "tui", "kwargs": kwargs}),
    )
    argv = [
        "download_subs.py",
        "--lang",
        " AR ",
        "--backend",
        "subdl",
        str(media),
    ]
    if force_no_tui:
        argv.insert(1, "--no-tui")
    monkeypatch.setattr(sys, "argv", argv)

    download_subs.main()

    assert calls["mode"] == ("legacy" if force_no_tui else "tui")
    if force_no_tui:
        assert calls["kwargs"]["resolved_language"] == ("ar", "cli")
        assert calls["kwargs"]["backend"] is download_subs.SubtitleBackend.SUBDL
    else:
        assert calls["kwargs"]["language_resolution"] == ("ar", "cli")
        assert calls["kwargs"]["overrides"] == {
            "lang": "ar",
            "backend": "subdl",
        }


def test_legacy_flat_output_rejects_duplicate_media_stems(tmp_path, monkeypatch):
    first = tmp_path / "library" / "A" / "Movie.mkv"
    second = tmp_path / "library" / "B" / "Movie.mp4"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.touch()
    second.touch()
    calls = []

    class FakeDownloader:
        config = {
            "general": {
                "skip_interactive_menu": True,
                "preferred_backend": "subdl",
            },
            "subdl": {"languages": {"English": "en"}},
        }

        def _get_backend_from_config(self):
            return download_subs.SubtitleBackend.SUBDL

        def download_subtitles(self, *_args):
            calls.append("downloaded")

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )

    with pytest.raises(SystemExit):
        download_subs.run_legacy(
            "config.yaml",
            [str(tmp_path / "library")],
            recursive=True,
            output_directory=tmp_path / "subtitles",
        )

    assert calls == []


def test_legacy_dispatch_uses_normalized_files_without_provider_rescanning(
    tmp_path,
):
    media = tmp_path / "Movie.webm"
    media.touch()
    processed = []

    class FakeClient:
        def process_media_file(self, path, language):
            processed.append((path, language))

    downloader = object.__new__(download_subs.SubtitleDownloader)
    downloader.console = download_subs.console
    downloader.subdl_client = FakeClient()
    downloader.opensubtitles_client = None
    downloader.subsource_client = None
    downloader._choose_backend = (
        lambda _paths, _backend: download_subs.SubtitleBackend.SUBDL
    )
    downloader._init_subdl = lambda: None

    downloader.download_subtitles(
        [str(media)],
        "en",
        download_subs.SubtitleBackend.SUBDL,
    )

    assert processed == [(str(media), "en")]


def test_no_tui_all_providers_uses_headless_runner(tmp_path, monkeypatch):
    media = tmp_path / "movie.mkv"
    media.touch()
    calls = {"legacy_downloads": []}

    class FakeDownloader:
        config = {
            "general": {"preferred_backend": "all-providers"},
            "opensubtitles": {"languages": {"Arabic": "ar"}},
        }

        def download_subtitles(self, *args):
            calls["legacy_downloads"].append(args)

    class FakeRunner:
        def run(self, media_paths, language):
            calls["run"] = (media_paths, language)
            return HeadlessBatchSummary(attempted=1, succeeded=1, failed=0)

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )
    monkeypatch.setattr(
        download_subs,
        "_build_headless_all_providers_runner",
        lambda *_args, **_kwargs: FakeRunner(),
        raising=False,
    )

    download_subs.run_legacy(
        "config.yaml",
        [str(media)],
        backend=download_subs.SubtitleBackend.ALL_PROVIDERS,
        resolved_language=("ar", "cli"),
    )

    assert calls["run"] == ([media.resolve()], "ar")
    assert calls["legacy_downloads"] == []


def test_no_tui_all_providers_exits_when_every_file_fails(
    tmp_path,
    monkeypatch,
):
    media = tmp_path / "movie.mkv"
    media.touch()

    class FakeDownloader:
        config = {"general": {"preferred_backend": "all-providers"}}

    class FakeRunner:
        def run(self, _media_paths, _language):
            return HeadlessBatchSummary(attempted=1, succeeded=0, failed=1)

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )
    monkeypatch.setattr(
        download_subs,
        "_build_headless_all_providers_runner",
        lambda *_args, **_kwargs: FakeRunner(),
        raising=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        download_subs.run_legacy(
            "config.yaml",
            [str(media)],
            backend=download_subs.SubtitleBackend.ALL_PROVIDERS,
            resolved_language=("ar", "cli"),
        )

    assert exc_info.value.code == 1


def test_no_tui_all_providers_emits_partial_batch_summary(
    tmp_path,
    monkeypatch,
    capsys,
):
    media = tmp_path / "movie.mkv"
    media.touch()

    class FakeDownloader:
        config = {"general": {"preferred_backend": "all-providers"}}

    class FakeRunner:
        adapters = {object(): object()}

        def run(self, _media_paths, _language):
            return HeadlessBatchSummary(attempted=2, succeeded=1, failed=1)

    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )
    monkeypatch.setattr(
        download_subs,
        "_build_headless_all_providers_runner",
        lambda *_args, **_kwargs: FakeRunner(),
    )

    download_subs.run_legacy(
        "config.yaml",
        [str(media)],
        backend=SubtitleBackend.ALL_PROVIDERS,
        resolved_language=("ar", "cli"),
    )

    output = capsys.readouterr().out
    assert "attempted=2" in output
    assert "succeeded=1" in output
    assert "failed=1" in output


def test_no_tui_all_providers_without_adapters_reports_configuration_first(
    tmp_path,
    capsys,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "general:\n"
        "  preferred_backend: all-providers\n",
        encoding="utf-8",
    )
    media = tmp_path / "movie.mkv"
    media.touch()

    with pytest.raises(SystemExit) as exc_info:
        download_subs.run_legacy(
            str(config_path),
            [str(media)],
            backend=SubtitleBackend.ALL_PROVIDERS,
        )

    output = capsys.readouterr().out
    assert exc_info.value.code == 1
    assert "No configured provider is available" in output
    assert "No language selected" not in output


def test_main_forwards_all_providers_to_headless_dispatch(
    tmp_path,
    monkeypatch,
):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "general:\n"
        "  preferred_backend: opensubtitles\n"
        "opensubtitles:\n"
        "  languages:\n"
        "    Arabic: ar\n",
        encoding="utf-8",
    )
    media = tmp_path / "movie.mkv"
    media.touch()
    calls = {}

    monkeypatch.setattr(download_subs, "__file__", str(tmp_path / "download_subs.py"))
    monkeypatch.setattr(
        download_subs,
        "run_legacy",
        lambda *args, **kwargs: calls.update({"args": args, "kwargs": kwargs}),
    )
    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: pytest.fail(
            "main must not construct a legacy single-provider downloader"
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_subs.py",
            "--no-tui",
            "--backend",
            "all-providers",
            str(media),
        ],
    )

    download_subs.main()

    assert calls["kwargs"]["backend"] is SubtitleBackend.ALL_PROVIDERS
    assert calls["kwargs"]["resolved_language"] == ("ar", "provider")


def test_all_providers_output_next_to_media_clears_configured_output(
    tmp_path,
    monkeypatch,
):
    configured_output = tmp_path / "configured-subs"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "general:\n"
        "  preferred_backend: all-providers\n"
        f"  subtitle_output_directory: {configured_output}\n"
        "  default_language: ar\n",
        encoding="utf-8",
    )
    media = tmp_path / "library" / "movie.mkv"
    media.parent.mkdir()
    media.touch()
    calls = {}

    class FakeDownloader:
        config = {
            "general": {
                "preferred_backend": "all-providers",
                "subtitle_output_directory": str(configured_output),
                "default_language": "ar",
            }
        }

    class FakeRunner:
        def __init__(self, config, _adapters, *, emit):
            del emit
            self.config = config

        def run(self, media_paths, _language):
            configured = self.config.general.subtitle_output_directory
            calls["output_directory"] = (
                Path(configured) if configured else media_paths[0].parent
            )
            return HeadlessBatchSummary(attempted=1, succeeded=1, failed=0)

    import tui.headless
    import tui.providers.factory

    monkeypatch.setattr(download_subs, "__file__", str(tmp_path / "download_subs.py"))
    monkeypatch.setattr(
        download_subs,
        "SubtitleDownloader",
        lambda *_args, **_kwargs: FakeDownloader(),
    )
    monkeypatch.setattr(
        tui.providers.factory,
        "create_adapters",
        lambda _config: {object(): object()},
    )
    monkeypatch.setattr(
        tui.headless,
        "HeadlessAllProvidersRunner",
        FakeRunner,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "download_subs.py",
            "--no-tui",
            "--backend",
            "all-providers",
            "--output-next-to-media",
            str(media),
        ],
    )

    download_subs.main()

    assert calls["output_directory"] == media.parent
