from pathlib import Path
from types import SimpleNamespace

from library import sync_subtitles


class FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self.returncode = returncode

    def wait(self):
        return self.returncode


def test_sync_subs_audio_streams_combined_ffsubsync_output(monkeypatch, tmp_path):
    commands = []
    process = FakeProcess(
        [
            "extracting speech segments...\n",
            "computing alignments...\n",
            "...done\n",
        ]
    )

    monkeypatch.setattr(sync_subtitles.shutil, "which", lambda _name: "ffs")

    def fake_popen(command, **kwargs):
        commands.append((command, kwargs))
        return process

    monkeypatch.setattr(sync_subtitles.subprocess, "Popen", fake_popen)
    output = []

    result = sync_subtitles.sync_subs_audio(
        tmp_path / "Movie.mkv",
        tmp_path / "Movie.en.srt",
        on_output=output.append,
    )

    assert result is True
    assert output == [
        "extracting speech segments...",
        "computing alignments...",
        "...done",
    ]
    assert commands[0][1]["stderr"] is sync_subtitles.subprocess.STDOUT
    assert commands[0][1]["text"] is True


def test_sync_subs_audio_keeps_direct_terminal_output_without_callback(
    monkeypatch,
    tmp_path,
):
    calls = []
    monkeypatch.setattr(sync_subtitles.shutil, "which", lambda _name: "ffs")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(sync_subtitles.subprocess, "run", fake_run)

    sync_subtitles.sync_subs_audio(
        Path(tmp_path / "Movie.mkv"),
        Path(tmp_path / "Movie.en.srt"),
    )

    assert calls[0][1] == {"check": True}


def test_sync_subs_audio_finds_canonical_launcher_beside_python(
    monkeypatch,
    tmp_path,
):
    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    python = scripts / "python.exe"
    launcher = scripts / "ffsubsync.exe"
    python.touch()
    launcher.touch()
    calls = []

    monkeypatch.setattr(
        sync_subtitles,
        "sys",
        SimpleNamespace(executable=str(python)),
        raising=False,
    )
    monkeypatch.setattr(sync_subtitles.shutil, "which", lambda _name: None)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))

    monkeypatch.setattr(sync_subtitles.subprocess, "run", fake_run)

    sync_subtitles.sync_subs_audio(
        tmp_path / "Movie.mkv",
        tmp_path / "Movie.en.srt",
    )

    assert calls[0][0][0] == str(launcher)
