from tui.media import expand_media_paths


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
