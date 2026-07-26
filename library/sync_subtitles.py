import shutil
import subprocess
from pathlib import Path


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


def sync_subs_audio(media_path, subtitle_path):
    media_path = Path(media_path)
    subtitle_path = Path(subtitle_path)

    media_path = media_path.resolve()
    subtitle_path = subtitle_path.resolve()
    # using subsync library to do the magic
    executable = shutil.which("ffs")
    if executable is None:
        raise RuntimeError("ffsubsync executable 'ffs' is not available")
    _command = [
        executable,
        f"{media_path}",  # path to the video
        "-i",
        f"{subtitle_path}",  # the subtitle for input, using the same name as the film + .srt
        "-o",
        f"{subtitle_path}",  # the output replaces the original subtitle
        "--encoding",
        "utf-8",
    ]  # encoding

    subprocess.run(_command, check=True)
    print(f"{subtitle_path.absolute()} synced!")
    return True


if __name__ == "__main__":
    print("This is a Module")
