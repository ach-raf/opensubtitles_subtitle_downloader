# opensubtitles.py
import os
import struct
import requests
import json
import random
import re
from pathlib import Path
import library.clean_subtitles as clean_subtitles
import library.sync_subtitles as sync_subtitles
import library.utils as utils
import spacy


class OpenSubtitles:
    def __init__(self, username, password, api_key):
        # self.nlp = spacy.load("en_core_web_md")
        self.username = username
        self.password = password
        self.api_key = api_key
        self.token = self.login()

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
        if utils.read_token():
            return utils.read_token()

        url = "https://api.opensubtitles.com/api/v1/login"

        payload = {"username": self.username, "password": self.password}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "nakrad v1.0",
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
        params = {
            "languages": languages,
            # "order_by": "votes",
            # "order_direction": "desc",
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Api-Key": self.api_key,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "nakrad v1.0",
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
            print(f"Error: {response.json()}, {e}")
            return None

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

    def jaccard_similarity(self, str1, str2):
        a = set(str1.split())
        b = set(str2.split())
        intersection = len(a.intersection(b))
        union = len(a) + len(b) - intersection
        return intersection / union

    """def auto_select_sub_new(self, video_file_name, subtitles_result_list):
        # print(f"_subtitles_result_list: {len(subtitles_result_list)}")
        subtitles_selected = None
        max_similarity = -1

        # Process the video file name with spaCy
        video_file_doc = self.nlp(video_file_name)

        for subtitle in subtitles_result_list:
            # if the subtitle is found by hash, return it
            if subtitle["attributes"]["moviehash_match"]:
                return subtitle
            release_name = subtitle["attributes"]["release"]

            # Process the subtitle release name with spaCy
            release_name_doc = self.nlp(release_name)

            # Calculate similarity between video file name and subtitle release name
            similarity = video_file_doc.similarity(release_name_doc)

            # Update subtitles_selected if a better match is found
            if similarity > max_similarity:
                max_similarity = similarity
                subtitles_selected = subtitle

        return subtitles_selected"""

    def auto_select_sub(self, video_file_name, _subtitles_result_list):
        # print(f"_subtitles_result_list : {len(_subtitles_result_list)}")
        _subtitles_selected = None
        """Automatic subtitles selection, by hash or using filename match"""
        video_file_parts = (
            video_file_name.replace("-", ".")
            .replace(" ", ".")
            .replace("_", ".")
            .lower()
            .split(".")
        )
        max_score = -1

        # make the list random to avoid selecting the same sub every time
        # random.shuffle(_subtitles_result_list)
        for subtitle in _subtitles_result_list:
            score = 0
            # extra point if the sub is found by hash
            if subtitle["attributes"]["moviehash_match"]:
                score += 10

            # points for filename mach
            release_name = subtitle["attributes"]["release"]
            sub_file_parts = (
                release_name.replace("-", ".")
                .replace(" ", ".")
                .replace("_", ".")
                .lower()
                .split(".")
            )
            for subPart in sub_file_parts:
                for filePart in video_file_parts:
                    if subPart == filePart:
                        score += 1
            if score > max_score:
                max_score = score
                _subtitles_selected = subtitle

        return _subtitles_selected

    def get_download_link(self, selected_subtitles):
        url = "https://api.opensubtitles.com/api/v1/download"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Api-Key": self.api_key,
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "nakrad v1.0",
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
        subtitle_path = Path(path.parent, f"{path.stem}_{language_choice}.srt")
        results = self.search(
            media_hash=hash, media_name=media_name, languages=language_choice
        )
        print(f"Searcing for subtitles for {media_name}, found {len(results)} results")
        # add more results, by searching with the new search term
        new_search_terms = self.get_alternate_names(media_name)
        if new_search_terms:
            for term in new_search_terms:
                temp_results = self.search(
                    media_hash=hash,
                    media_name=term,
                    languages=language_choice,
                )
                results.extend(temp_results)
                print(
                    f"Adding more results by searching for {term}, found {len(temp_results)} results"
                )
        if not results:
            print(f"No subtitles found for {media_name}, or {new_search_terms}")
            return False

        sorted_results = self.sort_list_of_dicts_by_key(results, "download_count")
        print(f"Found {len(sorted_results)} subtitles for {media_name}")
        selected_sub = self.auto_select_sub(media_name, sorted_results)
        download_link = self.get_download_link(selected_sub)
        print(f">> Downloading {language_choice} subtitles for {media_path}")
        self.print_subtitle_info(selected_sub)
        self.save_subtitle(download_link, subtitle_path)
        self.clean_subtitles(subtitle_path)
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
            elif self.check_if_media_file(media_path):
                self.download_single_subtitle(media_path, language_choice)

    def clean_subtitles(self, subtitle_path):
        clean_subtitles.clean_ads(subtitle_path)

    def sync_subtitles(self, media_path, subtitle_path):
        sync_subtitles.sync_subs_audio(media_path, subtitle_path)

    def print_subtitle_info(self, sub):
        movie_name = sub["attributes"]["feature_details"]["movie_name"]
        sub_id = sub["id"]
        file_id = sub["attributes"]["files"][0]["file_id"]
        language = sub["attributes"]["language"]
        release = sub["attributes"]["release"]
        download_count = sub["attributes"]["download_count"]
        url = sub["attributes"]["url"]
        ai_translated = sub["attributes"]["ai_translated"]
        machine_translated = sub["attributes"]["machine_translated"]
        media_hash = None
        try:
            media_hash = sub["attributes"]["moviehash_match"]
        except KeyError:
            pass

        print(f"Media Name: {movie_name}, sub_id: {sub_id}")
        print(f"file_id {file_id}, hash: {media_hash}")
        print(f"- Language: {language}")
        print(f"- Release: {release}")
        print(f"- Downloads: {download_count}")
        print(f"- AI Translated: {ai_translated}")
        print(f"- machine_translated: {machine_translated}")
        print(f"- URL: {url}")


if __name__ == "__main__":
    print("This is a module, import it in your project")
