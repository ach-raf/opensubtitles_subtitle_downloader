import subprocess
import sys
import os
import shutil
from tarfile import SUPPORTED_TYPES
from pathlib import Path


CURRENT_DIR_PATH = os.path.dirname(os.path.realpath(__file__))


def sync_subs_srt(_reference_srt, _unsync_srt, _output):
    _command = [
        shutil.which("ffs"),
        f"{_reference_srt}",
        "-i",
        f"{_unsync_srt}",
        "-o",
        f"{_output}",
    ]
    subprocess.call(_command)


def sync_subs_audio(_media_path):
    _media_path = Path(_media_path)
    current_extension = "srt"
    if os.path.exists(Path(_media_path.parent, f"{_media_path.stem}.ass")):
        current_extension = "ass"

    subtitle_path = Path(_media_path.parent, f"{_media_path.stem}.{current_extension}")
    _media_path = _media_path.resolve()
    subtitle_path = subtitle_path.resolve()
    # using subsync library to do the magic
    _command = [
        "ffs",
        f"{_media_path}",  # path to the video
        "-i",
        f"{subtitle_path}",  # the subtitle for input, using the same name as the film + .srt
        "-o",
        f"{subtitle_path}",  # the output replaces the original subtitle
        "--encoding",
        "utf-8",
    ]  # encoding

    subprocess.call(_command)
    print(f"{subtitle_path.absolute()} synced!")


if __name__ == "__main__":
    print("This is a Module")
