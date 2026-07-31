import argparse
import os
import sys
from enum import Enum
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from tui.media import MEDIA_EXTENSIONS, expand_media_paths

console = Console()


class SubtitleBackend(Enum):
    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    SUBSOURCE = "subsource"
    ALL_PROVIDERS = "all-providers"
    AUTO = "auto"
    ASK = "ask"


def _resolve_backend(
    cli_backend: str | None,
    config: dict,
) -> SubtitleBackend:
    cli_value = str(cli_backend or "").strip().lower()
    if cli_value:
        return SubtitleBackend(cli_value)

    general = config.get("general", {}) or {}
    configured_value = str(
        general.get("preferred_backend", SubtitleBackend.ASK.value)
    ).strip().lower()
    try:
        return SubtitleBackend(configured_value)
    except ValueError:
        console.print(
            "[bold red]Warning: Invalid backend in config: "
            f"{configured_value}. Using 'ask' instead.[/]"
        )
        return SubtitleBackend.ASK


def _resolve_language(
    cli_language: str | None,
    config: dict,
    backend: SubtitleBackend,
) -> tuple[str, str]:
    cli_value = str(cli_language or "").strip().lower()
    if cli_value:
        return cli_value, "cli"

    config_value = str(
        (config.get("general", {}) or {}).get("default_language", "") or ""
    ).strip().lower()
    if config_value:
        return config_value, "config"

    if backend == SubtitleBackend.ALL_PROVIDERS:
        provider_sections = ("opensubtitles", "subdl", "subsource")
    elif backend == SubtitleBackend.SUBDL:
        provider_sections = ("subdl",)
    elif backend == SubtitleBackend.SUBSOURCE:
        provider_sections = ("subsource",)
    else:
        provider_sections = ("opensubtitles",)
    for provider_section in provider_sections:
        languages = (
            (config.get(provider_section, {}) or {}).get("languages", {}) or {}
        )
        provider_value = str(
            next(iter(languages.values()), "") or ""
        ).strip().lower()
        if provider_value:
            return provider_value, "provider"
    return "", "missing"


