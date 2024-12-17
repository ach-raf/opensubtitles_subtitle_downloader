# OpenSubtitles.py is a class that handles subtitle search and download from opensubtitles API.
import requests
import json

from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from library.subtitle_utils import SubtitleUtils
import re


class OpenSubtitles:

    def __init__(
        self,
        username,
        password,
        api_key,
        user_agent,
        sync_audio_to_subs=False,
        hearing_impaired=False,
        auto_select=True,
    ):
        self.username = username
        self.password = password
        self.api_key = api_key
        self.user_agent = user_agent
        self.sync_audio_to_subs = sync_audio_to_subs
        self.hearing_impaired = hearing_impaired
        self.auto_select = auto_select
        self.console = Console()
        self.subtitle_utils = SubtitleUtils()
        self.token = self.login()

    def clean_filename(self, filename):
        # Remove multiple consecutive dashes and spaces
        cleaned = re.sub(r"-+\s*-+", " ", filename)
        # Remove multiple dots
        cleaned = re.sub(r"\.+", " ", cleaned)
        # Remove quality tags and other common patterns in brackets
        cleaned = re.sub(r"\[(.*?)\]", "", cleaned)
        # Remove multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def login(self):
        token = self.subtitle_utils.read_token()
        if token:
            return token

        url = "https://api.opensubtitles.com/api/v1/login"

        payload = {"username": self.username, "password": self.password}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Api-Key": self.api_key,
        }
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            token = response.json()["token"]
            self.subtitle_utils.save_token(token)
            return token
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during OpenSubtitles login: {e}[/]")
            return None
        except (KeyError, json.decoder.JSONDecodeError) as e:
            self.console.print(
                f"[bold red]Error parsing OpenSubtitles login response: {e}[/]"
            )
            return None
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error during login: {e}[/]")
            return None

    def search(
        self,
        media_hash="",
        imdb_id="",
        media_name="",
        languages="en,ar",
    ):
        url = "https://api.opensubtitles.com/api/v1/subtitles"
        hearing_impaired = "include" if self.hearing_impaired else "exclude"
        params = {
            "languages": languages,
            "hearing_impaired": hearing_impaired,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Api-Key": self.api_key,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
        }
        if imdb_id:
            params["imdb_id"] = imdb_id

        if media_hash:
            params["moviehash"] = media_hash

        if media_name:
            params["query"] = media_name

        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            results = response.json()["data"]
            return results
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during OpenSubtitles search: {e}[/]")
            return None
        except (KeyError, json.decoder.JSONDecodeError) as e:
            self.console.print(
                f"[bold red]Error parsing OpenSubtitles search response: {e}[/]"
            )
            return None
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error during search: {e}[/]")
            return None

    def get_download_link(self, selected_subtitles):
        url = "https://api.opensubtitles.com/api/v1/download"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Api-Key": self.api_key,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
        }
        payload = {}
        try:
            payload["file_id"] = int(
                selected_subtitles["attributes"]["files"][0]["file_id"]
            )
            response = requests.post(
                url, headers=headers, data=json.dumps(payload), timeout=10
            )
            response.raise_for_status()
            return response.json()["link"]
        except requests.exceptions.RequestException as e:
            self.console.print(
                f"[bold red]Error during OpenSubtitles download link retrieval: {e}[/]"
            )
            return None
        except (KeyError, json.decoder.JSONDecodeError, TypeError, IndexError) as e:
            self.console.print(
                f"[bold red]Error parsing OpenSubtitles download link response: {e}[/]"
            )
            return None
        except Exception as e:
            self.console.print(
                f"[bold red]Unexpected error during download link retrieval: {e}[/]"
            )
            return None

    def save_subtitle(self, url, path):
        """Download and save subtitle file from url to path"""
        try:
            response = requests.get(url, stream=True, timeout=10)
            response.raise_for_status()
            with open(path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error downloading subtitle: {e}[/]")
            return False
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error saving subtitle: {e}[/]")
            return False

    def process_media_file(self, media_path, language_choice, media_name=""):
        try:
            path = Path(media_path)
            hash = self.subtitle_utils.hashFile(media_path)
            if not media_name:
                media_name = path.stem

            # Clean the media name for better search results
            clean_media_name = self.clean_filename(media_name)
            rprint(
                f"[cyan]Searching for subtitles for[/cyan] [yellow]{media_name}[/yellow]"
            )
            subtitle_path = Path(path.parent, f"{path.stem}.{language_choice}.srt")
            results = self.search(
                media_hash=hash, media_name=clean_media_name, languages=language_choice
            )
            if not results:
                rprint(f"[red]No subtitles found for {clean_media_name}[/red]")
            else:
                rprint(f"[green]Found {len(results)} results[/green]")

            # parse series name and search for subtitles by series name alone
            series_name = re.search(
                r"(.+?)(?:\s-\sS\d{2}E\d{2}|\s-\s\d{4})", clean_media_name
            )

            if series_name:
                series_name = series_name.group(1).strip()
                rprint(
                    f"[cyan]Searching for subtitles for series[/cyan] [yellow]{series_name}[/yellow]"
                )
                temp_results = self.search(
                    media_hash=hash, media_name=series_name, languages=language_choice
                )
                if temp_results:
                    results.extend(temp_results)
                    rprint(
                        f"[blue]Adding more results by searching for[/blue] [yellow]{series_name}[/yellow], [green]found {len(temp_results)} results[/green]"
                    )

                # Check if series name contains Mr. or Ms. and search without them
                if re.search(r"(?i)mr\.|ms\.", series_name):
                    clean_series_name = re.sub(
                        r"(?i)(?:mr\.|ms\.)\s*", "", series_name
                    ).strip()
                    rprint(
                        f"[cyan]Searching without title prefix for[/cyan] [yellow]{clean_series_name}[/yellow]"
                    )
                    temp_results = self.search(
                        media_hash=hash,
                        media_name=clean_series_name,
                        languages=language_choice,
                    )
                    if temp_results:
                        results.extend(temp_results)
                        rprint(
                            f"[blue]Adding more results by searching for[/blue] [yellow]{clean_series_name}[/yellow], [green]found {len(temp_results)} results[/green]"
                        )

            # Add more results using alternate names
            new_search_terms = self.subtitle_utils.get_alternate_names(clean_media_name)
            if new_search_terms:
                for term in new_search_terms:
                    temp_results = self.search(
                        media_hash=hash,
                        media_name=term,
                        languages=language_choice,
                    )
                    if temp_results:
                        results.extend(temp_results)
                        rprint(
                            f"[blue]Adding more results by searching for[/blue] [yellow]{term}[/yellow], [green]found {len(temp_results)} results[/green]"
                        )

            if not results:
                rprint(f"[red]No subtitles found for {clean_media_name}[/red]")
                return False

            # remove duplicates
            results = list({v["id"]: v for v in results}.values())

            sorted_results = self.subtitle_utils.sort_list_of_dicts_by_key(
                results, "download_count"
            )

            if self.auto_select:
                selected_sub = self.subtitle_utils.auto_select_subtitle(
                    clean_media_name, sorted_results
                )
            else:
                selected_sub = self.subtitle_utils.manual_select_subtitle(
                    clean_media_name, sorted_results
                )

            if selected_sub is None:
                rprint("[yellow]Subtitle download cancelled.[/yellow]")
                return False

            download_link = self.get_download_link(selected_sub)
            if download_link is None:
                return False

            rprint(
                f"[green]>> Downloading {language_choice} subtitles for {media_path}[/green]"
            )
            self.print_subtitle_info(selected_sub)
            if not self.save_subtitle(download_link, subtitle_path):
                return False
            self.subtitle_utils.clean_subtitles(subtitle_path)
            if self.sync_audio_to_subs == "ask":
                should_sync = self.subtitle_utils.ask_sync_subtitles()
                if should_sync:
                    self.subtitle_utils.sync_subtitles(media_path, subtitle_path)
            elif self.sync_audio_to_subs:
                self.subtitle_utils.sync_subtitles(media_path, subtitle_path)
            return True
        except Exception as e:
            self.console.print(
                f"[bold red]Unexpected error processing media file: {e}[/]"
            )
            return False

    def process_media_list(self, media_path_list, language_choice):
        for media_path in media_path_list:
            try:
                path = Path(media_path)
                if path.is_dir():
                    for file in path.iterdir():
                        if self.subtitle_utils.check_if_media_file(file):
                            result = self.process_media_file(file, language_choice)
                            if not result:
                                self.console.print(
                                    f"[bold yellow]Warning: Could not find subtitles for {file}[/]"
                                )
                elif self.subtitle_utils.check_if_media_file(path):
                    result = self.process_media_file(path, language_choice)
                    if not result:
                        self.console.print(
                            f"[bold yellow]Warning: Could not find subtitles for {path}[/]"
                        )
            except Exception as e:
                self.console.print(
                    f"[bold red]Unexpected error processing media list item {media_path}: {e}[/]"
                )

    def print_subtitle_info(self, sub):
        try:
            attrs = sub["attributes"]
            movie_name = attrs["feature_details"]["movie_name"]

            info_table = Table(title="Selected Subtitle Information", show_header=False)
            info_table.add_column("Property", style="cyan")
            info_table.add_column("Value", style="yellow")

            info_table.add_row("Movie Name", movie_name)
            info_table.add_row("Subtitle ID", sub["id"])
            info_table.add_row("File ID", str(attrs["files"][0]["file_id"]))
            info_table.add_row("Language", attrs["language"])
            info_table.add_row("Release", attrs["release"])
            info_table.add_row("Downloads", str(attrs["download_count"]))
            info_table.add_row(
                "AI Translated", "Yes" if attrs["ai_translated"] else "No"
            )
            info_table.add_row(
                "Machine Translated", "Yes" if attrs["machine_translated"] else "No"
            )
            info_table.add_row(
                "Hash Match", "Yes" if attrs.get("moviehash_match", False) else "No"
            )
            info_table.add_row("URL", attrs["url"])

            self.console.print(info_table)
        except (KeyError, TypeError, IndexError) as e:
            self.console.print(f"[bold red]Error printing subtitle information: {e}[/]")
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error: {e}[/]")


if __name__ == "__main__":
    print("This is a module, import it in your project")
