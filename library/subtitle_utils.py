# subtitle_utils.py

import re
import os
import struct
from pathlib import Path
from thefuzz import fuzz
from rich.console import Console
from rich.table import Table
import pickle
import time
import library.clean_subtitles as clean_subtitles
import library.sync_subtitles as sync_subtitles

# ================================ Paths =============================
CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
TOKEN_STORAGE_FILE = os.path.join(CURRENT_DIR_PATH, "token.pkl")
# ====================================================================


class SubtitleUtils:
    console = Console()

    def __init__(self):
        pass

    def extract_subdl_subtitle_id(self, url):
        if not url:
            return None
        # url format is '/subtitle/3158195-3172856.zip'
        parts = url.split("/")
        if len(parts) >= 3:
            return parts[2].replace(".zip", "")
        return None

    def standardize_subtitle_object(self, subtitle, backend="opensubtitles"):
        """Convert subtitle object to standard format"""
        try:
            match backend:
                case "opensubtitles":
                    return subtitle  # Already in desired format

                case "subdl":
                    return {
                        "id": self.extract_subdl_subtitle_id(subtitle.get("url", "")),
                        "attributes": {
                            "release": subtitle.get("release_name", ""),
                            "language": subtitle.get("language", "").lower(),
                            "download_count": 0,  # SubDL doesn't provide this
                            "ai_translated": False,  # SubDL doesn't provide this
                            "machine_translated": False,
                            "moviehash_match": False,
                            "url": subtitle.get("url", ""),
                            "hi": subtitle.get("hi", False),
                            "full_season": subtitle.get("full_season", False),
                            "author": subtitle.get("author", "Unknown"),
                            "season": subtitle.get("season"),
                            "episode": subtitle.get("episode"),
                        },
                    }
        except Exception as e:
            self.console.print(f"[bold red]Error standardizing subtitle object: {e}[/]")
            return None

    def save_token(self, token):
        try:
            # Create a dictionary to store the token and the timestamp
            data = {
                "token": token,
                "timestamp": time.time(),
            }  # Store the current timestamp

            # Save the data to a pickle file
            with open(TOKEN_STORAGE_FILE, "wb") as file:
                pickle.dump(data, file)
        except Exception as e:
            self.console.print(f"[bold red]Error saving token: {e}[/]")

    def read_token(self):
        try:
            # Check if the pickle file exists
            if os.path.exists(TOKEN_STORAGE_FILE):
                with open(TOKEN_STORAGE_FILE, "rb") as file:
                    data = pickle.load(file)

                # Get the timestamp and current time
                timestamp = data["timestamp"]
                current_time = time.time()

                # Check if the token was saved less than 23 hours ago
                if current_time - timestamp < 23 * 3600:  # 23 hours in seconds
                    return data["token"]

            # If the file doesn't exist or the token is too old, return False
            return False
        except (FileNotFoundError, EOFError, pickle.UnpicklingError) as e:
            self.console.print(f"[bold yellow]Warning: Error reading token: {e}[/]")
            return False
        except Exception as e:
            self.console.print(f"[bold red]Error reading token: {e}[/]")
            return False

    def clean_subtitles(self, subtitle_path):
        try:
            clean_subtitles.clean_ads(subtitle_path)
        except Exception as e:
            self.console.print(f"[bold red]Error cleaning subtitles: {e}[/]")

    def sync_subtitles(self, media_path, subtitle_path):
        try:
            sync_subtitles.sync_subs_audio(media_path, subtitle_path)
        except Exception as e:
            self.console.print(f"[bold red]Error syncing subtitles: {e}[/]")

    def sort_list_of_dicts_by_key(self, input_list, key_to_sort_by):
        try:
            # Create an empty set to store unique 'id' values
            unique_ids = set()

            # Initialize an empty list to store unique items
            unique_data = []

            # Iterate through the list of dictionaries
            for item in input_list:
                item_id = item["id"]

                # Check if the 'id' is not already in the set of unique_ids
                if item_id not in unique_ids:
                    unique_ids.add(item_id)
                    unique_data.append(item)

            sorted_list = sorted(
                unique_data, key=lambda x: x["attributes"][key_to_sort_by], reverse=True
            )
            return sorted_list
        except (KeyError, TypeError) as e:
            self.console.print(f"[bold red]Error sorting list of dictionaries: {e}[/]")
            return []
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error sorting list: {e}[/]")
            return []

    def hashFile(self, media_path):
        """Produce a hash for a video file: size + 64bit chksum of the first and
        last 64k (even if they overlap because the file is smaller than 128k)"""
        try:
            longlongformat = "Q"  # unsigned long long little endian
            bytesize = struct.calcsize(longlongformat)
            fmt = "<%d%s" % (65536 // bytesize, longlongformat)

            with open(media_path, "rb") as f:
                filesize = os.fstat(f.fileno()).st_size
                filehash = filesize

                if filesize < 65536 * 2:
                    self.console.print(
                        f"[bold red]Error: File size error while generating hash for {media_path}[/]"
                    )
                    return "SizeError"

                buf = f.read(65536)
                longlongs = struct.unpack(fmt, buf)
                filehash += sum(longlongs)

                f.seek(-65536, os.SEEK_END)  # size is always > 131072
                buf = f.read(65536)
                longlongs = struct.unpack(fmt, buf)
                filehash += sum(longlongs)
                filehash &= 0xFFFFFFFFFFFFFFFF

            returnedhash = "%016x" % filehash
            return returnedhash

        except (IOError, OSError) as e:
            self.console.print(
                f"[bold red]Error: I/O error while generating hash for {media_path}: {e}[/]"
            )
            return "IOError"
        except Exception as e:
            self.console.print(
                f"[bold red]Unexpected error generating hash for {media_path}: {e}[/]"
            )
            return None

    def extract_season_and_episode(self, media_name):
        """Extract season and episode numbers from media name using multiple formats"""
        if not media_name:
            return None, None

        # Normalize input string
        media_name = media_name.replace("_", " ").replace(".", " ")

        patterns = [
            # Standard formats
            r"[Ss](\d{1,2})[Ee](\d{1,2})",  # S01E02, s1e2
            r"[Ss](\d{1,2})\s*-\s*[Ee](\d{1,2})",  # S01-E02
            r"(\d{1,2})x(\d{1,2})",  # 1x02
            r"(?:Episode|Ep)\s*(\d{1,2})",  # Episode 2, Ep 2 (implies S1)
            r"[Ee](\d{1,2})",  # E02 (implies S1)
            r"[Ee][Pp](\d{1,2})",  # EP02 (implies S1)
            # More specific formats
            r"\s-\s*[Ss](\d{1,2})[Ee](\d{1,2})",  # - S01E02
            r"[Ss]eason\s*(\d{1,2})\s*[Ee]pisode\s*(\d{1,2})",  # Season 1 Episode 2
            r"[Ss](\d{1,2})\s*[Ee]p\s*(\d{1,2})",  # S01 Ep 02
            # Date-based formats for daily shows
            r"(\d{4})\.(\d{2}\.\d{2})",  # 2024.01.02
            r"(\d{4})-(\d{2}-\d{2})",  # 2024-01-02
            # Special formats
            r"Episode\s#(\d+)\.(\d+)",  # Episode #1.2
            r"E(\d{1,2})",  # E1 (implies S1)
        ]

        for pattern in patterns:
            match = re.search(pattern, media_name, re.IGNORECASE)
            if match:
                groups = match.groups()

                # Handle special cases
                if len(groups) == 1:  # Single number patterns imply Season 1
                    return 1, int(groups[0])

                if len(groups) == 2:
                    season = groups[0]
                    episode = groups[1]

                    # Handle date-based formats
                    if len(season) == 4:  # Year-based format
                        return 1, int(episode.replace(".", "").replace("-", ""))

                    try:
                        return int(season), int(episode)
                    except (ValueError, TypeError):
                        continue

        return None, None

    def get_alternate_names(self, media_name):
        """Generate alternate name formats for the media"""
        try:
            if not media_name:
                return None

            # First get season/episode since we have robust parsing for that
            season, episode = self.extract_season_and_episode(media_name)
            if not episode:  # Need at least episode number
                return None

            # Extract title and year, now knowing where season/episode info is
            # Remove common episode/season patterns
            clean_name = media_name
            patterns_to_remove = [
                r"[Ss]\d{1,2}[Ee]\d{1,2}",
                r"[Ss]\d{1,2}\s*-\s*[Ee]\d{1,2}",
                r"\d{1,2}x\d{1,2}",
                r"(?:Episode|Ep)\s*\d{1,2}",
                r"[Ee]\d{1,2}",
                r"[Ee][Pp]\d{1,2}",
            ]

            for pattern in patterns_to_remove:
                clean_name = re.sub(pattern, "", clean_name, flags=re.IGNORECASE)

            # Extract year if present
            year_match = re.search(r"\((\d{4})\)", clean_name)
            year = year_match.group(1) if year_match else ""
            if year:
                clean_name = re.sub(r"\s*\(\d{4}\)\s*", " ", clean_name)

            # Clean up title
            title = clean_name.strip().strip(".-_ ")

            # Generate alternate formats
            formats = []

            # Basic formats
            if season:
                formats.extend(
                    [
                        f"{title} {season}x{episode:02d}",
                        f"{title} S{season:02d}E{episode:02d}",
                        f"{title} Episode #{season}.{episode:02d}",
                    ]
                )

            # Add year if available
            if year:
                formats.extend(
                    [
                        f"{title} ({year}) - S{season:02d}E{episode:02d}",
                        f"{title} ({year}) {season}x{episode:02d}",
                    ]
                )

            # Special format for season 1
            if season == 1:
                formats.extend(
                    [
                        f"{title.replace(' ', '.')}-E{episode}",
                        f"{title.lower().replace(' ', '.')}.E{episode:02d}",
                    ]
                )

            # Web-style format
            formats.append(
                f"{title.lower().replace(' ', '-')}-episode-{season}-{episode}"
            )

            return list(
                dict.fromkeys(formats)
            )  # Remove duplicates while preserving order
        except Exception as e:
            self.console.print(f"[bold red]Error generating alternate names: {e}[/]")
            return None

    def normalize_score(self, score):
        """
        Normalize subtitle matching score to 0-100 range

        Args:
            score (float): Raw score from matching algorithm

        Returns:
            float: Normalized score between 0-100
        """
        try:
            # Calculate actual max score based on current scoring system:
            # 100 (hash match)
            # + 55 (series name match)
            # + 45 (quality terms 9 × 5)
            # + Word matches (variable but capped implicitly)
            # + 100 (perfect fuzzy match)
            # + 50 (episode match)
            # + 25 (season match)
            # + 50 (quality indicators 5 × 10)
            # + 75 (perfect match bonus)
            MAX_POSSIBLE_SCORE = 500

            # Normalize using max possible score
            normalized = (score / MAX_POSSIBLE_SCORE) * 100

            # Clamp between 0-100
            return max(0, min(100, normalized))
        except Exception as e:
            self.console.print(f"[bold red]Error normalizing score: {e}[/]")
            return 0

    def score_subtitle(self, subtitle_release_name, video_file_name, hash_match=False):
        """Score subtitle match against video filename"""
        try:
            score = 0

            if not subtitle_release_name or not video_file_name:
                return 0

            # Hash match is strongest indicator
            if hash_match:
                score += 100

            # Normalize filenames
            video_file_clean = re.sub(
                r"[\-\_\[\]\(\)\{\}\s\.]+", " ", video_file_name
            ).lower()
            sub_file_clean = re.sub(
                r"[\-\_\[\]\(\)\{\}\s\.]+", " ", subtitle_release_name
            ).lower()

            # Extract series name
            series_name = re.split(
                r"s\d{1,2}e\d{1,2}|season|episode|\d{3,4}p|\b\d{4}\b", video_file_clean
            )[0].strip()

            # Series name match (max 55)
            if series_name and series_name in sub_file_clean:
                score += 55

            # Quality term matches (max 45: 9 terms × 5 points)
            quality_score = 0
            quality_terms = [
                "hdtv",
                "720p",
                "1080p",
                "2160p",
                "4k",
                "webdl",
                "webrip",
                "bluray",
                "hdrip",
            ]
            for term in quality_terms:
                if term in video_file_clean and term in sub_file_clean:
                    quality_score += 5
            score += min(quality_score, 45)

            # Handle implicit season 1
            implicit_s1_patterns = [
                r"\.e(\d{1,2})\.",  # .E01.
                r"\.ep(\d{1,2})\.",  # .EP01.
                r"episode\.(\d{1,2})",  # episode.01
            ]
            video_is_implicit_s1 = any(
                re.search(pattern, video_file_clean) for pattern in implicit_s1_patterns
            )
            sub_is_implicit_s1 = any(
                re.search(pattern, sub_file_clean) for pattern in implicit_s1_patterns
            )

            # Word matching (max 30)
            word_match_score = 0
            video_file_parts = re.split(r"[.\s_-]", video_file_clean)
            sub_file_parts = re.split(r"[.\s_-]", sub_file_clean)
            series_name_parts = video_file_parts[:3]

            for sub_part in sub_file_parts:
                for file_part in video_file_parts:
                    if sub_part == file_part:
                        if file_part in series_name_parts:
                            word_match_score += 5
                        else:
                            word_match_score += 1
            score += min(word_match_score, 30)

            # Fuzzy matching (max 100)
            similarity = fuzz.token_sort_ratio(video_file_clean, sub_file_clean)
            if similarity == 100:
                score += 100
            elif similarity > 90:
                score += 50
            elif similarity > 70:
                score += 35
            elif similarity > 40:
                score += 10

            # Episode/Season matching
            season_source, episode_source = self.extract_season_and_episode(
                video_file_name
            )
            season_target, episode_target = self.extract_season_and_episode(
                subtitle_release_name
            )

            if video_is_implicit_s1 and sub_is_implicit_s1:
                season_source = season_target = 1

            # Episode match (50 points)
            if episode_source and episode_target and episode_source == episode_target:
                score += 50

            # Season match (25 points)
            if season_source and season_target and season_source == season_target:
                score += 25
            elif video_is_implicit_s1 and sub_is_implicit_s1:
                score += 25

            # Quality indicators (max 50: 5 terms × 10 points)
            quality_indicator_score = 0
            quality_indicators = ["hdtv", "720p", "1080p", "webdl", "webrip"]
            for term in quality_indicators:
                if term in video_file_clean and term in sub_file_clean:
                    quality_indicator_score += 10
            score += min(quality_indicator_score, 50)

            # Perfect match bonus (75 points)
            if (
                (
                    (season_source == season_target)
                    or (video_is_implicit_s1 and sub_is_implicit_s1)
                )
                and episode_source
                and episode_target
                and episode_source == episode_target
            ):
                score += 75

            normalized_score = self.normalize_score(score)
            return normalized_score
        except Exception as e:
            self.console.print(f"[bold red]Error scoring subtitle: {e}[/]")
            return 0

    def sort_subtitle_list(self, subtitles_list, scores=None):
        try:
            sorted_subs = sorted(
                subtitles_list,
                key=lambda x: (
                    scores.get(x["id"], 0)
                    if scores
                    else x["attributes"]["download_count"]
                ),
                reverse=True,
            )

            return sorted_subs
        except (KeyError, TypeError) as e:
            self.console.print(f"[bold red]Error sorting subtitle list: {e}[/]")
            return []
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error sorting subtitles: {e}[/]")
            return []

    def manual_select_subtitle(self, media_name, subtitles_list):
        try:
            if subtitles_list is None:
                return None

            scores = None
            if media_name:
                scores = {}
                for sub in subtitles_list:
                    release_name = sub["attributes"]["release"]
                    hash_match = sub["attributes"]["moviehash_match"]
                    score = self.score_subtitle(release_name, media_name, hash_match)
                    scores[sub["id"]] = score

            sorted_subs = self.sort_subtitle_list(subtitles_list, scores)
            self.display_subtitle_options_opensubtitle(sorted_subs, scores)

            while True:
                try:
                    choice = int(
                        self.console.input(
                            "[yellow]Enter the index of the subtitle you want to download (0 to cancel): [/yellow]"
                        )
                    )
                    if choice == 0:
                        return None
                    if 1 <= choice <= len(sorted_subs):
                        return sorted_subs[choice - 1]
                    self.console.print("[red]Invalid index. Please try again.[/red]")
                except ValueError:
                    self.console.print("[red]Please enter a valid number.[/red]")
        except Exception as e:
            self.console.print(f"[bold red]Error in manual subtitle selection: {e}[/]")
            return None

    def auto_select_subtitle(self, video_file_name, subtitles_result_list):
        try:
            max_score = -1
            best_subtitle = None
            scores = {}

            for subtitle in subtitles_result_list:
                release_name = subtitle["attributes"]["release"]
                hash_match = subtitle["attributes"]["moviehash_match"]
                score = self.score_subtitle(release_name, video_file_name, hash_match)
                scores[subtitle["id"]] = score

                if score > max_score:
                    max_score = score
                    best_subtitle = subtitle

            sorted_subs = self.sort_subtitle_list(subtitles_result_list, scores)
            self.display_subtitle_options_opensubtitle(sorted_subs, scores)
            return best_subtitle
        except Exception as e:
            self.console.print(f"[bold red]Error in auto subtitle selection: {e}[/]")
            return None

    def display_subtitle_options_opensubtitle(self, subtitles_list, scores=None):
        try:
            table = Table(title="Available Subtitles")

            table.add_column("Index", style="cyan", no_wrap=True)
            table.add_column("Subtitle ID", style="magenta")
            table.add_column("Release Name", style="magenta")
            table.add_column("Language", style="green")
            table.add_column("Downloads", style="yellow", justify="right")
            table.add_column("Hash Match", style="blue", justify="center")
            table.add_column("Machine Translated", style="red", justify="center")
            table.add_column("Auto Selection Score", style="cyan", justify="right")

            # Find max score if scores exist
            max_score = max(scores.values()) if scores else 0

            for idx, sub in enumerate(subtitles_list, start=1):
                attrs = sub["attributes"]
                sub_id = sub["id"]
                score = scores.get(sub_id, "") if scores else ""

                # Format score with color if it matches max score
                score_str = str(score) if score else "-"
                if score and score == max_score:
                    score_str = f"[green]{score_str}[/]"

                table.add_row(
                    str(idx),
                    sub_id,
                    attrs["release"],
                    attrs["language"],
                    str(attrs["download_count"]),
                    (
                        "[green]o[/]"
                        if attrs.get("moviehash_match", False)
                        else "[red]x[/]"
                    ),
                    "[green]o[/]" if attrs["machine_translated"] else "[red]x[/]",
                    score_str,
                )

            self.console.print(table)
        except Exception as e:
            self.console.print(f"[bold red]Error displaying subtitle options: {e}[/]")

    def ask_sync_subtitles(self):
        """Prompt user whether to sync subtitles"""
        while True:
            choice = self.console.input(
                "[yellow]Do you want to sync subtitles with video? (y/n): [/yellow]"
            ).lower()
            if choice in ["y", "yes"]:
                return True
            elif choice in ["n", "no"]:
                return False
            self.console.print("[red]Please enter y or n[/red]")

    def check_if_media_file(self, media_path):
        try:
            path = Path(media_path)
            if not path.exists():
                return False
            # if path is file
            if path.is_file():
                # check if file is video file
                if path.suffix.lower() not in [".mp4", ".mkv", ".avi"]:
                    return False
            if path.is_dir():
                return False
            return True
        except Exception as e:
            self.console.print(f"[bold red]Error checking media file: {e}[/]")
            return False


if __name__ == "__main__":
    print("This is a module to be imported")
