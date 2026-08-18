# subtitle_utils.py

import os
import pickle
import re
import struct
import time
import unicodedata
from pathlib import Path

from rich.console import Console
from rich.table import Table
from thefuzz import fuzz

import library.clean_subtitles as clean_subtitles
import library.sync_subtitles as sync_subtitles

# ================================ Paths =============================
CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))
TOKEN_STORAGE_FILE = os.path.join(CURRENT_DIR_PATH, "token.pkl")
# ====================================================================

# Release naming drops apostrophes entirely ("Widow's Bay" -> "Widows Bay"),
# so they are removed rather than treated as token separators when matching
# or building provider search queries.
APOSTROPHE_RE = re.compile(r"['\u2018\u2019\u02BB\u02BC`\u00B4]")


class SubtitleUtils:
    console = Console()

    def __init__(self):
        pass

    def extract_subdl_subtitle_id(self, url):
        if not url:
            return None
        # v1: '/subtitle/3158195-3172856.zip'
        # v2: '/subtitle/3158195-3172856.zip?api_key=...'  (strip the query first)
        url = url.split("?")[0]
        parts = url.split("/")
        # 'and parts[2]' makes '/subtitle/' (empty id segment) return None, not ''
        if len(parts) >= 3 and parts[2]:
            return parts[2].replace(".zip", "")
        return None

    def extract_subsource_subtitle_id(self, subtitle):
        """Pull the numeric SubSource subtitle id from the raw API object.

        SubSource returns `subtitleId` (int) on the subtitle object directly, so we
        prefer that. The `link` field (e.g. '/subtitle/inception-2010/english/10215904')
        is used as a fallback, taking its last numeric path segment.
        """
        sub_id = subtitle.get("subtitleId")
        if sub_id is not None:
            return str(sub_id)
        link = subtitle.get("link", "") or ""
        link = link.split("?")[0].rstrip("/")
        if link:
            last = link.rsplit("/", 1)[-1]
            if last.isdigit():
                return last
        return None

    def standardize_subtitle_object(self, subtitle, backend="opensubtitles"):
        """Convert subtitle object to standard format"""
        try:
            match backend:
                case "opensubtitles":
                    return subtitle  # Already in desired format

                case "subdl":
                    url = subtitle.get("url")
                    if not url:
                        return None
                    return {
                        "id": self.extract_subdl_subtitle_id(url),
                        "attributes": {
                            "release": subtitle.get("release_name", ""),
                            "language": subtitle.get("language", "").lower(),
                            "download_count": 0,  # SubDL doesn't provide this
                            "ai_translated": False,  # SubDL doesn't provide this
                            "machine_translated": False,
                            "moviehash_match": False,
                            "url": url,
                            "hi": subtitle.get("hi", False),
                            "full_season": subtitle.get("full_season", False),
                            "author": subtitle.get("author", "Unknown"),
                            "season": subtitle.get("season"),
                            "episode": subtitle.get("episode"),
                            "unpack_files": subtitle.get("unpack_files", []),
                        },
                    }

                case "subsource":
                    sub_id = self.extract_subsource_subtitle_id(subtitle)
                    if sub_id is None:
                        return None
                    # releaseInfo is a list of release names; join them so the
                    # scorer can match against any of them.
                    release_info = subtitle.get("releaseInfo")
                    if isinstance(release_info, list):
                        release = " | ".join(r for r in release_info if r)
                    else:
                        release = release_info or ""
                    # SubSource languages are full names ("english"); keep verbatim
                    # but lower-cased for consistency with other backends.
                    language = (subtitle.get("language") or "").lower()
                    contributors = subtitle.get("contributors") or []
                    author = (
                        contributors[0].get("displayname", "Unknown")
                        if contributors and isinstance(contributors[0], dict)
                        else "Unknown"
                    )
                    prod = (subtitle.get("productionType") or "").lower()
                    return {
                        "id": sub_id,
                        "attributes": {
                            "release": release,
                            "language": language,
                            "download_count": subtitle.get("downloads", 0) or 0,
                            # Only "machine" productionType is considered AI/MT.
                            "ai_translated": prod == "machine",
                            "machine_translated": prod == "machine",
                            "moviehash_match": False,
                            # url is the human-readable link; the real download URL is
                            # built from the id by SubSource._download_url_for.
                            "url": subtitle.get("link", ""),
                            "hi": bool(subtitle.get("hearingImpaired")),
                            "full_season": False,
                            "author": author,
                            "season": None,
                            "episode": None,
                            "unpack_files": [],
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

    def clean_subtitles_strict(self, subtitle_path, ads_path=None):
        return clean_subtitles.clean_ads(
            subtitle_path,
            ads_file_path=ads_path,
        )

    def clean_subtitles(self, subtitle_path, ads_path=None):
        try:
            return self.clean_subtitles_strict(subtitle_path, ads_path)
        except Exception as e:
            self.console.print(f"[bold red]Error cleaning subtitles: {e}[/]")
            return False

    def sync_subtitles_strict(self, media_path, subtitle_path, on_output=None):
        return sync_subtitles.sync_subs_audio(
            media_path,
            subtitle_path,
            on_output=on_output,
        )

    def sync_subtitles(self, media_path, subtitle_path):
        try:
            return self.sync_subtitles_strict(media_path, subtitle_path)
        except Exception as e:
            self.console.print(f"[bold red]Error syncing subtitles: {e}[/]")
            return False

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
            fmt = f"<{65536 // bytesize}{longlongformat}"

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

            returnedhash = "{:016x}".format(filehash)
            return returnedhash

        except OSError as e:
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

    @staticmethod
    def normalize_media_name(value):
        """Drop apostrophes so queries match scene naming ("Widow's Bay" -> "Widows Bay")."""
        if not value:
            return value
        return APOSTROPHE_RE.sub("", str(value))

    @staticmethod
    def _normalize_match_text(value):
        text = unicodedata.normalize("NFKC", str(value or ""))
        text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
        text = APOSTROPHE_RE.sub("", text)
        text = text.replace("_", " ").replace(".", " ")
        text = re.sub(r"[^0-9A-Za-z]+", " ", text)
        return " ".join(text.lower().split())

    @staticmethod
    def _episode_evidence(media_name, *, allow_bare=False):
        """Return (season, episode, confidence) without forcing uncertain data."""
        if not media_name:
            return None, None, "none"

        text = unicodedata.normalize("NFKC", str(media_name))
        text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
        explicit_patterns = (
            r"\b[Ss](\d{1,2})[\s._-]*[Ee](?:[Pp])?[\s._-]*(\d{1,3})\b",
            r"\b(\d{1,2})[xX](\d{1,3})\b",
            (
                r"\b[Ss]eason[\s._-]*(\d{1,2})"
                r"[\s._-]*(?:[Ee]pisode|[Ee]p|[Ee])[\s._-]*(\d{1,3})\b"
            ),
        )
        for pattern in explicit_patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1)), int(match.group(2)), "high"

        labeled = re.search(
            r"\b(?:episode|ep|round|e)[\s._#-]*(\d{1,3})\b",
            text,
            re.IGNORECASE,
        )
        if labeled:
            return None, int(labeled.group(1)), "medium"

        if allow_bare:
            bare = re.search(
                r"(?:^|\s+-\s+|\s+)(\d{1,3})"
                r"(?=\s*(?:end\b|\[[^\]]*\]|\([^)]*\)|$))",
                text,
                re.IGNORECASE,
            )
            if bare:
                return None, int(bare.group(1)), "low"

        return None, None, "none"

    @classmethod
    def _title_hypotheses(cls, media_name, *, allow_bare=False):
        if not media_name:
            return []

        text = unicodedata.normalize("NFKC", str(media_name))
        text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
        text = re.sub(r"^\s*(?:\[[^\]]+\]\s*)+", "", text)
        boundaries = (
            r"\b[Ss]\d{1,2}[\s._-]*[Ee](?:[Pp])?[\s._-]*\d{1,3}\b",
            r"\b\d{1,2}[xX]\d{1,3}\b",
            r"\b[Ss]eason[\s._-]*\d{1,2}\b",
            r"\b(?:episode|ep|round|e)[\s._#-]*\d{1,3}\b",
        )
        prefixes = [
            text[: match.start()]
            for pattern in boundaries
            if (match := re.search(pattern, text, re.IGNORECASE))
        ]
        if allow_bare:
            bare = re.search(
                r"(?:^|\s+-\s+|\s+)\d{1,3}"
                r"(?=\s*(?:end\b|\[[^\]]*\]|\([^)]*\)|$))",
                text,
                re.IGNORECASE,
            )
            if bare:
                prefixes.append(text[: bare.start()])
        if not prefixes:
            prefixes.append(text)

        technical_tokens = {
            "aac",
            "ac3",
            "amzn",
            "arabic",
            "atmos",
            "avc",
            "bluray",
            "ddp",
            "dl",
            "dts",
            "dvd",
            "eac3",
            "flac",
            "h264",
            "h265",
            "hdtv",
            "hdrip",
            "hevc",
            "netflix",
            "proper",
            "remux",
            "webrip",
            "web",
            "webdl",
            "x264",
            "x265",
        }
        hypotheses = []
        for prefix in prefixes:
            normalized = cls._normalize_match_text(prefix)
            normalized = re.sub(r"\b(?:19|20)\d{2}\b", " ", normalized)
            tokens = [
                token
                for token in normalized.split()
                if token not in technical_tokens
                and not re.fullmatch(r"\d{3,4}p", token)
                and not re.fullmatch(r"\d+bit", token)
                and not re.fullmatch(r"\d+(?:\.\d+)?ch", token)
            ]
            hypothesis = " ".join(tokens).strip()
            if hypothesis and hypothesis not in hypotheses:
                hypotheses.append(hypothesis)
        return hypotheses

    @staticmethod
    def _informative_title_tokens(title):
        stopwords = {
            "a",
            "an",
            "and",
            "at",
            "for",
            "from",
            "in",
            "of",
            "on",
            "the",
            "to",
        }
        return {token for token in title.split() if token not in stopwords}

    @classmethod
    def _title_match_score(cls, source_name, target_name, *, source_allow_bare=False):
        source_titles = cls._title_hypotheses(
            source_name,
            allow_bare=source_allow_bare,
        )
        target_titles = cls._title_hypotheses(target_name)
        best = 0.0
        for source_title in source_titles:
            source_tokens = cls._informative_title_tokens(source_title)
            if not source_tokens:
                continue
            for target_title in target_titles:
                target_tokens = cls._informative_title_tokens(target_title)
                if not target_tokens:
                    continue
                if source_tokens == target_tokens:
                    best = max(best, 55.0)
                    continue
                if source_tokens <= target_tokens or target_tokens <= source_tokens:
                    best = max(best, 53.0)
                    continue

                shared = source_tokens & target_tokens
                if len(shared) >= 2:
                    coverage = len(shared) / min(
                        len(source_tokens),
                        len(target_tokens),
                    )
                    best = max(best, 20.0 + 25.0 * coverage)

                similarity = fuzz.token_set_ratio(
                    " ".join(sorted(source_tokens)),
                    " ".join(sorted(target_tokens)),
                )
                if similarity >= 90:
                    best = max(best, 42.0)
                elif similarity >= 80 and shared:
                    best = max(best, 30.0)
        return min(best, 55.0)

    @classmethod
    def _technical_match_score(cls, source_name, target_name):
        terms = {
            "720p",
            "1080p",
            "2160p",
            "4k",
            "amzn",
            "bluray",
            "h264",
            "h265",
            "hdtv",
            "hdrip",
            "hevc",
            "netflix",
            "web",
            "webdl",
            "webrip",
            "x264",
            "x265",
        }
        source_tokens = set(cls._normalize_match_text(source_name).split())
        target_tokens = set(cls._normalize_match_text(target_name).split())
        return min(10.0, 2.0 * len(source_tokens & target_tokens & terms))

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

            # Check for Mr. or Ms. in the title and create alternate versions
            mr_match = re.search(r"Mr\.\s+(\w+)", title, re.IGNORECASE)
            ms_match = re.search(r"Ms\.\s+(\w+)", title, re.IGNORECASE)

            if mr_match:
                alternate_title = re.sub(r"Mr\.\s+", "", title, flags=re.IGNORECASE)
                title_with_mister = re.sub(
                    r"Mr\.", "Mister", title, flags=re.IGNORECASE
                )
                formats.extend([alternate_title, title_with_mister])

            if ms_match:
                alternate_title = re.sub(r"Ms\.\s+", "", title, flags=re.IGNORECASE)
                title_with_miss = re.sub(r"Ms\.", "Miss", title, flags=re.IGNORECASE)
                formats.extend([alternate_title, title_with_miss])

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
                        f"{title} E{episode:02d}",
                        f"{title.lower().replace(' ', '.')}.E{episode:02d}",
                    ]
                )

            # Web-style format
            formats.append(
                f"{title.lower().replace(' ', '-')}-episode-{season}-{episode}"
            )

            # If we found Mr. or Ms. alternates, also add their variations with season/episode
            if mr_match or ms_match:
                for alt_title in formats[
                    :
                ]:  # Create a copy of the list to iterate over
                    if mr_match:
                        alt_without_mr = re.sub(
                            r"Mr\.\s+", "", alt_title, flags=re.IGNORECASE
                        )
                        alt_with_mister = re.sub(
                            r"Mr\.", "Mister", alt_title, flags=re.IGNORECASE
                        )
                        formats.extend([alt_without_mr, alt_with_mister])
                    if ms_match:
                        alt_without_ms = re.sub(
                            r"Ms\.\s+", "", alt_title, flags=re.IGNORECASE
                        )
                        alt_with_miss = re.sub(
                            r"Ms\.", "Miss", alt_title, flags=re.IGNORECASE
                        )
                        formats.extend([alt_without_ms, alt_with_miss])

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
        """Score independent filename evidence without requiring a perfect parse."""
        try:
            if not subtitle_release_name or not video_file_name:
                return 0
            if hash_match:
                return 100.0

            target_season, target_episode, target_confidence = (
                self._episode_evidence(video_file_name)
            )
            allow_bare = target_confidence in {"high", "medium"}
            source_season, source_episode, source_confidence = (
                self._episode_evidence(
                    subtitle_release_name,
                    allow_bare=allow_bare,
                )
            )
            title_score = self._title_match_score(
                subtitle_release_name,
                video_file_name,
                source_allow_bare=allow_bare,
            )
            title_plausible = title_score >= 25
            score = title_score

            episode_agrees = (
                source_episode is not None
                and target_episode is not None
                and source_episode == target_episode
            )
            if episode_agrees:
                episode_points = {
                    "high": 20.0,
                    "medium": 14.0,
                    "low": 8.0,
                }.get(source_confidence, 0.0)
                score += episode_points if title_plausible else min(6.0, episode_points)
            elif (
                title_plausible
                and source_episode is not None
                and target_episode is not None
                and source_confidence in {"high", "medium"}
            ):
                score -= 15.0

            if source_season is not None and target_season is not None:
                if source_season == target_season:
                    score += 10.0 if title_plausible else 3.0
                elif title_plausible and source_confidence == "high":
                    score -= 12.0

            if title_plausible and episode_agrees:
                score += 10.0 if source_confidence != "low" else 6.0

            technical_score = self._technical_match_score(
                subtitle_release_name,
                video_file_name,
            )
            score += technical_score if title_plausible else min(2.0, technical_score)
            if not title_plausible:
                score = min(score, 15.0)
            return max(0.0, min(100.0, score))
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
            if path.is_file() and path.suffix.lower() not in [
                ".mp4",
                ".mkv",
                ".avi",
            ]:
                return False
            return not path.is_dir()
        except Exception as e:
            self.console.print(f"[bold red]Error checking media file: {e}[/]")
            return False


if __name__ == "__main__":
    print("This is a module to be imported")
