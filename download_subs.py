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
        with open(file_path, "r") as file:
            return yaml.safe_load(file)

    def _init_opensubtitles(self):
        if self.opensubtitles_client is None:
            self.opensubtitles_client = OpenSubtitles.OpenSubtitles(
                self.config["opensubtitles"]["username"],
                self.config["opensubtitles"]["password"],
                self.config["opensubtitles"]["api_key"],
                self.config["opensubtitles"]["user_agent"],
                skip_sync_choice=self.config["general"].get("skip_sync", False),
                auto_select=self.config["general"].get("auto_selection", False),
            )

    def _init_subdl(self):
        if self.subdl_client is None:
            self.subdl_client = SubDL(
                self.config["subdl"]["api_key"],
                sync_choice=self.config["general"].get("skip_sync", False),
                hearing_impaired=False,
                auto_select=self.config["general"].get("auto_selection", False),
            )

    def _choose_backend(
        self, media_paths: List[str], preferred_backend: SubtitleBackend
    ) -> SubtitleBackend:
        if preferred_backend == SubtitleBackend.ASK:
            return self._ask_backend()
        elif preferred_backend != SubtitleBackend.AUTO:
            return preferred_backend

        # Add logic here to choose the best backend based on various factors
        # For example:
        # 1. Check previous success rates
        return (
            SubtitleBackend.OPENSUBTITLES
            if len(media_paths) % 2 == 0
            else SubtitleBackend.SUBDL
        )

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
                if choice_num == 1:
                    return SubtitleBackend.OPENSUBTITLES
                elif choice_num == 2:
                    return SubtitleBackend.SUBDL
                elif choice_num == 3:
                    return SubtitleBackend.AUTO
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

        self.console.print(
            f"[bold green]Downloading subtitles using {chosen_backend.value}..."
        )

        if chosen_backend == SubtitleBackend.OPENSUBTITLES:
            self._init_opensubtitles()
            self.console.print(
                f"[bold blue]Using OpenSubtitles backend for {len(media_paths)} files[/]"
            )
            self.opensubtitles_client.download_subtitles(media_paths, language)
        else:
            self._init_subdl()
            self.console.print(
                f"[bold blue]Using SubDL backend for {len(media_paths)} files[/]"
            )
            self.subdl_client.process_media_list(
                media_paths,
                language,
            )

    def _show_language_menu(self, languages: Dict[str, str]) -> str:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Language", style="green")
        table.add_column("Code", style="yellow")

        # Updated to handle languages where the key is the full name and value is the code
        for i, (lang, code) in enumerate(languages.items(), 1):
            table.add_row(str(i), lang, code)

        self.console.print(table)

        while True:
            choice = self.console.input("[bold cyan]Select language number:[/] ")
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(languages):
                    # Return the language code (value) instead of the full name (key)
                    return list(languages.values())[choice_num - 1]
                else:
                    self.console.print("[bold red]Please enter a valid number[/]")
            except ValueError:
                self.console.print("[bold red]Please enter a valid number[/]")

    def interactive_menu(self) -> Tuple[SubtitleBackend, str]:
        backend = self._get_backend_from_config()

        if backend == SubtitleBackend.OPENSUBTITLES:
            languages = self.config["opensubtitles"]["languages"]
        elif backend == SubtitleBackend.SUBDL:
            languages = self.config["subdl"]["languages"]
        else:  # For AUTO or ASK, use OpenSubtitles languages as default
            languages = self.config["opensubtitles"]["languages"]

        language = self._show_language_menu(languages)
        return backend, language

    def _get_backend_from_config(self) -> SubtitleBackend:
        backend_str = self.config["general"].get("preferred_backend", "ask").lower()
        try:
            return SubtitleBackend(backend_str)
        except ValueError:
            self.console.print(
                f"[bold red]Invalid backend in config: {backend_str}. Using 'ask' instead.[/]"
            )
            return SubtitleBackend.ASK


def main():
    CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
    CONFIG_FILE_PATH = os.path.join(CURRENT_DIR_PATH, "config.yaml")

    try:
        downloader = SubtitleDownloader(CONFIG_FILE_PATH)
    except FileNotFoundError:
        console = Console()
        console.print(
            "[bold red]Config file not found. Please ensure config.yaml exists.[/]"
        )
        sys.exit(1)
    except yaml.YAMLError as e:
        console = Console()
        console.print(f"[bold red]Error reading config file: {e}[/]")
        sys.exit(1)

    media_paths = sys.argv[1:]
    if not media_paths:
        console = Console()
        console.print("[bold red]No media paths provided. Exiting...[/]")
        sys.exit(1)

    if downloader.config["general"].get("skip_interactive_menu", False):
        backend = downloader._get_backend_from_config()
        if backend == SubtitleBackend.OPENSUBTITLES:
            # get the first language code (value) instead of key
            language = list(downloader.config["opensubtitles"]["languages"].values())[0]
        else:
            language = list(downloader.config["subdl"]["languages"].values())[0]
    else:
        backend, language = downloader.interactive_menu()

    downloader.download_subtitles(media_paths, language, backend)


if __name__ == "__main__":
    # Usage: python download_subs.py <path_to_media_file>
    # Usage: python download_subs.py <path_to_media_file> <path_to_media_file> # multiple files
    # Usage: python download_subs.py <path_to_media_folder>
    # Usage: python download_subs.py <path_to_media_folder> <path_to_media_folder> # multiple folders
    main()
