# SubDL.py is a class that handles subtitle search and download from SubDL API.
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from library.subtitle_utils import SubtitleUtils


@dataclass
class SearchResult:
    subtitles: list[dict[str, Any]]
    metadata_results: list[dict[str, Any]]


class SubDL:
    def __init__(
        self,
        api_key,
        sync_audio_to_subs=False,
        hearing_impaired=False,
        auto_select=True,
        output_directory=None,
    ):
        self.api_key = api_key
        self.sync_audio_to_subs = sync_audio_to_subs
        self.hearing_impaired = hearing_impaired
        self.auto_select = auto_select
        self.output_directory = (
            Path(output_directory) if output_directory is not None else None
        )
        self.api_base_url = "https://api.subdl.com/api/v2"
        self.download_base_url = "https://dl.subdl.com"
        self.console = Console()
        self.subtitle_utils = SubtitleUtils()
        self.standardize_subtitle_objects = None
        self._last_request_error = None

    def _output_path(self, media_path, filename):
        directory = self.output_directory or Path(media_path).parent
        if self.output_directory is not None:
            directory.mkdir(parents=True, exist_ok=True)
        return directory / filename

    def _request(self, path, params):
        """GET a v2 endpoint with Bearer auth and return parsed JSON."""
        try:
            response = requests.get(
                self.api_base_url + path,
                params=params,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            self._last_request_error = exc
            raise

    def _parse(self, data):
        """Return (subtitles, metadata). Handles v2 error and success shapes."""
        if not isinstance(data, dict):
            return [], []
        if "error" in data:
            err = data["error"]
            msg = err.get("message", err) if isinstance(err, dict) else err
            self.console.print(f"[bold red]SubDL API error: {msg}[/]")
            return [], []
        subtitles = data.get("subtitles", []) or []
        metadata = data.get("results", []) or []
        return subtitles, metadata

    def _standardize(self, subtitles):
        standardized = [
            self.subtitle_utils.standardize_subtitle_object(sub, "subdl")
            for sub in subtitles
        ]
        return [s for s in standardized if s]

    def search(
        self,
        file_name="",
        film_name="",
        imdb_id="",
        tmdb_id="",
        sd_id="",
        languages="en",
        season=None,
        episode=None,
        full_season=False,
        type="",
        unpack=True,
    ) -> SearchResult:
        """Search subtitles via /subtitles/search. Accepts any one identifier."""
        params = {"languages": languages}
        if file_name:
            params["file_name"] = file_name
        if film_name:
            params["film_name"] = film_name
        if imdb_id:
            params["imdb_id"] = imdb_id
        if tmdb_id:
            params["tmdb_id"] = tmdb_id
        if sd_id:
            params["sd_id"] = sd_id
        if type:
            params["type"] = type
        if season is not None:
            params["season"] = season
        if episode is not None:
            params["episode"] = episode
        if full_season:
            params["full_season"] = 1
        if unpack:
            params["unpack"] = 1

        try:
            data = self._request("/subtitles/search", params)
            subtitles, metadata = self._parse(data)
            standardized = self._standardize(subtitles)
            if standardized:
                self.console.print(
                    f"[green]Found {len(standardized)} subtitles[/green]"
                )
            self.standardize_subtitle_objects = standardized
            return SearchResult(subtitles=standardized, metadata_results=metadata)
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubDL API request: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])
        except (KeyError, ValueError) as e:
            self.console.print(f"[bold red]Error decoding SubDL API response: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])

    def filename_search(
        self, filename, languages="en", subs_per_page=30
    ) -> SearchResult:
        """Search by release filename and return its title and subtitles."""
        params = {
            "filename": filename,
            "languages": languages,
            "subs_per_page": subs_per_page,
        }
        try:
            data = self._request("/files/search", params)
            subtitles, metadata = self._parse(data)
            standardized = self._standardize(subtitles)
            return SearchResult(subtitles=standardized, metadata_results=metadata)
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubDL filename search: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])
        except (KeyError, ValueError) as e:
            self.console.print(
                f"[bold red]Error decoding SubDL filename search response: {e}[/]"
            )
            return SearchResult(subtitles=[], metadata_results=[])

    def movie_search(self, q, type="", limit=10):
        """Resolve a title to provider IDs and return matching results."""
        params = {"q": q, "limit": limit}
        if type:
            params["type"] = type
        try:
            data = self._request("/movies/search", params)
            _, metadata = self._parse(data)
            return metadata
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubDL movie search: {e}[/]")
            return []
        except (KeyError, ValueError) as e:
            self.console.print(
                f"[bold red]Error decoding SubDL movie search response: {e}[/]"
            )
            return []

    def _gather_candidates(self, path, language):
        """Run all search sources, merge, filter, and dedupe into one candidate list."""
        media_name = path.stem
        subs = []
        metadata = []

        def add(result):
            subs.extend(result.subtitles)
            metadata.extend(result.metadata_results)

        # 1) NEW: purpose-built filename search (also resolves the title id)
        add(self.filename_search(filename=media_name, languages=language))

        # 2) by filename (legacy)
        add(self.search(file_name=media_name, languages=language))

        # 3) by series name
        series_match = re.search(r"(.+?)(?:\s-\sS\d{2}E\d{2}|\s-\s\d{4})", media_name)
        if series_match:
            add(self.search(film_name=series_match.group(1), languages=language))

        # resolve season/episode once for the precise TV pass
        video_season, video_episode = self.subtitle_utils.extract_season_and_episode(
            media_name
        )

        # 4) by IMDb ids resolved from any metadata, narrowed by season/episode for TV
        imdb_ids = {m["imdb_id"] for m in metadata if m.get("imdb_id")}
        for imdb_id in imdb_ids:
            add(
                self.search(
                    imdb_id=imdb_id,
                    languages=language,
                    season=video_season,
                    episode=video_episode,
                )
            )

        # 5) by alternate filename variants
        for term in self.subtitle_utils.get_alternate_names(media_name) or []:
            add(self.search(file_name=term, languages=language))

        # 6) last-resort title resolution if nothing matched a title id
        if not imdb_ids:
            for title in self.movie_search(media_name):
                if title.get("imdb_id"):
                    add(
                        self.search(
                            imdb_id=title["imdb_id"],
                            languages=language,
                            season=video_season,
                            episode=video_episode,
                        )
                    )

        # hearing-impaired preference (v2 has no hi param; filter client-side)
        if self.hearing_impaired:
            subs = [s for s in subs if s.get("attributes", {}).get("hi")]

        # dedupe by subtitle id
        return list({s["id"]: s for s in subs if s.get("id")}.values())

    def search_candidates(self, path, language, query=""):
        """Return candidates without selection, printing, or downloading."""
        self._last_request_error = None
        search_path = Path(query.strip()) if query.strip() else Path(path)
        candidates = self._gather_candidates(search_path, language)
        if not candidates and self._last_request_error is not None:
            raise RuntimeError(
                f"SubDL search request failed: {self._last_request_error}"
            )
        return candidates

    def _select_unpack_file(self, attrs, video_season, video_episode, is_movie):
        """Return the best unpacked file URL and format, if one exists."""
        unpack_files = attrs.get("unpack_files") or []
        if not unpack_files:
            return None, None
        if is_movie:
            chosen = unpack_files[0]
        else:
            chosen = next(
                (
                    f
                    for f in unpack_files
                    if f.get("season") == video_season
                    and f.get("episode") == video_episode
                ),
                None,
            )
            if chosen is None:
                chosen = next(
                    (f for f in unpack_files if f.get("episode") == video_episode), None
                )
            if chosen is None:
                # No episode match: return no single file so download_single_subtitle
                # falls back to the zip path (filename-based match, loud failure).
                # Do NOT default to unpack_files[0] -- that can save the wrong episode.
                return None, None
        return chosen.get("url"), chosen.get("format", "srt")

    def _decode_bytes(self, content):
        for encoding in ("utf-8", "utf-16", "cp1252", "iso-8859-1", "latin1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    def _target_subtitle_name(self, video_input_path, language_choice, ext):
        if language_choice:
            return f"{video_input_path.stem}.{language_choice}{ext}"
        return f"{video_input_path.stem}{ext}"

    def _download_url(self, value):
        if value.startswith(("https://", "http://")):
            return value
        return self.download_base_url + value

    def _download_single_file(self, rel_url, fmt, video_input_path, language_choice):
        abs_url = self._download_url(rel_url)
        response = requests.get(abs_url, timeout=10)
        response.raise_for_status()
        ext = f".{fmt}" if fmt in ("srt", "ass", "vtt") else ".srt"
        target_filename = self._target_subtitle_name(
            video_input_path, language_choice, ext
        )
        target_path = self._output_path(video_input_path, target_filename)
        if self.output_directory is not None and target_path.exists():
            self.console.print(f"[bold red]Subtitle already exists: {target_path}[/]")
            return None
        decoded = self._decode_bytes(response.content)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(decoded)
        self.console.print(
            f"[green]Subtitle downloaded and saved as: {target_filename}[/green]"
        )
        return target_path

    def _download_zip(
        self,
        rel_url,
        video_input_path,
        language_choice,
        video_season,
        video_episode,
        is_movie,
    ):
        abs_url = self._download_url(rel_url)
        response = requests.get(abs_url, stream=True, timeout=10)
        response.raise_for_status()
        zip_path = self._output_path(
            video_input_path,
            f"{video_input_path.stem}.zip",
        )
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        if language_choice:
            subtitle_filename = f"{video_input_path.stem}.{language_choice}.ass"
            fallback_filename = f"{video_input_path.stem}.{language_choice}.srt"
        else:
            subtitle_filename = f"{video_input_path.stem}.ass"
            fallback_filename = f"{video_input_path.stem}.srt"

        if not is_movie and (video_season is None or video_episode is None):
            self.console.print(
                "[bold red]Error: Could not extract season/episode from "
                "video filename[/]"
            )
            zip_path.unlink(missing_ok=True)
            return None

        selected_subtitle_path = None
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                extracted_files = zip_ref.namelist()
                ass_files = [f for f in extracted_files if f.endswith(".ass")]
                srt_files = [f for f in extracted_files if f.endswith(".srt")]

                if not ass_files and not srt_files:
                    self.console.print(
                        "[bold red]Error: No .ass or .srt subtitle files "
                        "found in the archive.[/]"
                    )
                    return None

                if is_movie:
                    matching_subtitle = (ass_files + srt_files)[0]
                else:
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

                for subtitle_file in ass_files + srt_files:
                    try:
                        with zip_ref.open(subtitle_file) as source:
                            decoded_content = self._decode_bytes(source.read())

                        if subtitle_file == matching_subtitle:
                            target_filename = (
                                subtitle_filename
                                if subtitle_file.endswith(".ass")
                                else fallback_filename
                            )
                            selected_subtitle_path = self._output_path(
                                video_input_path,
                                target_filename,
                            )
                        else:
                            original_name = Path(subtitle_file).stem
                            extension = Path(subtitle_file).suffix
                            target_filename = (
                                f"{original_name}.{language_choice}{extension}"
                            )

                        target_path = self._output_path(
                            video_input_path,
                            target_filename,
                        )
                        if self.output_directory is not None and target_path.exists():
                            if target_path == selected_subtitle_path:
                                selected_subtitle_path = None
                            self.console.print(
                                f"[bold red]Subtitle already exists: {target_path}[/]"
                            )
                            continue
                        with open(target_path, "w", encoding="utf-8") as target:
                            target.write(decoded_content)
                        self.console.print(
                            "[green]Subtitle extracted and saved as: "
                            f"{target_filename}[/green]"
                        )
                    except Exception as e:
                        self.console.print(
                            "[bold red]Error processing subtitle file "
                            f"{subtitle_file}: {e}[/]"
                        )
        finally:
            zip_path.unlink(missing_ok=True)

        if selected_subtitle_path is None:
            self.console.print(
                f"[bold yellow]Warning: Could not find matching episode "
                f"(S{video_season:02d}E{video_episode:02d}) in the subtitle pack[/]"
            )
        return selected_subtitle_path

    def download_single_subtitle(self, subtitle, video_input_path, language_choice=""):
        """Download one subtitle, preferring an unpacked file over an archive."""
        attrs = subtitle.get("attributes", {}) if isinstance(subtitle, dict) else {}
        try:
            video_season, video_episode = (
                self.subtitle_utils.extract_season_and_episode(str(video_input_path))
            )
            is_movie = video_season is None and video_episode is None

            single_url, single_format = self._select_unpack_file(
                attrs, video_season, video_episode, is_movie
            )
            if single_url:
                return self._download_single_file(
                    single_url, single_format, video_input_path, language_choice
                )

            zip_url = attrs.get("url", "")
            if not zip_url:
                self.console.print("[bold red]Error: subtitle has no download url.[/]")
                return None
            return self._download_zip(
                zip_url,
                video_input_path,
                language_choice,
                video_season,
                video_episode,
                is_movie,
            )
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error downloading subtitle: {e}[/]")
            return None
        except zipfile.BadZipFile:
            self.console.print(
                "[bold red]Error: Downloaded file is not a valid ZIP.[/]"
            )
            return None
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error: {e}[/]")
            return None

    def process_media_file(self, media_path, language_choice, media_name=""):
        try:
            path = Path(media_path)
            self.subtitle_utils.hashFile(path)
            if not media_name:
                media_name = path.stem
            rprint(
                "[cyan]Searching for subtitles for[/cyan] "
                f"[yellow]{media_name}[/yellow]"
            )
            subtitles_list = self._gather_candidates(path, language_choice)
            if not subtitles_list:
                rprint(f"[red]No subtitles found for {media_name}[/red]")
                return False
            rprint(
                "[green]Total unique results after all searches: "
                f"{len(subtitles_list)}[/green]"
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
                selected_sub, path, language_choice
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
                    "[bold red]Unexpected error processing media list item "
                    f"{media_path}: {e}[/]"
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
