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
from library.ai_subtitle_matcher import AISubtitleMatcher, SubtitleMatchResult

# ================================ Paths =============================
CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
TOKEN_STORAGE_FILE = os.path.join(CURRENT_DIR_PATH, "token.pkl")
# ====================================================================


class SubtitleUtils:
    console = Console()

    def __init__(self, use_ai=True):
        self.use_ai = use_ai
        self.console.print("[cyan]Initializing subtitle utilities...[/cyan]")
        if use_ai:
            try:
                self.console.print("[cyan]Initializing AI matcher...[/cyan]")
                self.ai_matcher = AISubtitleMatcher()
                self.console.print("[green]AI matcher initialized successfully[/green]")
            except Exception as e:
                self.console.print(
                    f"[yellow]Warning: AI matcher initialization failed: {e}. Falling back to traditional matching.[/yellow]"
                )
                self.use_ai = False
        else:
            self.console.print("[yellow]AI matching is disabled[/yellow]")

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
                return 0, 0, None  # Return traditional score, AI score, and AI details

            # Calculate traditional score
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

            return score, 0, None  # AI score will be calculated in batch
        except Exception as e:
            self.console.print(f"[bold red]Error scoring subtitle: {e}[/]")
            return 0, 0, None

    def sort_subtitle_list(self, subtitles_list, scores=None, ai_scores=None):
        try:
            sorted_subs = sorted(
                subtitles_list,
                key=lambda x: (
                    (
                        ai_scores.get(x["id"], 0) if ai_scores else 0
                    ),  # First sort by AI score
                    (
                        scores.get(x["id"], 0) if scores else 0
                    ),  # Then by traditional score
                    x["attributes"]["download_count"],  # Finally by download count
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

            scores = {}
            ai_scores = {}
            ai_details = {}

            if media_name:
                # Calculate traditional scores
                for sub in subtitles_list:
                    release_name = sub["attributes"]["release"]
                    hash_match = sub["attributes"]["moviehash_match"]
                    traditional_score, _, _ = self.score_subtitle(
                        release_name, media_name, hash_match
                    )
                    scores[sub["id"]] = traditional_score

                # Get AI scores in a single batch
                if self.use_ai:
                    try:
                        self.console.print("[cyan]Starting AI analysis...[/cyan]")
                        ai_results = self.ai_matcher.batch_analyze_subtitles(
                            media_name, subtitles_list
                        )
                        if not ai_results:
                            self.console.print(
                                "[yellow]AI analysis returned no results[/yellow]"
                            )
                        else:
                            self.console.print(
                                f"[green]AI analysis completed with {len(ai_results)} results[/green]"
                            )
                            for result in ai_results:
                                ai_scores[result.subtitle_id] = result.score
                                ai_details[result.subtitle_id] = {
                                    "reasoning": result.match_details.get(
                                        "reasoning", "No reasoning provided"
                                    ),
                                    **result.match_details,
                                }
                    except Exception as e:
                        self.console.print(
                            f"[yellow]Batch AI analysis failed: {str(e)}. Using traditional scores only.[/yellow]"
                        )
                        import traceback

                        self.console.print(
                            f"[red]Traceback: {traceback.format_exc()}[/red]"
                        )
                else:
                    self.console.print(
                        "[yellow]Skipping AI analysis (disabled)[/yellow]"
                    )

            sorted_subs = self.sort_subtitle_list(subtitles_list, scores, ai_scores)
            self.display_subtitle_options_opensubtitle(
                sorted_subs, scores, ai_scores, ai_details
            )

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
            import traceback

            self.console.print(f"[red]Traceback: {traceback.format_exc()}[/red]")
            return None

    def auto_select_subtitle(
        self, video_file_name, subtitles_result_list, backend="opensubtitles"
    ):
        try:
            max_score = -1
            best_subtitle = None
            scores = {}
            ai_scores = {}
            ai_details = {}

            standardized_subs = [
                self.standardize_subtitle_object(sub, backend)
                for sub in subtitles_result_list
            ]
            standardized_subs = [sub for sub in standardized_subs if sub]

            # Calculate traditional scores first
            for subtitle in standardized_subs:
                attrs = subtitle["attributes"]
                release_name = attrs["release"]
                hash_match = attrs.get("moviehash_match", False)
                traditional_score, _, _ = self.score_subtitle(
                    release_name, video_file_name, hash_match
                )
                scores[subtitle["id"]] = traditional_score

                if traditional_score > max_score:
                    max_score = traditional_score
                    best_subtitle = subtitle

            # Get AI scores in a single batch
            if self.use_ai:
                try:
                    ai_results = self.ai_matcher.batch_analyze_subtitles(
                        video_file_name, standardized_subs, backend
                    )
                    for result in ai_results:
                        ai_scores[result.subtitle_id] = result.score
                        ai_details[result.subtitle_id] = {
                            "reasoning": result.match_details.get("reasoning", ""),
                            **result.match_details,
                        }
                except Exception as e:
                    self.console.print(
                        f"[yellow]Batch AI analysis failed: {e}. Using traditional scores only.[/yellow]"
                    )

            sorted_subs = self.sort_subtitle_list(standardized_subs, scores)
            self.display_subtitle_options_opensubtitle(
                sorted_subs, scores, ai_scores, ai_details
            )
            return best_subtitle
        except Exception as e:
            self.console.print(f"[bold red]Error in auto subtitle selection: {e}[/]")
            return None

    def display_subtitle_options_opensubtitle(
        self, subtitles_list, scores=None, ai_scores=None, ai_details=None
    ):
        try:
            table = Table(title="Available Subtitles")

            table.add_column("Index", style="cyan", no_wrap=True)
            table.add_column("Subtitle ID", style="magenta")
            table.add_column("Release Name", style="magenta")
            table.add_column("Language", style="green")
            table.add_column("Downloads", style="yellow", justify="right")
            table.add_column("Hash Match", style="blue", justify="center")
            table.add_column("Machine Translated", style="red", justify="center")
            table.add_column("Match Score", style="cyan", justify="right")
            table.add_column("AI Score", style="green", justify="right")
            table.add_column("AI Reasoning", style="yellow", no_wrap=False)

            # Find max scores
            max_score = max(scores.values()) if scores else 0
            max_ai_score = max(ai_scores.values()) if ai_scores else 0

            for idx, sub in enumerate(subtitles_list, start=1):
                attrs = sub["attributes"]
                release = attrs["release"]
                language = attrs["language"]
                downloads = str(attrs["download_count"])
                hash_match = attrs.get("moviehash_match", False)
                machine_translated = attrs.get("machine_translated", False)

                sub_id = sub["id"]
                score = scores.get(sub_id, "") if scores else ""
                ai_score = ai_scores.get(sub_id, "") if ai_scores else ""

                # Format scores with color if they match max scores
                score_str = str(round(score, 2)) if score != "" else "-"
                if score and score == max_score:
                    score_str = f"[green]{score_str}[/]"

                ai_score_str = str(round(ai_score, 2)) if ai_score != "" else "-"
                if ai_score and ai_score == max_ai_score:
                    ai_score_str = f"[green]{ai_score_str}[/]"

                # Get AI reasoning
                reasoning = "-"
                if ai_details and sub_id in ai_details:
                    details = ai_details[sub_id]
                    if isinstance(details, dict):
                        reasoning = details.get("reasoning", "")
                        if len(reasoning) > 50:
                            reasoning = reasoning[:47] + "..."

                row = [
                    str(idx),
                    sub_id,
                    release,
                    language,
                    downloads,
                    "[green]o[/]" if hash_match else "[red]x[/]",
                    "[green]o[/]" if machine_translated else "[red]x[/]",
                    score_str,
                    ai_score_str,
                    reasoning,
                ]

                table.add_row(*row)

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