class SubtitleDownloader:
    def __init__(
        self,
        config_path: str,
        *,
        output_directory: str | Path | None = None,
    ):
        self.config = self._read_config_file(config_path)
        self.output_directory = (
            Path(output_directory) if output_directory is not None else None
        )
        self.opensubtitles_client = None
        self.subdl_client = None
        self.subsource_client = None
        self.console = Console()

    def _read_config_file(self, file_path: str) -> dict:
        try:
            with open(file_path) as file:
                return yaml.safe_load(file)
        except FileNotFoundError:
            console.print(f"[bold red]Error: Config file not found at {file_path}[/]")
            sys.exit(1)
        except yaml.YAMLError as e:
            console.print(f"[bold red]Error: Invalid YAML in config file: {e}[/]")
            sys.exit(1)

    def _init_opensubtitles(self):
        if self.opensubtitles_client is None:
            try:
                from library.OpenSubtitles import OpenSubtitles

                self.opensubtitles_client = OpenSubtitles(
                    self.config["opensubtitles"]["username"],
                    self.config["opensubtitles"]["password"],
                    self.config["opensubtitles"]["api_key"],
                    self.config["opensubtitles"]["user_agent"],
                    sync_audio_to_subs=self.config["general"].get(
                        "sync_audio_to_subs", False
                    ),
                    auto_select=self.config["general"].get("auto_selection", False),
                    output_directory=self.output_directory,
                )
            except KeyError as e:
                console.print(
                    f"[bold red]Error: Missing key in opensubtitles config: {e}[/]"
                )
                sys.exit(1)

    def _init_subdl(self):
        if self.subdl_client is None:
            try:
                from library.SubDL import SubDL

                self.subdl_client = SubDL(
                    self.config["subdl"]["api_key"],
                    sync_audio_to_subs=self.config["general"].get(
                        "sync_audio_to_subs", False
                    ),
                    hearing_impaired=False,
                    auto_select=self.config["general"].get("auto_selection", False),
                    output_directory=self.output_directory,
                )
            except KeyError as e:
                console.print(f"[bold red]Error: Missing key in subdl config: {e}[/]")
                sys.exit(1)

    def _init_subsource(self):
        if self.subsource_client is None:
            try:
                from library.SubSource import SubSource

                self.subsource_client = SubSource(
                    self.config["subsource"]["api_key"],
                    sync_audio_to_subs=self.config["general"].get(
                        "sync_audio_to_subs", False
                    ),
                    hearing_impaired=False,
                    auto_select=self.config["general"].get("auto_selection", False),
                    output_directory=self.output_directory,
                )
            except KeyError as e:
                console.print(
                    f"[bold red]Error: Missing key in subsource config: {e}[/]"
                )
                sys.exit(1)

    def _choose_backend(
        self, media_paths: list[str], preferred_backend: SubtitleBackend
    ) -> SubtitleBackend:
        if preferred_backend == SubtitleBackend.ASK:
            return self._ask_backend()
        elif preferred_backend == SubtitleBackend.AUTO:
            # Check APIavailability
            opensubtitles_available = self._check_api_availability(
                "https://api.opensubtitles.com/api/v1/login"
            )
            subdl_available = self._check_api_availability(
                "https://api.subdl.com/api/v2/me",
                headers={"Authorization": f"Bearer {self.config['subdl']['api_key']}"},
            )
            subsource_available = self._check_api_availability(
                "https://api.subsource.net/api/v1/movies/search?searchType=text&q=test",
                headers={"X-API-Key": self.config["subsource"]["api_key"]},
            )

            # Prefer an explicit backend, then OpenSubtitles, SubDL, SubSource.
            if subsource_available:
                return SubtitleBackend.SUBSOURCE
            elif opensubtitles_available:
                return SubtitleBackend.OPENSUBTITLES
            elif subdl_available:
                return SubtitleBackend.SUBDL
            else:
                console.print("[bold red]Error: All subtitle APIs are unavailable.[/]")
                return None  # Indicate failure

        else:
            return preferred_backend

    def _check_api_availability(self, url, headers=None) -> bool:
        import requests

        try:
            response = requests.get(url, timeout=5, headers=headers)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _ask_backend(self) -> SubtitleBackend:
        # Interactive list of concrete (non-meta) backends + Auto.
        options = [
            (
                SubtitleBackend.OPENSUBTITLES,
                "OpenSubtitles",
                "Extensive database, good for movies and TV shows",
            ),
            (
                SubtitleBackend.SUBDL,
                "SubDL",
                "Alternative source, sometimes better for specific content",
            ),
            (
                SubtitleBackend.SUBSOURCE,
                "SubSource",
                "Community source with per-season TV organization",
            ),
            (
                SubtitleBackend.AUTO,
                "Auto",
                "Let the program decide based on availability",
            ),
        ]

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Service", style="green")
        table.add_column("Description", style="yellow")

        for i, (_backend, name, desc) in enumerate(options, start=1):
            table.add_row(str(i), name, desc)

        self.console.print(table)

        while True:
            choice = self.console.input(
                f"[bold cyan]Select service (1-{len(options)}):[/] "
            )
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(options):
                    return options[choice_num - 1][0]
                else:
                    self.console.print(
                        f"[bold red]Please enter a number between 1 and "
                        f"{len(options)}[/]"
                    )
            except ValueError:
                self.console.print("[bold red]Please enter a valid number[/]")

    def download_subtitles(
        self, media_paths: list[str], language: str, backend: SubtitleBackend
    ) -> None:
        chosen_backend = self._choose_backend(media_paths, backend)
        if chosen_backend is None:
            return

        self.console.print(
            f"[bold green]Downloading subtitles using {chosen_backend.value}..."
        )

        if chosen_backend == SubtitleBackend.OPENSUBTITLES:
            self._init_opensubtitles()
            self.console.print(
                "[bold blue]Using OpenSubtitles backend for "
                f"{len(media_paths)} files[/]"
            )
            if self.opensubtitles_client:
                self._process_media_files(
                    self.opensubtitles_client,
                    media_paths,
                    language,
                )
            else:
                console.print(
                    "[bold red]OpenSubtitles client initialization failed.[/]"
                )
        elif chosen_backend == SubtitleBackend.SUBDL:
            self._init_subdl()
            self.console.print(
                f"[bold blue]Using SubDL backend for {len(media_paths)} files[/]"
            )
            if self.subdl_client:
                self._process_media_files(self.subdl_client, media_paths, language)
            else:
                console.print("[bold red]SubDL client initialization failed.[/]")
        elif chosen_backend == SubtitleBackend.SUBSOURCE:
            self._init_subsource()
            self.console.print(
                f"[bold blue]Using SubSource backend for {len(media_paths)} files[/]"
            )
            if self.subsource_client:
                self._process_media_files(
                    self.subsource_client,
                    media_paths,
                    language,
                )
            else:
                console.print("[bold red]SubSource client initialization failed.[/]")
        else:
            console.print("[bold red]Invalid backend selected.[/]")

    @staticmethod
    def _process_media_files(client, media_paths: list[str], language: str) -> None:
        for media_path in media_paths:
            client.process_media_file(media_path, language)

    def _show_language_menu(self, languages: dict[str, str]) -> str:
        if not languages:
            console.print("[bold red]Error: No languages defined in config.[/]")
            return ""

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Language", style="green")
        table.add_column("Code", style="yellow")

        for i, (lang, code) in enumerate(languages.items(), 1):
            table.add_row(str(i), lang, code)

        self.console.print(table)

        while True:
            choice = self.console.input("[bold cyan]Select language number:[/] ")
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(languages):
                    return list(languages.values())[choice_num - 1]
                else:
                    self.console.print("[bold red]Please enter a valid number[/]")
            except ValueError:
                self.console.print("[bold red]Please enter a valid number[/]")

    def interactive_menu(self) -> tuple[SubtitleBackend, str]:
        backend = self._get_backend_from_config()

        if backend == SubtitleBackend.OPENSUBTITLES:
            languages = self.config.get("opensubtitles", {}).get("languages", {})
        elif backend == SubtitleBackend.SUBDL:
            languages = self.config.get("subdl", {}).get("languages", {})
        elif backend == SubtitleBackend.SUBSOURCE:
            languages = self.config.get("subsource", {}).get("languages", {})
        else:
            languages = self.config.get("opensubtitles", {}).get("languages", {})

        language = self._show_language_menu(languages)
        return backend, language

    def _get_backend_from_config(self) -> SubtitleBackend:
        backend_str = (
            self.config.get("general", {}).get("preferred_backend", "ask").lower()
        )
        try:
            return SubtitleBackend(backend_str)
        except ValueError:
            console.print(
                "[bold red]Warning: Invalid backend in config: "
                f"{backend_str}. Using 'ask' instead.[/]"
            )
            return SubtitleBackend.ASK


