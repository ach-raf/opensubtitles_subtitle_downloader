import os
import sys
import yaml
from enum import Enum
from typing import List, Dict, Optional, Tuple
from rich.console import Console
from rich.table import Table
from rich import print as rprint
import library.OpenSubtitles as OpenSubtitles
from library.SubDL import SubDL
import requests

console = Console()


class SubtitleBackend(Enum):
    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    AUTO = "auto"
    ASK = "ask"


class SubtitleDownloader:
    def __init__(self, config_path: str):
        self.config = self._read_config_file(config_path)
        self.opensubtitles_client = None
        self.subdl_client = None
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

    def _choose_backend(
        self, media_paths: List[str], preferred_backend: SubtitleBackend
    ) -> SubtitleBackend:
        if preferred_backend == SubtitleBackend.ASK:
            return self._ask_backend()
        elif preferred_backend == SubtitleBackend.AUTO:
            # Check API availability
            opensubtitles_available = self._check_api_availability(
                "https://api.opensubtitles.com/api/v1/login"
            )
            subdl_available = self._check_api_availability(
                "https://api.subdl.com/api/v1/subtitles"
            )

            if opensubtitles_available and subdl_available:
                # Implement more sophisticated logic here if both are available
                return SubtitleBackend.OPENSUBTITLES
            elif opensubtitles_available:
                return SubtitleBackend.OPENSUBTITLES
            elif subdl_available:
                return SubtitleBackend.SUBDL
            else:
                console.print(
                    "[bold red]Error: Both OpenSubtitles and SubDL APIs are unavailable.[/]"
                )
                return None  # Indicate failure

        else:
            return preferred_backend

    def _check_api_availability(self, url: str) -> bool:
        try:
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _ask_backend(self) -> SubtitleBackend:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Service", style="green")
        table.add_column("Description", style="yellow")

        table.add_row(
            "1", "OpenSubtitles", "Extensive database, good for movies and TV shows"
        )
        table.add_row(
            "2", "SubDL", "Alternative source, sometimes better for specific content"
        )
        table.add_row("3", "Auto", "Let the program decide based on various factors")

        self.console.print(table)

        while True:
            choice = self.console.input("[bold cyan]Select service (1-3):[/] ")
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= 3:
                    return [
                        SubtitleBackend.OPENSUBTITLES,
                        SubtitleBackend.SUBDL,
                        SubtitleBackend.AUTO,
                    ][choice_num - 1]
                else:
                    self.console.print(
                        "[bold red]Please enter a number between 1 and 3[/]"
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


def main():
    CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
    CONFIG_FILE_PATH = os.path.join(CURRENT_DIR_PATH, "config.yaml")

    try:
        downloader = SubtitleDownloader(CONFIG_FILE_PATH)
    except SystemExit:
        sys.exit(1)

    media_paths = sys.argv[1:]
    if not media_paths:
        console.print("[bold red]Error: No media paths provided. Exiting...[/]")
        sys.exit(1)

    if downloader.config.get("general", {}).get("skip_interactive_menu", False):
        backend = downloader._get_backend_from_config()
        if backend == SubtitleBackend.OPENSUBTITLES:
            language = (
                list(
                    downloader.config.get("opensubtitles", {})
                    .get("languages", {})
                    .values()
                )[0]
                if downloader.config.get("opensubtitles", {}).get("languages")
                else ""
            )
        else:
            language = (
                list(downloader.config.get("subdl", {}).get("languages", {}).values())[
                    0
                ]
                if downloader.config.get("subdl", {}).get("languages")
                else ""
            )
        if not language:
            console.print("[bold red]Error: No languages defined in config.[/]")
            sys.exit(1)
    else:
        backend, language = downloader.interactive_menu()
        if not language:
            sys.exit(1)

    downloader.download_subtitles(media_paths, language, backend)


if __name__ == "__main__":
    main()
