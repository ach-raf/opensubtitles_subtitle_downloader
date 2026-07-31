from tui.media import (
    DEFAULT_MEDIA_EXTENSIONS,
    expand_media_paths,
    resolve_media_extensions,
)


def test_default_media_extensions_cover_common_video_formats():
    assert {"avi", "av1", "mkv", "mp4"} <= DEFAULT_MEDIA_EXTENSIONS


def test_resolve_media_extensions_extends_and_excludes_defaults():
    extensions = resolve_media_extensions(
        include=[".CUSTOM", "ts"],
        exclude=[".TS", "AVI"],
    )

    assert "custom" in extensions
    assert "mkv" in extensions
    assert "ts" not in extensions
    assert "avi" not in extensions


def test_expand_media_paths_expands_directories_non_recursively(tmp_path):
    movie = tmp_path / "Movie.mkv"
    episode = tmp_path / "Episode.mp4"
    nested = tmp_path / "nested"
    nested.mkdir()
    ignored = nested / "Ignored.mkv"
    ignored.touch()
    movie.touch()
    episode.touch()

    result = expand_media_paths([tmp_path], {"mkv", "mp4"})

    assert result.paths == [episode.resolve(), movie.resolve()]
    assert ignored not in result.paths


def test_expand_media_paths_recurses_when_requested(tmp_path):
    first = tmp_path / "A Movie" / "first.mkv"
    second = tmp_path / "B Movie" / "deeper" / "second.mp4"
    first.parent.mkdir()
    second.parent.mkdir(parents=True)
    first.touch()
    second.touch()

    result = expand_media_paths(
        [tmp_path],
        {"mkv", "mp4"},
        recursive=True,
    )

    assert result.paths == [first.resolve(), second.resolve()]


def test_expand_media_paths_reports_unsupported_input(tmp_path):
    note = tmp_path / "notes.txt"
    note.touch()

    result = expand_media_paths([note], {"mkv"})

    assert result.paths == []
    assert result.issues[0].kind == "unsupported"


def test_expand_media_paths_reports_missing_input(tmp_path):
    missing = tmp_path / "missing.mkv"

    result = expand_media_paths([missing], {"mkv"})

    assert result.issues[0].kind == "missing"
