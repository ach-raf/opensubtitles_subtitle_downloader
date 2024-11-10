# opensubtitles.py
import os
import struct
import requests
import json
import re

import library.clean_subtitles as clean_subtitles
import library.sync_subtitles as sync_subtitles
import library.utils as utils

from pathlib import Path
from thefuzz import fuzz

from rich.console import Console
from rich.table import Table
from rich import print as rprint


class OpenSubtitles:

    def __init__(
        self,
        username,
        password,
        api_key,
        user_agent,
        skip_sync_choice=False,
        hearing_impaired=False,
        auto_select=True,
    ):
        # self.nlp = spacy.load("en_core_web_md")
        self.username = username
        self.password = password
        self.api_key = api_key
        self.user_agent = user_agent
        self.token = self.login()
        self.sync_choice = skip_sync_choice
        self.hearing_impaired = hearing_impaired
        self.auto_select = auto_select
        self.console = Console()

    def sort_list_of_dicts_by_key(self, input_list, key_to_sort_by):
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

    def hashFile(self, media_path):
        """Produce a hash for a video file: size + 64bit chksum of the first and
        last 64k (even if they overlap because the file is smaller than 128k)"""
        try:
            longlongformat = "Q"  # unsigned long long little endian
            bytesize = struct.calcsize(longlongformat)
            fmt = "<%d%s" % (65536 // bytesize, longlongformat)

            f = open(media_path, "rb")

            filesize = os.fstat(f.fileno()).st_size
            filehash = filesize

            if filesize < 65536 * 2:
                print(
                    "error",
                    "File size error!",
                    "File size error while generating hash for this file:\n<i>"
                    + media_path
                    + "</i>",
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

            f.close()
            returnedhash = "%016x" % filehash
            return returnedhash

        except IOError:
            print(
                "error",
                "I/O error!",
                "Input/Output error while generating hash for this file:\n<i>"
                + media_path
                + "</i>",
            )
            return "IOError"

    def login(self):
        token = utils.read_token()
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
        response = requests.post(url, headers=headers, json=payload)
        token = None
        try:
            token = response.json()["token"]
            utils.save_token(token)
            return token
        except KeyError as e:
            print(f"Error: {response.json()}, {e}")
            exit()
        except json.decoder.JSONDecodeError as e:
            print(f"Error: {response.text}, {e}")
            exit()

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
            # "order_by": "votes",
            # "order_direction": "desc",
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
        # print(params)
        response = requests.get(url, headers=headers, params=params)
        try:
            response.raise_for_status()
            return response.json()["data"]
        except requests.exceptions.HTTPError as e:
            print(f"Error: {response}, {e}")
            return None

    def extract_season_and_episode(self, media_name):
        regex_pattern = r"S(\d{1,2})E(\d{1,2})|(\d+)x(\d+)| - S(\d{1,2})E(\d{1,2})|S(\d+)\s*-\s*(\d+)"
        regex = re.compile(regex_pattern)

        match = regex.search(media_name)
        if match:
            season = (
                match.group(1) or match.group(3) or match.group(5) or match.group(7)
            )
            episode = (
                match.group(2) or match.group(4) or match.group(6) or match.group(8)
            )

            if season and episode:
                season_number = int(season)
                episode_number = int(episode)
                return season_number, episode_number
            if season:
                season_number = int(season)
                return season_number, None
            if episode:
                episode_number = int(episode)
                return None, episode_number

        return None, None

    def extract_episode_info(self, input_string):
        # Split the input string by spaces, hyphens, and periods
        parts = re.split(r"[ \-\.]+", input_string)

        # Initialize variables to store title, season, and episode
        title = ""
        season = ""
        episode = ""

        for part in parts:
            # Check if the part represents a season and episode
            if re.match(r"S\d{2}E\d{2}", part):
                season_episode = re.findall(r"\d{2}", part)
                if len(season_episode) == 2:
                    season, episode = season_episode
            else:
                # If not a season and episode, add it to the title
                title += part + " "

        # Remove trailing spaces from title
        title = title.strip()

        # If season and episode are found, format the extracted information
        if season and episode:
            formatted_info = f"{title} {season}x{episode}"
            return formatted_info

        return None

    def get_episode_info_new(self, input_string):
        # Define a regular expression pattern to capture season and episode information
        pattern = r"S(\d{2})E(\d{2})"

        # Search for the pattern in the input string
        match = re.search(pattern, input_string)

        if match:
            # Extract season and episode numbers
            season = match.group(1)
            episode = match.group(2)

            # Split the input string by the season and episode pattern
            parts = re.split(pattern, input_string)

            if len(parts) >= 2:
                title = parts[0].strip()
            else:
                title = input_string.strip()

            # Format the extracted information
            formatted_info = f"{title} {season}x{episode}"

            return formatted_info

        return None

    def get_episode_info(self, media_name):
        # Define a regular expression pattern to match the required information
        patterns = [
            r"([^()]+)\s\((\d{4})\)\s-\sS(\d{2})E(\d{2})",  # Format 1
            r'([^"]+)"\sEpisode\s#(\d+\.\d+)\sS(\d{2})E(\d{2})',  # Format 2
            r"([^()]+)\s-\s(\d{2})x(\d{2})\s-\s([^()]+)",  # Format 3
            r"([^()]+)\sS(\d{2})E(\d{2})",  # Format 4
        ]

        for pattern in patterns:
            # Use regex to search for the pattern in the input string
            match = re.search(pattern, media_name)

            if match:
                # Extract the relevant groups from the match
                title = match.group(1) if match.group(1) else ""
                year = match.group(2) if match.group(2) else ""
                season = match.group(3) if match.group(3) else ""
                episode = match.group(4) if match.group(4) else ""
                return title, year, season, episode
        return None

    def get_alternate_names(self, media_name):
        # Define a regular expression pattern to match the required information
        pattern = r"([^()]+)\s\((\d{4})\)\s-\sS(\d{2})E(\d{2})"

        # Use regex to search for the pattern in the input string
        match = re.search(pattern, media_name)

        if match:
            # Extract the relevant groups from the match
            title = match.group(1)
            year = match.group(2)
            season = match.group(3)
            episode = match.group(4)

            # Format the extracted information
            formatted_info_1 = f"{title} {season}x{episode}"
            formatted_info_2 = f"{title} S{season.zfill(2)}E{episode.zfill(2)}"
            formatted_info_3 = f"{title} Episode #{season}.{episode}"
            # add format, the-uncanny-counter-episode-2-1
            formatted_info_4 = f"{title.replace(' ', '-').lower()}-episode-{int(season)}-{int(episode)}"

            result = [
                formatted_info_1,
                formatted_info_2,
                formatted_info_3,
                formatted_info_4,
            ]

            return result
        else:
            return None

    def auto_select_subtitle(self, video_file_name, subtitles_result_list):
        video_file_parts = re.split(
            r"[-\s_]",
            video_file_name.replace("-", ".")
            .replace(" ", ".")
            .replace("_", ".")
            .lower(),
        )

        max_score = -1
        best_subtitle = None
        best_similarity = 0

        for subtitle in subtitles_result_list:
            score = 0
            release_name = subtitle["attributes"]["release"]
            sub_file_parts = re.split(
                r"[-\s_]",
                release_name.replace("-", ".")
                .replace(" ", ".")
                .replace("_", ".")
                .lower(),
            )

            # Check for moviehash match
            if subtitle["attributes"]["moviehash_match"]:
                score += 100
                best_subtitle = subtitle
                break

            # Score for filename match
            for sub_part in sub_file_parts:
                for file_part in video_file_parts:
                    if sub_part == file_part:
                        score += 1

            # Compare video filename and subtitle name using fuzzy string matching
            similarity = fuzz.token_sort_ratio(
                video_file_name.lower(), release_name.lower()
            )
            if similarity == 100:
                score += 100
            elif similarity > 90:
                score += 50
            elif similarity > 70:
                score += 35
            elif similarity > 40:
                score += 10

            if similarity > best_similarity:
                best_similarity = similarity

            # Check for season and episode match
            season_source, episode_source = self.extract_season_and_episode(
                video_file_name
            )
            season_target, episode_target = self.extract_season_and_episode(
                release_name
            )
            if season_source and episode_source and season_target and episode_target:
                if season_source == season_target and episode_source == episode_target:
                    score += 80

            if score > max_score:
                max_score = score
                best_subtitle = subtitle

        return best_subtitle

    def display_subtitle_options(self, subtitles_list):
        table = Table(title="Available Subtitles")

        table.add_column("Index", style="cyan", no_wrap=True)
        table.add_column("Release Name", style="magenta")
        table.add_column("Language", style="green")
        table.add_column("Downloads", style="yellow", justify="right")
        table.add_column("Hash Match", style="blue", justify="center")
        table.add_column("Machine Translated", style="red", justify="center")

        for idx, sub in enumerate(subtitles_list, start=1):
            attrs = sub["attributes"]
            table.add_row(
                str(idx),
                attrs["release"],
                attrs["language"],
                str(attrs["download_count"]),
                "[green]o[/]" if attrs.get("moviehash_match", False) else "[red]x[/]",
                "[green]o[/]" if attrs["machine_translated"] else "[red]x[/]",
            )

        self.console.print(table)

    def manual_select_subtitle(self, subtitles_list):
        self.display_subtitle_options(subtitles_list)

        while True:
            try:
                choice = int(
                    self.console.input(
                        "[yellow]Enter the index of the subtitle you want to download (0 to cancel): [/yellow]"
                    )
                )
                if choice == 0:
                    return None
                if 1 <= choice <= len(subtitles_list):
                    return subtitles_list[choice - 1]
                self.console.print("[red]Invalid index. Please try again.[/red]")
            except ValueError:
                self.console.print("[red]Please enter a valid number.[/red]")

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
        except TypeError:
            # print(f"{selected_subtitles=}")
            exit()

        response = requests.post(url, headers=headers, data=json.dumps(payload))
        try:
            return response.json()["link"]
        except KeyError as e:
            print(f"Error: {response.json()}, {e}")
            exit()

    def save_subtitle(self, url, path):
        """Download and save subtitle file from url to path"""
        response = requests.get(url)
        with open(path, "wb") as f:
            f.write(response.content)

    def download_single_subtitle(self, media_path, language_choice, media_name=""):
        path = Path(media_path)
        hash = self.hashFile(media_path)
        if not media_name:
            media_name = path.stem
        rprint(
            f"[cyan]Searching for subtitles for[/cyan] [yellow]{media_name}[/yellow]"
        )
        subtitle_path = Path(path.parent, f"{path.stem}.{language_choice}.srt")
        results = self.search(
            media_hash=hash, media_name=media_name, languages=language_choice
        )
        if not results:
            rprint(f"[red]No subtitles found for {media_name}[/red]")
            return False
        rprint(f"[green]Found {len(results)} results[/green]")

        # Add more results using alternate names
        new_search_terms = self.get_alternate_names(media_name)
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
            rprint(f"[red]No subtitles found for {media_name}[/red]")
            return False

        sorted_results = self.sort_list_of_dicts_by_key(results, "download_count")

        if self.auto_select:
            selected_sub = self.auto_select_subtitle(media_name, sorted_results)
        else:
            selected_sub = self.manual_select_subtitle(sorted_results)

        if selected_sub is None:
            rprint("[yellow]Subtitle download cancelled.[/yellow]")
            return False

        download_link = self.get_download_link(selected_sub)
        rprint(
            f"[green]>> Downloading {language_choice} subtitles for {media_path}[/green]"
        )
        self.print_subtitle_info(selected_sub)
        self.save_subtitle(download_link, subtitle_path)
        self.clean_subtitles(subtitle_path)
        if self.sync_choice:
            self.sync_subtitles(media_path, subtitle_path)
        return True

    def check_if_media_file(self, media_path):
        path = Path(media_path)
        if not path.exists():
            return False
        # if path is file
        if path.is_file():
            # check if file is video file
            if not path.suffix in [".mp4", ".mkv", ".avi"]:
                return False
        if path.is_dir():
            return False
        return True

    def download_subtitles(self, media_path_list, language_choice):
        for media_path in media_path_list:
            path = Path(media_path)
            if path.is_dir():
                for file in path.iterdir():
                    if self.check_if_media_file(file):
                        result = self.download_single_subtitle(file, language_choice)
                        if not result:
                            print(f"Could not find subtitles for {file}")
            elif self.check_if_media_file(path):
                result = self.download_single_subtitle(path, language_choice)
                if not result:
                    print(f"Could not find subtitles for {path}")

    def clean_subtitles(self, subtitle_path):
        clean_subtitles.clean_ads(subtitle_path)

    def sync_subtitles(self, media_path, subtitle_path):
        sync_subtitles.sync_subs_audio(media_path, subtitle_path)

    def print_subtitle_info(self, sub):
        attrs = sub["attributes"]
        movie_name = attrs["feature_details"]["movie_name"]

        info_table = Table(title=f"Selected Subtitle Information", show_header=False)
        info_table.add_column("Property", style="cyan")
        info_table.add_column("Value", style="yellow")

        info_table.add_row("Movie Name", movie_name)
        info_table.add_row("Subtitle ID", sub["id"])
        info_table.add_row("File ID", str(attrs["files"][0]["file_id"]))
        info_table.add_row("Language", attrs["language"])
        info_table.add_row("Release", attrs["release"])
        info_table.add_row("Downloads", str(attrs["download_count"]))
        info_table.add_row("AI Translated", "Yes" if attrs["ai_translated"] else "No")
        info_table.add_row(
            "Machine Translated", "Yes" if attrs["machine_translated"] else "No"
        )
        info_table.add_row(
            "Hash Match", "Yes" if attrs.get("moviehash_match", False) else "No"
        )
        info_table.add_row("URL", attrs["url"])

        self.console.print(info_table)


if __name__ == "__main__":
    print("This is a module, import it in your project")
