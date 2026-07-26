import os
import sys
import argparse
import yaml
from enum import Enum
from typing import List, Dict, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich import print as rprint
import library.OpenSubtitles as OpenSubtitles
from library.SubDL import SubDL
from library.SubSource import SubSource
import requests

console = Console()


class SubtitleBackend(Enum):
    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    SUBSOURCE = "subsource"
    AUTO = "auto"
    ASK = "ask"


class SubtitleDownloader:
    def __init__(self, config_path: str):
        self.config = self._read_config_file(config_path)
        self.opensubtitles_client = None
        self.subdl_client = None
        self.subsource_client = None
        self.console = Console()

    def _read_config_file(self, file_path: str) -> Dict:
        try:
            with open(file_path, "r") as file:
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
                self.opensubtitles_client = OpenSubtitles.OpenSubtitles(
                    self.config["opensubtitles"]["username"],
                    self.config["opensubtitles"]["password"],
                    self.config["opensubtitles"]["api_key"],
                    self.config["opensubtitles"]["user_agent"],
                    sync_audio_to_subs=self.config["general"].get(
                        "sync_audio_to_subs", False
                    ),
                    auto_select=self.config["general"].get("auto_selection", False),
                )
            except KeyError as e:
                console.print(
                    f"[bold red]Error: Missing key in opensubtitles config: {e}[/]"
                )
                sys.exit(1)

    def _init_subdl(self):
        if self.subdl_client is None:
            try:
                self.subdl_client = SubDL(
                    self.config["subdl"]["api_key"],
                    sync_audio_to_subs=self.config["general"].get(
                        "sync_audio_to_subs", False
                    ),
                    hearing_impaired=False,
                    auto_select=self.config["general"].get("auto_selection", False),
                )
            except KeyError as e:
                console.print(f"[bold red]Error: Missing key in subdl config: {e}[/]")
                sys.exit(1)

    def _init_subsource(self):
        if self.subsource_client is None:
            try:
                self.subsource_client = SubSource(
                    self.config["subsource"]["api_key"],
                    sync_audio_to_subs=self.config["general"].get(
                        "sync_audio_to_subs", False
                    ),
                    hearing_impaired=False,
                    auto_select=self.config["general"].get("auto_selection", False),
                )
            except KeyError as e:
                console.print(
                    f"[bold red]Error: Missing key in subsource config: {e}[/]"
                )
                sys.exit(1)

    def _choose_backend(
        self, media_paths: List[str], preferred_backend: SubtitleBackend
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
                console.print(
                    "[bold red]Error: All subtitle APIs are unavailable.[/]"
                )
                return None  # Indicate failure

        else:
            return preferred_backend

    def _check_api_availability(self, url, headers=None) -> bool:
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
            (SubtitleBackend.AUTO, "Auto", "Let the program decide based on availability"),
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
        self, media_paths: List[str], language: str, backend: SubtitleBackend
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
                f"[bold blue]Using OpenSubtitles backend for {len(media_paths)} files[/]"
            )
            if self.opensubtitles_client:
                self.opensubtitles_client.process_media_list(media_paths, language)
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
                self.subdl_client.process_media_list(media_paths, language)
            else:
                console.print("[bold red]SubDL client initialization failed.[/]")
        elif chosen_backend == SubtitleBackend.SUBSOURCE:
            self._init_subsource()
            self.console.print(
                f"[bold blue]Using SubSource backend for {len(media_paths)} files[/]"
            )
            if self.subsource_client:
                self.subsource_client.process_media_list(media_paths, language)
            else:
                console.print(
                    "[bold red]SubSource client initialization failed.[/]"
                )
        else:
            console.print("[bold red]Invalid backend selected.[/]")

    def _show_language_menu(self, languages: Dict[str, str]) -> str:
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

    def interactive_menu(self) -> Tuple[SubtitleBackend, str]:
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
                f"[bold red]Warning: Invalid backend in config: {backend_str}. Using 'ask' instead.[/]"
            )
            return SubtitleBackend.ASK


def run_legacy(config_path: str, media_paths: List[str]) -> None:
    """The original numbered-prompt CLI flow, preserved behind --no-tui.

    This is the exact pre-TUI behaviour: read config, build a SubtitleDownloader,
    show the numbered menus (or honor skip_interactive_menu), and download.
    """
    try:
        downloader = SubtitleDownloader(config_path)
    except SystemExit:
        sys.exit(1)

    if not media_paths:
        console.print("[bold red]Error: No media paths provided. Exiting...[/]")
        sys.exit(1)

    if downloader.config.get("general", {}).get("skip_interactive_menu", False):
        backend = downloader._get_backend_from_config()
        # Pick the language block matching the configured backend.
        if backend == SubtitleBackend.SUBDL:
            source_section = "subdl"
        elif backend == SubtitleBackend.SUBSOURCE:
            source_section = "subsource"
        else:
            # OPENSUBTITLES, AUTO, ASK all fall back to the opensubtitles languages.
            source_section = "opensubtitles"
        languages_map = (
            downloader.config.get(source_section, {}).get("languages", {}) or {}
        )
        language = list(languages_map.values())[0] if languages_map else ""
        if not language:
            console.print("[bold red]Error: No languages defined in config.[/]")
            sys.exit(1)
    else:
        backend, language = downloader.interactive_menu()
        if not language:
            sys.exit(1)

    downloader.download_subtitles(media_paths, language, backend)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Parse argv into media paths + the initial overrides that seed the TUI.

    Positional args are media paths (preserving the pre-TUI call shape).
    Flags only take effect when the TUI runs; the legacy path is unchanged.
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
        help="Launch the Textual TUI (opt-in through Phase 5; default in Phase 6).",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Force the legacy numbered-prompt CLI even if TUI is the default.",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Seed the TUI with an ISO language code (e.g. 'en', 'ar').",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=["opensubtitles", "subdl", "subsource", "auto", "ask"],
        help="Seed the TUI with a subtitle backend.",
    )
    return parser


def main() -> None:
    CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
    CONFIG_FILE_PATH = os.path.join(CURRENT_DIR_PATH, "config.yaml")

    parser = _build_arg_parser()
    args = parser.parse_args()
    media_paths: List[str] = list(args.paths)

    # TUI is opt-in for Phases 0-5; --no-tui and the absence of --tui both run
    # the legacy CLI. Phase 6 flips this so TUI is the default.
    use_tui = args.tui and not args.no_tui

    if not use_tui:
        run_legacy(CONFIG_FILE_PATH, media_paths)
        return

    # --- TUI path ---
    # Lazy import so the legacy path (and --help) never requires textual.
    from tui.app import run_tui

    config: Dict = {}
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        console.print(
            f"[bold red]Error: Config file not found at {CONFIG_FILE_PATH}[/]"
        )
        sys.exit(1)
    except yaml.YAMLError as exc:
        console.print(f"[bold red]Error: Invalid YAML in config file: {exc}[/]")
        sys.exit(1)

    if not media_paths:
        console.print("[bold red]Error: No media paths provided. Exiting...[/]")
        sys.exit(1)

    overrides = {"lang": args.lang, "backend": args.backend}
    run_tui(
        config=config,
        media_paths=media_paths,
        overrides=overrides,
        config_path=CONFIG_FILE_PATH,
    )


if __name__ == "__main__":
    main()
