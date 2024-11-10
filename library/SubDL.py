import os
import struct
import requests
import zipfile
from pathlib import Path
from thefuzz import fuzz
import difflib
import re
from rich.console import Console
from rich.table import Table
from rich import print as rprint
import library.clean_subtitles as clean_subtitles
import library.sync_subtitles as sync_subtitles


class SubDL:

    def __init__(
        self,
        api_key,
        sync_choice=False,
        hearing_impaired=False,
        auto_select=True,
    ):
        self.api_key = api_key
        self.sync_choice = sync_choice
        self.hearing_impaired = hearing_impaired
        self.auto_select = auto_select
        self.base_url = "https://api.subdl.com/api/v1/subtitles"
        self.download_base_url = "https://dl.subdl.com/subtitle/"
        self.console = Console()

    def hashFile(self, media_path):
        try:
            longlongformat = "Q"  # unsigned long long little endian
            bytesize = struct.calcsize(longlongformat)
            fmt = "<%d%s" % (65536 // bytesize, longlongformat)

            with open(media_path, "rb") as f:
                filesize = os.fstat(f.fileno()).st_size
                if filesize < 65536 * 2:
                    self.console.print(f"[red]File size error for {media_path}[/red]")
                    return "SizeError"

                filehash = filesize
                buf = f.read(65536)
                longlongs = struct.unpack(fmt, buf)
                filehash += sum(longlongs)

                f.seek(-65536, os.SEEK_END)
                buf = f.read(65536)
                longlongs = struct.unpack(fmt, buf)
                filehash += sum(longlongs)
                filehash &= 0xFFFFFFFFFFFFFFFF
            return "%016x" % filehash

        except IOError:
            self.console.print(
                f"[red]I/O error while generating hash for: {media_path}[/red]"
            )
            return "IOError"

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
    ):
        params = {
            "api_key": self.api_key,
            "subs_per_page": 30,
            "languages": languages,
        }
        if self.hearing_impaired:
            params["hi"] = 1

        if film_name:
            params["film_name"] = film_name
        if file_name:
            params["file_name"] = file_name
        if imdb_id:
            params["imdb_id"] = imdb_id
        if tmdb_id:
            params["tmdb_id"] = tmdb_id
        if season_number is not None:
            params["season_number"] = season_number
        if episode_number is not None:
            params["episode_number"] = episode_number
        if content_type:
            params["type"] = content_type
        if year:
            params["year"] = year

        try:
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            data = response.json()

            if data["status"]:
                subtitles = data.get("subtitles", [])
                if subtitles:
                    self.console.print(
                        f"[green]Found {len(subtitles)} subtitles[/green]"
                    )
                return subtitles
            else:
                self.console.print(
                    f"[red]Error: {data.get('error', 'Unknown error')}[/red]"
                )
                return []

        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error during API request: {e}[/red]")
            return []

    def extract_subtitle_id(self, url):
        if not url:
            return None
        # url format is '/subtitle/3158195-3172856.zip'
        parts = url.split("/")
        if len(parts) >= 3:
            return parts[2].replace(".zip", "")
        return None

    def extract_video_info(self, file_name):
        patterns = {
            "resolution": r"(720p|1080p|2160p|480p)",
            "year": r"(\d{4})",
            "release_group": r"(-[a-zA-Z0-9]+$)",
        }
        info = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, file_name)
            if match:
                info[key] = match.group(0).strip("-")
        return info

    def display_subtitles(self, subtitles):
        table = Table(title="Available Subtitles")

        table.add_column("Index", justify="center", style="cyan", no_wrap=True)
        table.add_column("Release Name", style="magenta")
        table.add_column("Language", justify="center", style="green")

        for idx, subtitle in enumerate(subtitles):
            table.add_row(
                str(idx + 1),
                subtitle.get("release_name", "Unknown"),
                subtitle.get("language", "Unknown"),
            )

        self.console.print(table)

    def auto_select_subtitle(self, video_file_name, subtitles_list):
        video_file_parts = set(video_file_name.lower().replace(".", " ").split())
        video_info = self.extract_video_info(video_file_name)

        max_score = -1
        best_subtitle = None

        for subtitle in subtitles_list:
            score = 0
            release_name = None
            for field in ["release_name", "fileName", "file_name", "name"]:
                if field in subtitle:
                    release_name = subtitle[field]
                    break

            if not release_name:
                continue

            release_parts = set(release_name.lower().replace(".", " ").split())
            subtitle_info = self.extract_video_info(release_name)

            # Score based on common words
            common_words = video_file_parts.intersection(release_parts)
            score += len(common_words) * 10

            # Boost score if key elements match (resolution, year, release group)
            for key in ["resolution", "year", "release_group"]:
                if key in video_info and key in subtitle_info:
                    if video_info[key] == subtitle_info[key]:
                        score += 50  # Boost score for matching key elements

            # Use fuzzy matching for the entire file name
            similarity = difflib.SequenceMatcher(
                None, video_file_name.lower(), release_name.lower()
            ).ratio()
            score += int(similarity * 100)

            # Update if the current subtitle has a higher score
            if score > max_score:
                max_score = score
                best_subtitle = subtitle

            # Early exit if we find a near-perfect match
            if max_score >= 200:
                break

        return best_subtitle

    def choose_subtitle(self, subtitles, video_file_name=None, auto_select=False):
        if auto_select and video_file_name:
            best_subtitle = self.auto_select_subtitle(video_file_name, subtitles)
            if best_subtitle:
                return best_subtitle
            else:
                self.console.print(
                    "[yellow]Auto-selection failed. Falling back to manual selection.[/yellow]"
                )

        self.display_subtitles(subtitles)
        while True:
            try:
                choice = (
                    int(
                        self.console.input(
                            "[bold yellow]Select subtitle by index: [/bold yellow]"
                        )
                    )
                    - 1
                )
                if 0 <= choice < len(subtitles):
                    return subtitles[choice]
                else:
                    self.console.print("[red]Invalid choice. Try again.[/red]")
            except ValueError:
                self.console.print("[red]Please enter a valid number.[/red]")

    def download_subtitle(self, subtitle_id, video_input_path, language_choice=""):
        download_url = f"{self.download_base_url}{subtitle_id}"
        try:
            response = requests.get(download_url)
            response.raise_for_status()
            zip_path = video_input_path.with_suffix(".zip")
            with open(zip_path, "wb") as f:
                f.write(response.content)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(video_input_path.parent)
                extracted_files = zip_ref.namelist()

                # Prioritize .ass file, else choose .srt file
                ass_files = [f for f in extracted_files if f.endswith(".ass")]
                srt_files = [f for f in extracted_files if f.endswith(".srt")]

                if ass_files:
                    selected_file = ass_files[0]
                elif srt_files:
                    selected_file = srt_files[0]
                else:
                    self.console.print(
                        f"[red]No .ass or .srt subtitle files found in the archive.[/red]"
                    )
                    return None

                # Add language choice before suffix if provided
                suffix = Path(selected_file).suffix
                if language_choice:
                    subtitle_path = video_input_path.with_name(
                        f"{video_input_path.stem}.{language_choice}{suffix}"
                    )
                else:
                    subtitle_path = video_input_path.with_suffix(suffix)

                selected_file_path = Path(video_input_path.parent, selected_file)
                selected_file_path.rename(subtitle_path)
                self.console.print(
                    f"[green]Subtitle downloaded and selected: {selected_file}[/green]"
                )

            # Clean up the zip file
            zip_path.unlink()

            return subtitle_path
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error downloading subtitle: {e}[/red]")
            return None
        except zipfile.BadZipFile:
            self.console.print(
                f"[red]Error: Downloaded file is not a valid ZIP for subtitle ID: {subtitle_id}[/red]"
            )
            return None
        except Exception as e:
            self.console.print(f"[red]Unexpected error: {e}[/red]")
            return None

    def process_media_file(self, media_path, language_choice):
        media_path = Path(media_path)
        media_name = media_path.stem

        self.console.print(f"[cyan]Searching for subtitles for {media_name}[/cyan]")

        results = self.search(file_name=media_name, languages=language_choice)
        if not results:
            clean_name = " ".join(
                word
                for word in media_name.replace(".", " ").split()
                if not any(char.isdigit() for char in word)
            )
            results = self.search(film_name=clean_name, languages=language_choice)

        if not results:
            self.console.print(f"[red]No subtitles found for {media_name}[/red]")
            return False

        selected_sub = self.choose_subtitle(
            results, media_name, auto_select=self.auto_select
        )
        subtitle_url = selected_sub.get("url")
        subtitle_id = self.extract_subtitle_id(subtitle_url)

        if not subtitle_id:
            self.console.print(
                f"[red]Could not extract subtitle ID for {media_name}[/red]"
            )
            return False

        self.console.print(
            f"[green]Selected subtitle: {selected_sub.get('release_name', 'Unknown')} (ID: {subtitle_id})[/green]"
        )
        subtitle_path = self.download_subtitle(subtitle_id, media_path, language_choice)

        if subtitle_path:
            self.print_subtitle_info(selected_sub)
            clean_subtitles.clean_ads(subtitle_path)
            if self.sync_choice:
                sync_subtitles.sync_subs_audio(media_path, subtitle_path)
            return True
        return False

    def process_media_list(self, media_path_list, language_choice):
        for media_path in media_path_list:
            path = Path(media_path)
            if path.is_dir():
                for file_path in path.glob("**/*"):
                    if file_path.suffix.lower() in [".mp4", ".mkv", ".avi"]:
                        self.process_media_file(str(file_path), language_choice)
            elif path.suffix.lower() in [".mp4", ".mkv", ".avi"]:
                self.process_media_file(str(path), language_choice)

    def print_subtitle_info(self, sub):
        table = Table(title="Subtitle Info")
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value", style="magenta")

        for key, value in sub.items():
            table.add_row(key, str(value))

        self.console.print(table)


if __name__ == "__main__":
    print("This is a module, import it in your project")