def _build_headless_all_providers_runner(
    config_path: str,
    *,
    output_directory: str | Path | None = None,
    output_directory_overridden: bool = False,
):
    """Build the typed all-provider runner without loading it on TUI startup."""
    from tui.config import ConfigRepository
    from tui.headless import HeadlessAllProvidersRunner
    from tui.providers.factory import create_adapters

    config = ConfigRepository(config_path).load()
    if output_directory_overridden or output_directory is not None:
        config.general.subtitle_output_directory = (
            str(output_directory) if output_directory is not None else ""
        )
    adapters = create_adapters(config)
    return HeadlessAllProvidersRunner(
        config,
        adapters,
        emit=console.print,
    )


def run_legacy(
    config_path: str,
    media_paths: list[str],
    *,
    backend: SubtitleBackend | None = None,
    recursive: bool = False,
    output_directory: str | Path | None = None,
    output_directory_overridden: bool = False,
    resolved_language: tuple[str, str] | None = None,
) -> None:
    """Run the non-TUI subtitle download flow.

    Read config, resolve startup options, and download without opening menus.
    """
    try:
        downloader = SubtitleDownloader(
            config_path,
            output_directory=output_directory,
        )
    except SystemExit:
        sys.exit(1)

    backend = backend or downloader._get_backend_from_config()
    headless_runner = None
    if backend is SubtitleBackend.ALL_PROVIDERS:
        headless_runner = _build_headless_all_providers_runner(
            config_path,
            output_directory=output_directory,
            output_directory_overridden=output_directory_overridden,
        )
    language_resolution = (
        resolved_language
        if resolved_language is not None
        else _resolve_language(None, downloader.config, backend)
    )
    language, _source = language_resolution
    if not language:
        if headless_runner is not None and not headless_runner.adapters:
            summary = headless_runner.run([], language)
            console.print(
                "Batch summary: "
                f"attempted={summary.attempted}, "
                f"succeeded={summary.succeeded}, "
                f"failed={summary.failed}"
            )
            raise SystemExit(summary.exit_code)
        console.print(
            "[bold red]Error: No language selected. Use --lang or set "
            "general.default_language.[/]"
        )
        sys.exit(1)

    if not media_paths:
        console.print("[bold red]Error: No media paths provided. Exiting...[/]")
        sys.exit(1)

    expansion = expand_media_paths(
        media_paths,
        MEDIA_EXTENSIONS,
        recursive=recursive,
    )
    media_paths = [str(path) for path in expansion.paths]
    if not media_paths:
        console.print("[bold red]Error: No supported media files found. Exiting...[/]")
        sys.exit(1)
    if output_directory is not None:
        seen_stems: set[str] = set()
        duplicate_stems: set[str] = set()
        for media_path in media_paths:
            stem = Path(media_path).stem.casefold()
            if stem in seen_stems:
                duplicate_stems.add(Path(media_path).stem)
            seen_stems.add(stem)
        if duplicate_stems:
            names = ", ".join(sorted(duplicate_stems, key=str.casefold))
            console.print(
                "[bold red]Error: Flat subtitle output would overwrite files for "
                f"duplicate media names: {names}[/]"
            )
            sys.exit(1)

    if headless_runner is not None:
        summary = headless_runner.run(
            [Path(path) for path in media_paths],
            language,
        )
        console.print(
            "Batch summary: "
            f"attempted={summary.attempted}, "
            f"succeeded={summary.succeeded}, "
            f"failed={summary.failed}"
        )
        if summary.exit_code:
            raise SystemExit(summary.exit_code)
        return

    downloader.download_subtitles(media_paths, language, backend)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Parse media paths and per-run command-line overrides.

    Positional args are media paths (preserving the pre-TUI call shape).
    """
    parser = argparse.ArgumentParser(
        prog="download_subs.py",
        description="Download subtitles from OpenSubtitles / SubDL / SubSource.",
        # Preserve the old behaviour: unknown positional args are media paths,
        # and we never error on extra args.
        add_help=True,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="One or more video files or folders to fetch subtitles for.",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Force the Textual TUI even if general.no_tui is set in config.",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run the noninteractive/headless CLI without the Textual TUI.",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Use this ISO language code in TUI, batch, and no-TUI modes.",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=[backend.value for backend in SubtitleBackend],
        help="Use this subtitle backend for this run.",
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Recursively discover video files in folders.",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output-dir",
        default=None,
        help="Save subtitles in this directory for this run.",
    )
    output_group.add_argument(
        "--output-next-to-media",
        action="store_true",
        help="Ignore a configured output directory for this run.",
    )
    return parser


def _resolve_path_options(
    args: argparse.Namespace,
    config: dict,
    config_path: str | Path,
) -> tuple[bool, Path | None]:
    general = config.get("general", {}) or {}
    recursive = (
        bool(general.get("recursive_search", False))
        if args.recursive is None
        else bool(args.recursive)
    )

    if args.output_next_to_media:
        output_directory = None
    elif args.output_dir is not None:
        output_directory = Path(args.output_dir).resolve()
    else:
        configured = str(general.get("subtitle_output_directory", "") or "").strip()
        if not configured:
            output_directory = None
        else:
            output_directory = Path(configured)
            if not output_directory.is_absolute():
                output_directory = Path(config_path).resolve().parent / output_directory
            output_directory = output_directory.resolve()
    return recursive, output_directory


def main() -> None:
    CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
    CONFIG_FILE_PATH = os.path.join(CURRENT_DIR_PATH, "config.yaml")

    parser = _build_arg_parser()
    args = parser.parse_args()
    media_paths: list[str] = list(args.paths)

    # Read config once so we can honor general.no_tui and per-run overrides.
    config: dict = {}
    try:
        with open(CONFIG_FILE_PATH, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        # Config missing — fall back to the headless CLI which prints its own
        # error (preserving the pre-TUI behaviour).
        run_legacy(CONFIG_FILE_PATH, media_paths)
        return
    except yaml.YAMLError as exc:
        console.print(f"[bold red]Error: Invalid YAML in config file: {exc}[/]")
        sys.exit(1)

    recursive_search, output_directory = _resolve_path_options(
        args,
        config,
        CONFIG_FILE_PATH,
    )
    backend = _resolve_backend(args.backend, config)
    language_resolution = _resolve_language(args.lang, config, backend)

    # Phase 6: the TUI is now the DEFAULT. Escape hatches:
    #   --no-tui flag, or general.no_tui: true in config.yaml.
    #   --tui overrides general.no_tui (explicit user intent wins).
    #   The headless CLI is selected by either no-TUI setting.
    config_no_tui = bool(config.get("general", {}).get("no_tui", False))
    if args.no_tui:
        use_tui = False
    elif args.tui:
        use_tui = True
    else:
        use_tui = not config_no_tui

    if not use_tui:
        run_legacy(
            CONFIG_FILE_PATH,
            media_paths,
            backend=backend,
            recursive=recursive_search,
            output_directory=output_directory,
            output_directory_overridden=(
                args.output_next_to_media or args.output_dir is not None
            ),
            resolved_language=language_resolution,
        )
        return

    # --- TUI path ---
    # Lazy import so the legacy path (and --help) never requires textual.
    from tui.app import run_tui

    if not media_paths:
        console.print("[bold red]Error: No media paths provided. Exiting...[/]")
        sys.exit(1)

    overrides = {
        "lang": language_resolution[0] if language_resolution[1] == "cli" else None,
        "backend": args.backend,
    }
    run_tui(
        config=config,
        media_paths=media_paths,
        overrides=overrides,
        config_path=CONFIG_FILE_PATH,
        recursive_search=recursive_search,
        output_directory=output_directory,
        language_resolution=language_resolution,
    )


if __name__ == "__main__":
    main()
