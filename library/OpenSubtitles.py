# opensubtitles.py
import os
import struct
import requests
import json
from pathlib import Path
import library.clean_subtitles as clean_subtitles
import library.sync_subtitles as sync_subtitles
import library.utils as utils


class OpenSubtitles:
    def __init__(self, username, password, api_key):
        self.username = username
        self.password = password
        self.api_key = api_key
        self.token = self.login()

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
        print(params)
        response = requests.get(url, headers=headers, params=params)
        try:
            response.raise_for_status()
            return response.json()["data"]
        except requests.exceptions.HTTPError as e:
            print(f"Error: {response.json()}, {e}")
            return None

    def auto_select_sub(self, video_file_name, _subtitles_result_list):
        print(f"_subtitles_result_list : {len(_subtitles_result_list)}")
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
            print(f"{selected_subtitles=}")
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

    def download_single_subtitle(self, media_path, language_choice):
        path = Path(media_path)
        hash = self.hashFile(media_path)
        media_name = path.stem
        subtitle_path = Path(path.parent, f"{media_name}_{language_choice}.srt")
        results = self.search(
            media_hash=hash, media_name=media_name, languages=language_choice
        )
        if not results:
            print(f"No subtitles found for {media_name}")
            return False
        print(f"Found {len(results)} subtitles for {media_name}")
        selected_sub = self.auto_select_sub(media_name, results)
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
