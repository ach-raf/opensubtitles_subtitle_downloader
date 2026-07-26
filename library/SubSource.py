# Handles subtitle search and download through the SubSource API.
# API docs: https://subsource.net/api-docs (base: https://api.subsource.net/api/v1)
#
# Key API differences from SubDL (verified against the live API):
#   - Authentication uses the `X-API-Key` header (not Bearer).
#   - Language filtering takes full names rather than ISO codes.
#   - Movie search is `searchType=text&q=...` or `searchType=imdb&imdb=tt...`.
#   - A TV series has a SEPARATE movieId per season (e.g. Breaking Bad S2 != S3), so TV
#     lookup must resolve the target season to its movieId via movie search.
#   - Downloads are ALWAYS a .zip (single-file subs come zipped too); there is no
#     unpack_files / single-file path, so download_single_subtitle always goes through
#     _download_zip and uses filename-based season/episode matching.
#   - `releaseInfo` is a list of release names; we join them for scoring.
import os
import re
import shutil
import subprocess
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from library.subtitle_utils import SubtitleUtils

# Map ISO-639-1 codes used elsewhere in this project to SubSource's full language names.
# SubSource filters by full name (e.g. "english"), not by code ("en").
SUBSOURCE_LANGUAGE_MAP = {
    "en": "english",
    "ar": "arabic",
    "fr": "french",
    "ja": "japanese",
    "es": "spanish",
    "de": "german",
    "it": "italian",
    "pt": "portuguese",
    "pt-br": "brazilian_portuguese",
    "zh": "chinese",
    "ko": "korean",
    "ru": "russian",
    "hi": "hindi",
    "tr": "turkish",
    "pl": "polish",
    "nl": "dutch",
    "id": "indonesian",
    "vi": "vietnamese",
    "th": "thai",
    "sv": "swedish",
    "da": "danish",
    "fi": "finnish",
    "no": "norwegian",
    "cs": "czech",
    "el": "greek",
    "he": "hebrew",
    "hu": "hungarian",
    "ro": "romanian",
    "uk": "ukrainian",
    "ms": "malay",
    "bn": "bengali",
    "fa": "persian",
    "ur": "urdu",
    "ta": "tamil",
    "te": "telugu",
    "tl": "tagalog",
}


@dataclass
class SearchResult:
    subtitles: list[dict[str, Any]]
    metadata_results: list[dict[str, Any]]


class _SevenZipArchive:
    """Minimal adapter exposing .names()/.read(name)/.close() over the 7-Zip CLI.

    Used as a fallback for RAR extraction when the `rarfile` package is not
    installed but a 7z executable is available. Each read shells out to 7z, so
    this is slower than the in-process paths but only used for legacy .rar uploads.
    """

    def __init__(self, path, exe):
        self._path = str(path)
        self._exe = exe
        completed = subprocess.run(
            [self._exe, "l", "-ba", self._path],
            capture_output=True,
            check=True,
        )
        listing = completed.stdout.decode("utf-8", errors="replace")
        self._names = []
        for line in listing.splitlines():
            # `7z l -ba`: one entry per line as "date time attr size compressed name"
            parts = line.split(None, 5)
            if len(parts) == 6:
                self._names.append(parts[5])

    def names(self):
        return list(self._names)

    def read(self, name):
        result = subprocess.run(
            [self._exe, "e", "-so", self._path, name],
            capture_output=True,
            check=True,
        )
        return result.stdout

    def close(self):
        # Nothing held open; the CLI is invoked per-operation.
        return None


