import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable
from pathlib import Path


def _find_ffsubsync() -> str:
    names = ("ffs", "ffsubsync")
    for name in names:
        if executable := shutil.which(name):
            return executable

    script_directories = [Path(sys.executable).parent]
    for scheme in (
        sysconfig.get_default_scheme(),
        sysconfig.get_preferred_scheme("user"),
    ):
        try:
            scripts = sysconfig.get_path("scripts", scheme=scheme)
        except (KeyError, TypeError):
            continue
        if scripts:
            script_directories.append(Path(scripts))

    suffixes = ("", ".exe")
    for directory in dict.fromkeys(script_directories):
        for name in names:
            for suffix in suffixes:
                candidate = directory / f"{name}{suffix}"
                if candidate.is_file():
                    return str(candidate)

    raise RuntimeError(
        "ffsubsync launcher was not found (checked 'ffs' and 'ffsubsync'). "
        f'Install it for this Python with: "{sys.executable}" '
        "-m pip install ffsubsync"
    )


def sync_subs_srt(_reference_srt, _unsync_srt, _output):
    _command = [
        _find_ffsubsync(),
        f"{_reference_srt}",
        "-i",
        f"{_unsync_srt}",
        "-o",
        f"{_output}",
    ]
    subprocess.call(_command)


def sync_subs_audio(
    media_path,
    subtitle_path,
    *,
    on_output: Callable[[str], None] | None = None,
):
    media_path = Path(media_path)
    subtitle_path = Path(subtitle_path)

    media_path = media_path.resolve()
    subtitle_path = subtitle_path.resolve()
    # using subsync library to do the magic
    executable = _find_ffsubsync()
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

    if on_output is None:
        subprocess.run(_command, check=True)
        print(f"{subtitle_path.absolute()} synced!")
        return True

    process = subprocess.Popen(
        _command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    if process.stdout is not None:
        for line in process.stdout:
            on_output(line.rstrip("\r\n"))
    returncode = process.wait()
    if returncode:
        raise subprocess.CalledProcessError(returncode, _command)
    return True


if __name__ == "__main__":
    print("This is a Module")
