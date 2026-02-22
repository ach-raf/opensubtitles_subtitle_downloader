# SubDL.py is a class that handles subtitle search and download from SubDL API.
import requests
import zipfile
from pathlib import Path
import re
import json
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from library.subtitle_utils import SubtitleUtils
from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class SearchResult:
    subtitles: List[Dict[str, Any]]
    metadata_results: List[Dict[str, Any]]


class SubDL:

    def __init__(
        self,
        api_key,
        sync_audio_to_subs=False,
        hearing_impaired=False,
        auto_select=True,
    ):
        self.api_key = api_key
        self.sync_audio_to_subs = sync_audio_to_subs
        self.hearing_impaired = hearing_impaired
        self.auto_select = auto_select
        self.base_url = "https://api.subdl.com/api/v1/subtitles"
        self.download_base_url = "https://dl.subdl.com/subtitle/"
        self.console = Console()
        self.subtitle_utils = SubtitleUtils()
        self.standardize_subtitle_objects = None

    def search(
        self,
        film_name="",
        file_name="",
        imdb_id="",
        tmdb_id="",
        season_number=None,
        episode_number=None,
        content_type="",
        year=None,
        languages="en",
        full_season=False,
        comment=False,
        releases=False,
        sd_id="",
    ) -> SearchResult:
        """Search for subtitles using the SubDL API.

        Args:
            film_name (str): Text search by film name
            file_name (str): Search by file name
            imdb_id (str): Search by IMDb ID
            tmdb_id (str): Search by TMDB ID
            season_number (int): Specific season number for TV shows
            episode_number (int): Specific episode number for TV shows
            content_type (str): Type of content ('movie' or 'tv')
            year (int): Release year of the movie/show
            languages (str): Comma-separated language codes
            full_season (bool): Include full season subtitles
            comment (bool): Include author comments
            releases (bool): Include releases list
            sd_id (str): Search by SubDL ID
        """
        params = {
            "api_key": self.api_key,
            "subs_per_page": 30,
            "languages": languages,
        }

        if self.hearing_impaired:
            params["hi"] = 1
        if full_season:
            params["full_season"] = 1
        if comment:
            params["comment"] = 1
        if releases:
            params["releases"] = 1

        # Add optional search parameters
        for param, value in {
            "film_name": film_name,
            "file_name": file_name,
            "imdb_id": imdb_id,
            "tmdb_id": tmdb_id,
            "season_number": season_number,
            "episode_number": episode_number,
            "type": content_type,
            "year": year,
            "sd_id": sd_id,
        }.items():
            if value:
                params[param] = value

        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data["status"]:
                subtitles = data.get("subtitles", [])
                if subtitles:
                    self.console.print(
                        f"[green]Found {len(subtitles)} subtitles[/green]"
                    )

                # Standardize subtitle objects
                self.standardize_subtitle_objects = [
                    self.subtitle_utils.standardize_subtitle_object(sub, "subdl")
                    for sub in subtitles
                ]

                return SearchResult(
                    subtitles=self.standardize_subtitle_objects,
                    metadata_results=data.get("results", []),
                )

            self.console.print(
                f"[bold red]Error: SubDL API returned error: {data.get('error', 'Unknown error')}[/]"
            )
            return SearchResult(subtitles=[], metadata_results=[])

        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubDL API request: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])
        except (KeyError, json.decoder.JSONDecodeError) as e:
            self.console.print(f"[bold red]Error decoding SubDL API response: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error in SubDL search: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])

    def download_single_subtitle(
        self, subtitle_id, video_input_path, language_choice=""
    ):
        download_url = f"{self.download_base_url}{subtitle_id}"
        try:
            response = requests.get(download_url, stream=True, timeout=10)
            response.raise_for_status()
            zip_path = video_input_path.with_suffix(".zip")
            with open(zip_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Generate the desired subtitle filename for the selected episode
            if language_choice:
                subtitle_filename = f"{video_input_path.stem}.{language_choice}.ass"
                fallback_filename = f"{video_input_path.stem}.{language_choice}.srt"
            else:
                subtitle_filename = f"{video_input_path.stem}.ass"
                fallback_filename = f"{video_input_path.stem}.srt"

            # Extract season and episode from video filename
            video_season, video_episode = (
                self.subtitle_utils.extract_season_and_episode(str(video_input_path))
            )

            # Check if this is a movie (no season/episode info)
            is_movie = video_season is None and video_episode is None
            if not is_movie and (video_season is None or video_episode is None):
                self.console.print(
                    "[bold red]Error: Could not extract season/episode from video filename[/]"
                )
                return None

            selected_subtitle_path = None
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                extracted_files = zip_ref.namelist()

                # Get all subtitle files
                ass_files = [f for f in extracted_files if f.endswith(".ass")]
                srt_files = [f for f in extracted_files if f.endswith(".srt")]

                if not ass_files and not srt_files:
                    self.console.print(
                        "[bold red]Error: No .ass or .srt subtitle files found in the archive.[/]"
                    )
                    return None

                # For movies, just use the first subtitle file
                if is_movie:
                    matching_subtitle = (
                        (ass_files + srt_files)[0] if (ass_files or srt_files) else None
                    )
                else:
                    # Find the matching episode subtitle for TV shows
                    matching_subtitle = None
                    for subtitle_file in ass_files + srt_files:
                        sub_season, sub_episode = (
                            self.subtitle_utils.extract_season_and_episode(
                                subtitle_file
                            )
                        )
                        if sub_season == video_season and sub_episode == video_episode:
                            matching_subtitle = subtitle_file
                            break

                # Extract all subtitle files
                for subtitle_file in ass_files + srt_files:
                    try:
                        # Read subtitle content with encoding detection
                        with zip_ref.open(subtitle_file) as source:
                            content = source.read()

                            # Try different encodings
                            encodings = [
                                "utf-8",
                                "utf-16",
                                "cp1252",
                                "iso-8859-1",
                                "latin1",
                            ]
                            decoded_content = None

                            for encoding in encodings:
                                try:
                                    decoded_content = content.decode(encoding)
                                    break
                                except UnicodeDecodeError:
                                    continue

                            if decoded_content is None:
                                self.console.print(
                                    f"[bold red]Error: Failed to decode subtitle file {subtitle_file} with any known encoding[/]"
                                )
                                continue

                            # Determine target filename
                            # If it's the matching episode's subtitle, use the standard naming
                            if subtitle_file == matching_subtitle:
                                target_filename = (
                                    subtitle_filename
                                    if subtitle_file.endswith(".ass")
                                    else fallback_filename
                                )
                                selected_subtitle_path = (
                                    video_input_path.parent / target_filename
                                )
                            else:
                                # For other subtitles, keep their original names but add language code
                                original_name = Path(subtitle_file).stem
                                extension = Path(subtitle_file).suffix
                                target_filename = (
                                    f"{original_name}.{language_choice}{extension}"
                                )

                            # Write with UTF-8 encoding
                            target_path = video_input_path.parent / target_filename
                            with open(target_path, "w", encoding="utf-8") as target:
                                target.write(decoded_content)

                            self.console.print(
                                f"[green]Subtitle extracted and saved as: {target_filename}[/green]"
                            )

                    except Exception as e:
                        self.console.print(
                            f"[bold red]Error processing subtitle file {subtitle_file}: {e}[/]"
                        )

            # Clean up the zip file
            zip_path.unlink()

            if selected_subtitle_path is None:
                self.console.print(
                    f"[bold yellow]Warning: Could not find matching episode (S{video_season:02d}E{video_episode:02d}) in the subtitle pack[/]"
                )

            return selected_subtitle_path

        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error downloading subtitle: {e}[/]")
            return None
        except zipfile.BadZipFile:
            self.console.print(
                f"[bold red]Error: Downloaded file is not a valid ZIP for subtitle ID: {subtitle_id}[/]"
            )
            return None
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error: {e}[/]")
            return None

    def process_media_file(self, media_path, language_choice, media_name=""):
        try:
            path = Path(media_path)
            hash = self.subtitle_utils.hashFile(path)
            if not media_name:
                media_name = path.stem
            rprint(
                f"[cyan]Searching for subtitles for[/cyan] [yellow]{media_name}[/yellow]"
            )
            subtitle_path = Path(path.parent, f"{path.stem}.{language_choice}.srt")

            # Initial search by filename
            search_results = self.search(
                file_name=media_name, languages=language_choice
            )
            subtitles_list = search_results.subtitles
            if not subtitles_list:
                rprint(f"[red]No subtitles found for {media_name}[/red]")
            else:
                rprint(f"[green]Found {len(subtitles_list)} results[/green]")

            # parse series name and search for subtitles by series name alone series name exapmle: "The Flash 2014", "Dune - Prophecy (2024) - S01E01 - - The Hidden Hand [AMZN WEBDL-1080p][8bit][h264][EAC3 5.1]-playWEB"
            series_name = re.search(
                r"(.+?)(?:\s-\sS\d{2}E\d{2}|\s-\s\d{4})", media_name
            )

            if series_name:
                series_name = series_name.group(1)
                rprint(
                    f"[cyan]Searching for subtitles for series[/cyan] [yellow]{series_name}[/yellow]"
                )
                series_name_search_results = self.search(
                    film_name=series_name, languages=language_choice
                )
                subtitles_list.extend(series_name_search_results.subtitles)
                if not subtitles_list:
                    rprint(f"[red]No subtitles found for {series_name}[/red]")
                else:
                    rprint(f"[green]Found {len(subtitles_list)} results[/green]")

            # Second pass - search by IMDb IDs
            imdb_ids = set()
            for result in search_results.metadata_results:
                if "imdb_id" in result:
                    imdb_id = result["imdb_id"]
                    if imdb_id:
                        imdb_ids.add(imdb_id)

            # Search for each IMDb ID
            for imdb_id in imdb_ids:
                imdb_results = self.search(
                    imdb_id=imdb_id, languages=language_choice
                ).subtitles
                if imdb_results:
                    subtitles_list.extend(imdb_results)
                    rprint(
                        f"[blue]Adding more results by searching IMDb ID[/blue] [yellow]{imdb_id}[/yellow], [green]found {len(imdb_results)} results[/green]"
                    )

            # Add more results using alternate names
            new_search_terms = self.subtitle_utils.get_alternate_names(media_name)
            if new_search_terms:
                for term in new_search_terms:
                    temp_results = self.search(
                        file_name=term,
                        languages=language_choice,
                    ).subtitles
                    if temp_results:
                        subtitles_list.extend(temp_results)
                        rprint(
                            f"[blue]Adding more results by searching for[/blue] [yellow]{term}[/yellow], [green]found {len(temp_results)} results[/green]"
                        )

            if not subtitles_list:
                rprint(f"[red]No subtitles found for {media_name}[/red]")
                return False

            # Remove duplicates
            subtitles_list = list({v["id"]: v for v in subtitles_list}.values())
            rprint(
                f"[green]Total unique results after all searches: {len(subtitles_list)}[/green]"
            )

            if self.auto_select:
                selected_sub = self.subtitle_utils.auto_select_subtitle(
                    media_name, subtitles_list
                )
            else:
                selected_sub = self.subtitle_utils.manual_select_subtitle(
                    media_name, subtitles_list
                )

            if selected_sub is None:
                rprint("[yellow]Subtitle download cancelled.[/yellow]")
                return False

            subtitle_path = self.download_single_subtitle(
                selected_sub["id"], path, language_choice
            )
            if subtitle_path is None:
                return False

            rprint(
                f"[green]>> Downloading {language_choice} subtitles for {path}[/green]"
            )
            self.print_subtitle_info(selected_sub)
            self.subtitle_utils.clean_subtitles(subtitle_path)
            if self.sync_audio_to_subs == "ask":
                should_sync = self.subtitle_utils.ask_sync_subtitles()
                if should_sync:
                    self.subtitle_utils.sync_subtitles(path, subtitle_path)
            elif self.sync_audio_to_subs:
                self.subtitle_utils.sync_subtitles(path, subtitle_path)
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
                    for file_path in path.glob("**/*"):
                        if file_path.suffix.lower() in [".mp4", ".mkv", ".avi"]:
                            self.process_media_file(str(file_path), language_choice)
                elif path.suffix.lower() in [".mp4", ".mkv", ".avi"]:
                    self.process_media_file(str(path), language_choice)
            except Exception as e:
                self.console.print(
                    f"[bold red]Unexpected error processing media list item {media_path}: {e}[/]"
                )

    def print_subtitle_info(self, sub):
        try:
            attrs = sub["attributes"]
            # movie_name = attrs["feature_details"]["movie_name"]

            info_table = Table(title="Selected Subtitle Information", show_header=False)
            info_table.add_column("Property", style="cyan")
            info_table.add_column("Value", style="yellow")

            info_table.add_row("Release", attrs["release"])
            # info_table.add_row("Movie Name", movie_name)
            info_table.add_row("Subtitle ID", sub["id"])
            # info_table.add_row("File ID", str(attrs["files"][0]["file_id"]))
            info_table.add_row("Language", attrs["language"])
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