class SubSource:
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
        self.api_base_url = "https://api.subsource.net/api/v1"
        self.console = Console()
        self.subtitle_utils = SubtitleUtils()
        self.standardize_subtitle_objects = None
        self._last_request_error = None

    # ------------------------------------------------------------------ #
    # HTTP / parsing helpers
    # ------------------------------------------------------------------ #
    def _request(self, path, params):
        """GET a v1 endpoint with the X-API-Key header and return parsed JSON."""
        try:
            response = requests.get(
                self.api_base_url + path,
                params=params,
                headers={"X-API-Key": self.api_key},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            self._last_request_error = exc
            raise

    def _get_raw(self, url):
        """GET an absolute URL (download) with the X-API-Key header."""
        response = requests.get(
            url, headers={"X-API-Key": self.api_key}, timeout=10, stream=True
        )
        response.raise_for_status()
        return response

    def _parse_list(self, data):
        """Return (subtitles, movies). Handles the {success, data, error} shape."""
        if not isinstance(data, dict):
            return [], []
        if data.get("error") or not data.get("success", True):
            msg = data.get("message", data.get("error"))
            self.console.print(f"[bold red]SubSource API error: {msg}[/]")
            return [], []
        items = data.get("data", []) or []
        if isinstance(items, dict):  # /movies/{id} returns a single object
            items = [items]
        # The /subtitles list and /movies/search both return a flat `data` list; we
        # tell them apart by whether the first item looks like a subtitle or a movie.
        return items, items

    def _standardize(self, subtitles):
        standardized = [
            self.subtitle_utils.standardize_subtitle_object(sub, "subsource")
            for sub in subtitles
        ]
        return [s for s in standardized if s]

    def _language_param(self, language_code):
        """Translate the project's ISO code to SubSource's full language name.
        Falls back to the raw value so unmapped codes still get sent verbatim."""
        if not language_code:
            return ""
        return SUBSOURCE_LANGUAGE_MAP.get(language_code.lower(), language_code)

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    def movie_search(
        self, query="", imdb_id="", search_type="text", limit=10
    ) -> list[dict[str, Any]]:
        """Resolve a title/imdb to movie records via /movies/search.

        Returns ALL movieIds for a series (one per season) so the caller can pick
        the season it needs.
        """
        params = {"searchType": search_type, "limit": limit}
        if search_type == "imdb":
            if not imdb_id:
                return []
            params["imdb"] = imdb_id
        else:
            if not query:
                return []
            params["q"] = query

        try:
            data = self._request("/movies/search", params)
            if data.get("error") or not data.get("success", True):
                msg = data.get("message", data.get("error"))
                self.console.print(f"[bold red]SubSource movie search error: {msg}[/]")
                return []
            return data.get("data", []) or []
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubSource movie search: {e}[/]")
            return []
        except (KeyError, ValueError) as e:
            self.console.print(
                f"[bold red]Error decoding SubSource movie search response: {e}[/]"
            )
            return []

    def get_movie(self, movie_id):
        """GET /movies/{id} -> single movie record (or None)."""
        try:
            data = self._request(f"/movies/{movie_id}", {})
            if data.get("error") or not data.get("success", True):
                return None
            item = data.get("data")
            return item if isinstance(item, dict) else None
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubSource get_movie: {e}[/]")
            return None
        except (KeyError, ValueError) as e:
            self.console.print(
                f"[bold red]Error decoding SubSource get_movie response: {e}[/]"
            )
            return None

    def subtitles_for_movie(
        self,
        movie_id,
        language_code="en",
        season=None,
        episode=None,
        hearing_impaired=None,
        limit=50,
    ) -> SearchResult:
        """GET /subtitles?movieId=... filtered by language. Returns standardized subs.

        SubSource has one movieId per season, so `season`/`episode` here are NOT sent
        to the API -- they are recorded on each standardized subtitle so the existing
        zip filename-matcher in download_single_subtitle can pick the right file.
        """
        params = {"movieId": movie_id, "limit": limit, "sort": "downloads"}
        lang_name = self._language_param(language_code)
        if lang_name:
            params["language"] = lang_name
        if hearing_impaired is True:
            params["hearingImpaired"] = "true"
        if hearing_impaired is False:
            # Don't actively exclude non-HI subs unless explicitly asked; only force HI.
            pass

        try:
            data = self._request("/subtitles", params)
            raw_subs, _ = self._parse_list(data)
            standardized = self._standardize(raw_subs)
            if standardized:
                self.console.print(
                    f"[green]Found {len(standardized)} subtitles "
                    f"(movieId {movie_id})[/green]"
                )
            self.standardize_subtitle_objects = standardized
            return SearchResult(subtitles=standardized, metadata_results=[])
        except requests.exceptions.RequestException as e:
            self.console.print(
                f"[bold red]Error during SubSource subtitles request: {e}[/]"
            )
            return SearchResult(subtitles=[], metadata_results=[])
        except (KeyError, ValueError) as e:
            self.console.print(
                f"[bold red]Error decoding SubSource subtitles response: {e}[/]"
            )
            return SearchResult(subtitles=[], metadata_results=[])

    # ------------------------------------------------------------------ #
    # Candidate gathering
    # ------------------------------------------------------------------ #
    def _resolve_movie_ids(
        self, media_name, video_season, video_episode
    ) -> list[tuple[int, int | None]]:
        """Return a list of (movieId, season) pairs relevant to this media.

        SubSource assigns a distinct movieId per season, so for TV we resolve the
        title then keep only the season matching the filename (falling back to all
        seasons if we can't find the exact one).
        """
        # Try a title (series/film name) search first.
        series_match = re.search(r"(.+?)(?:\s-\sS\d{2}E\d{2}|\s-\s\d{4})", media_name)
        query = series_match.group(1) if series_match else media_name

        movies = self.movie_search(query=query, search_type="text", limit=30)

        # If a title search was too noisy or empty, let the caller try imdb later.
        if not movies:
            return []

        results: list[tuple[int, int | None]] = []
        seen = set()
        for m in movies:
            mid = m.get("movieId")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            m_season = m.get("season")
            mtype = (m.get("type") or "").lower()

            if video_season is not None and mtype in ("tvseries", "tv"):
                # TV: prefer the season matching the filename.
                if m_season == video_season:
                    results.append((mid, m_season))
            elif mtype in ("movie", "") or m_season is None:
                # A movie has a single movieId and season == None.
                results.append((mid, None))

        # If we asked for a specific TV season but found no exact match, fall back
        # to all seasons returned for that title -- the zip matcher will still pick
        # the right episode from inside the pack.
        if not results and video_season is not None:
            results = [
                (m.get("movieId"), m.get("season"))
                for m in movies
                if m.get("movieId")
                and (m.get("type") or "").lower() in ("tvseries", "tv")
            ]
            results = list({(mid, s) for mid, s in results})

        return results

    def _gather_candidates(self, path, language) -> list[dict[str, Any]]:
        """Resolve movie ids, fetch subtitles for each, then dedupe by subtitle id."""
        media_name = path.stem
        subs: list[dict[str, Any]] = []

        video_season, video_episode = self.subtitle_utils.extract_season_and_episode(
            media_name
        )

        # Resolve candidate movieIds (one per season for TV).
        pairs = self._resolve_movie_ids(media_name, video_season, video_episode)

        # If title search found nothing, try an imdb resolution via the filename's
        # embedded tt-id if present (rare, but cheap to check).
        if not pairs:
            imdb_match = re.search(r"(tt\d{7,8})", media_name, re.IGNORECASE)
            if imdb_match:
                movies = self.movie_search(
                    imdb_id=imdb_match.group(1), search_type="imdb", limit=10
                )
                pairs = [
                    (m.get("movieId"), m.get("season"))
                    for m in movies
                    if m.get("movieId")
                ]

        if not pairs:
            self.console.print(
                f"[yellow]No movie found on SubSource for '{media_name}'[/yellow]"
            )
            return []

        for movie_id, _season in pairs:
            result = self.subtitles_for_movie(
                movie_id,
                language_code=language,
                season=video_season,
                episode=video_episode,
                hearing_impaired=self.hearing_impaired,
                limit=50,
            )
            subs.extend(result.subtitles)

        # hearing-impaired preference (filter client-side as a safety net, since the
        # API filter is sometimes flaky).
        if self.hearing_impaired:
            subs = [s for s in subs if s.get("attributes", {}).get("hi")]

        # dedupe by subtitle id
        return list({s["id"]: s for s in subs if s.get("id")}.values())

    def search_candidates(self, path, language, query=""):
        """Return candidates without selection or download side effects."""
        self._last_request_error = None
        search_path = Path(query.strip()) if query.strip() else Path(path)
        candidates = self._gather_candidates(search_path, language)
        if not candidates and self._last_request_error is not None:
            raise RuntimeError(
                f"SubSource search request failed: {self._last_request_error}"
            )
        return candidates

    # ------------------------------------------------------------------ #
    # Download
    # ------------------------------------------------------------------ #
    def _decode_bytes(self, content):
        for encoding in ("utf-8", "utf-16", "cp1252", "iso-8859-1", "latin1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    def _download_url_for(self, subtitle_id):
        return f"{self.api_base_url}/subtitles/{subtitle_id}/download"

    # ------------------------------------------------------------------ #
    # Archive abstraction (ZIP via stdlib, RAR via rarfile/7-Zip)
    #
    # SubSource serves older uploads as .rar and newer ones as .zip, with no
    # Content-Type distinction we can branch on at request time. We detect the
    # format from the downloaded bytes' magic signature and dispatch below.
    # ------------------------------------------------------------------ #
    def _is_rar(self, path):
        try:
            with open(path, "rb") as f:
                return f.read(4) == b"Rar!"
        except OSError:
            return False

    def _find_7z(self):
        """Locate a 7-Zip executable in common Windows install locations or on PATH."""
        exe = shutil.which("7z") or shutil.which("7z.exe")
        if exe:
            return exe
        for candidate in (
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ):
            if os.path.isfile(candidate):
                return candidate
        return None

    def _open_archive(self, path):
        """Return an archive handle with .names() and .read(name), or raise.

        SubSource serves older uploads as .rar and newer ones as .zip, with no
        Content-Type we can branch on at request time, so we detect the format
        from the magic bytes and dispatch below. The returned object must be
        .close()'d by the caller.
        """
        is_rar = self._is_rar(path)
        if is_rar:
            try:
                import rarfile  # type: ignore

                rf = rarfile.RarFile(path)
                rf.names = rf.namelist  # type: ignore[attr-defined]
                return rf
            except ImportError:
                sevenz = self._find_7z()
                if not sevenz:
                    raise RuntimeError(
                        "RAR archives require the 'rarfile' Python package "
                        "(pip install rarfile) or a '7z' executable on PATH / "
                        "in C:\\Program Files\\7-Zip."
                    ) from None
                return _SevenZipArchive(path, sevenz)
        else:
            zf = zipfile.ZipFile(path, "r")
            zf.names = zf.namelist  # type: ignore[attr-defined]
            return zf

    def _download_archive(
        self,
        subtitle,
        video_input_path,
        language_choice,
        video_season,
        video_episode,
        is_movie,
    ):
        """Stream a SubSource download (zip or rar) and extract the best match.

        SubSource always returns an archive; we extract every subtitle file in it
        and pick the season/episode match for TV (or the first for a movie).
        """
        subtitle_id = subtitle.get("id")
        abs_url = self._download_url_for(subtitle_id)
        response = self._get_raw(abs_url)

        archive_path = video_input_path.with_suffix(".download")
        archive = None
        try:
            with open(archive_path, "wb") as f:
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
                    "[bold red]Error: Could not extract season/episode "
                    "from video filename[/]"
                )
                return None

            try:
                archive = self._open_archive(archive_path)
            except RuntimeError as e:
                self.console.print(f"[bold red]Cannot extract archive: {e}[/]")
                return None

            sub_files = [
                n
                for n in archive.names()
                if Path(n).suffix.lower() in (".ass", ".srt", ".ssa", ".vtt", ".sub")
            ]
            if not sub_files:
                self.console.print(
                    "[bold red]Error: No subtitle files found in the archive.[/]"
                )
                return None

            # Pick the matching file for TV by parsing season/episode from each
            # entry name; for a movie take the first.
            if is_movie:
                matching_subtitle = sub_files[0]
            else:
                matching_subtitle = None
                for sf in sub_files:
                    sub_season, sub_episode = (
                        self.subtitle_utils.extract_season_and_episode(sf)
                    )
                    if sub_season == video_season and sub_episode == video_episode:
                        matching_subtitle = sf
                        break

            selected_subtitle_path = None
            for sf in sub_files:
                try:
                    decoded_content = self._decode_bytes(archive.read(sf))

                    if sf == matching_subtitle:
                        ext = ".ass" if sf.lower().endswith(".ass") else ".srt"
                        target_filename = (
                            subtitle_filename if ext == ".ass" else fallback_filename
                        )
                        selected_subtitle_path = (
                            video_input_path.parent / target_filename
                        )
                    else:
                        original_name = Path(sf).stem
                        extension = Path(sf).suffix
                        target_filename = (
                            f"{original_name}.{language_choice}{extension}"
                            if language_choice
                            else f"{original_name}{extension}"
                        )

                    target_path = video_input_path.parent / target_filename
                    with open(target_path, "w", encoding="utf-8") as target:
                        target.write(decoded_content)
                    self.console.print(
                        f"[green]Subtitle extracted and saved as: "
                        f"{target_filename}[/green]"
                    )
                except Exception as e:
                    self.console.print(
                        f"[bold red]Error processing subtitle file {sf}: {e}[/]"
                    )
        finally:
            if archive is not None:
                with suppress(Exception):
                    archive.close()
            archive_path.unlink(missing_ok=True)

        if selected_subtitle_path is None and not is_movie:
            self.console.print(
                f"[bold yellow]Warning: Could not find matching episode "
                f"(S{video_season:02d}E{video_episode:02d}) in the subtitle pack[/]"
            )
        return selected_subtitle_path

    def download_single_subtitle(self, subtitle, video_input_path, language_choice=""):
        """Download one SubSource subtitle. SubSource always serves an archive
        (.zip for newer uploads, .rar for some older ones)."""
        try:
            # Parse season/episode from the FILENAME only, not the full path: the
            # single-letter E(\d) pattern in extract_season_and_episode can match
            # substrings inside directory names (e.g. a temp dir ending in 'e07').
            video_season, video_episode = (
                self.subtitle_utils.extract_season_and_episode(video_input_path.name)
            )
            is_movie = video_season is None and video_episode is None

            if not subtitle.get("id"):
                self.console.print(
                    "[bold red]Error: subtitle has no id, cannot build download URL.[/]"
                )
                return None
            return self._download_archive(
                subtitle,
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
                "[bold red]Error: Downloaded archive is not a valid ZIP/RAR.[/]"
            )
            return None
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error: {e}[/]")
            return None

    # ------------------------------------------------------------------ #
    # Orchestration (mirrors SubDL)
    # ------------------------------------------------------------------ #
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
                f"[green]Total unique results after all searches: "
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
                    f"[bold red]Unexpected error processing media list item "
                    f"{media_path}: {e}[/]"
                )

    def print_subtitle_info(self, sub):
        try:
            attrs = sub["attributes"]

            info_table = Table(title="Selected Subtitle Information", show_header=False)
            info_table.add_column("Property", style="cyan")
            info_table.add_column("Value", style="yellow")

            info_table.add_row("Release", attrs["release"])
            info_table.add_row("Subtitle ID", str(sub["id"]))
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
            info_table.add_row("URL", attrs.get("url", ""))

            self.console.print(info_table)
        except (KeyError, TypeError, IndexError) as e:
            self.console.print(f"[bold red]Error printing subtitle information: {e}[/]")
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error: {e}[/]")


if __name__ == "__main__":
    print("This is a module, import it in your project")
