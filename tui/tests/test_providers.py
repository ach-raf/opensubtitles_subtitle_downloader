from pathlib import Path

from library.OpenSubtitles import OpenSubtitles
from library.SubDL import SubDL
from library.SubSource import SubSource
from tui.domain import Provider, SearchRequest
from tui.providers.opensubtitles import OpenSubtitlesAdapter
from tui.providers.subdl import SubDLAdapter
from tui.providers.subsource import SubSourceAdapter

REQUEST = SearchRequest(
    media_path=Path("Movie.mkv"),
    query="Movie",
    language="en",
)
SUBDL_RESPONSE = {
    "id": "77",
    "attributes": {
        "release": "Movie.2026.1080p",
        "language": "en",
        "url": "https://dl.example/file.zip?api_key=secret",
        "download_count": 5,
    },
}
SUBSOURCE_RESPONSE = {
    "id": "88",
    "attributes": {
        "release": "Movie WEB",
        "language": "english",
        "download_count": 9,
    },
}


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def search_candidates(self, path, language, query):
        return self.rows


class FailingClient:
    def search_candidates(self, path, language, query):
        raise OSError("network unavailable")


class SecretFailingClient:
    def search_candidates(self, path, language, query):
        raise OSError("GET https://example.test/search?api_key=do-not-leak&lang=en")


class QuietConsole:
    def print(self, *_args, **_kwargs):
        return None


def test_subdl_adapter_keeps_authenticated_url_private():
    adapter = SubDLAdapter(client=FakeClient([SUBDL_RESPONSE]))

    result = adapter.search(REQUEST)
    candidate = result.candidates[0]

    assert candidate.provider is Provider.SUBDL
    assert candidate.key.startswith("subdl:")
    assert "api_key" not in str(candidate.as_public_dict())
    assert candidate.public_url is None
    assert candidate.download_ref["attributes"]["url"].endswith("api_key=secret")


def test_subsource_adapter_normalizes_language_to_code():
    adapter = SubSourceAdapter(client=FakeClient([SUBSOURCE_RESPONSE]))

    result = adapter.search(REQUEST)

    assert result.candidates[0].language == "en"


def test_provider_error_is_distinct_from_zero_results():
    failed = OpenSubtitlesAdapter(client=FailingClient()).search(REQUEST)
    empty = OpenSubtitlesAdapter(client=FakeClient([])).search(REQUEST)

    assert failed.error is not None
    assert empty.error is None
    assert empty.candidates == []


def test_provider_errors_redact_authenticated_urls():
    failed = SubDLAdapter(client=SecretFailingClient()).search(REQUEST)

    assert "do-not-leak" not in failed.error
    assert "api_key=[redacted]" in failed.error


def test_missing_provider_id_gets_stable_source_scoped_fingerprint():
    row = {"attributes": {"release": "Same", "language": "English"}}
    first = OpenSubtitlesAdapter(client=FakeClient([row])).search(REQUEST)
    second = OpenSubtitlesAdapter(client=FakeClient([row])).search(REQUEST)

    assert first.candidates[0].key == second.candidates[0].key
    assert first.candidates[0].key.startswith("opensubtitles:fingerprint-")


def test_opensubtitles_candidates_add_hash_and_filename_results(tmp_path):
    media = tmp_path / "Dune - Prophecy (2024) - S01E01.mkv"
    media.touch()
    client = object.__new__(OpenSubtitles)
    client.subtitle_utils = type(
        "SearchUtils",
        (),
        {
            "hashFile": staticmethod(lambda _path: "movie-hash"),
            "get_alternate_names": staticmethod(
                lambda _name: ["Dune Prophecy S01E01", "Dune.Prophecy.1x01"]
            ),
        },
    )()
    calls = []

    def search(*, media_hash, media_name, languages):
        calls.append((media_hash, media_name, languages))
        is_hash_search = bool(media_hash)
        return [
            {
                "id": f"id-{len(calls)}",
                "attributes": {
                    "release": media_name or "hash release",
                    "moviehash_match": is_hash_search,
                },
            },
            {
                "id": "shared",
                "attributes": {
                    "release": "duplicate",
                    "moviehash_match": is_hash_search,
                },
            },
        ]

    client.search = search

    results = client.search_candidates(media, "en", media.stem)

    assert calls[0] == ("movie-hash", "", "en")
    assert [call[1] for call in calls[1:]] == [
        media.stem,
        "Dune - Prophecy (2024)",
        "Dune Prophecy S01E01",
        "Dune.Prophecy.1x01",
    ]
    assert all(call[0] == "" for call in calls[1:])
    assert len(results) == 6
    shared = next(row for row in results if row["id"] == "shared")
    assert shared["attributes"]["moviehash_match"] is True


def test_opensubtitles_legacy_download_uses_external_output_directory(tmp_path):
    output_directory = tmp_path / "subtitles"
    media = tmp_path / "library" / "Movie.mkv"
    saved_paths = []
    client = object.__new__(OpenSubtitles)
    client.output_directory = output_directory
    client.auto_select = True
    client.sync_audio_to_subs = False
    client.console = QuietConsole()
    client._gather_candidates = lambda *_args: ([{"id": "1"}], False)
    client.get_download_link = lambda _selected: "https://example.test/subtitle"
    client.print_subtitle_info = lambda _selected: None

    def save_subtitle(_url, path):
        saved_paths.append(path)
        return True

    client.save_subtitle = save_subtitle
    client.subtitle_utils = type(
        "Utils",
        (),
        {
            "sort_list_of_dicts_by_key": staticmethod(lambda rows, _key: rows),
            "auto_select_subtitle": staticmethod(lambda _name, rows: rows[0]),
            "clean_subtitles": staticmethod(lambda _path: None),
        },
    )()

    assert client.process_media_file(media, "en") is True
    assert saved_paths == [output_directory / "Movie.en.srt"]


def test_subdl_legacy_single_file_uses_external_output_directory(
    tmp_path,
    monkeypatch,
):
    output_directory = tmp_path / "subtitles"
    media = tmp_path / "library" / "Movie.mkv"
    client = object.__new__(SubDL)
    client.output_directory = output_directory
    client.download_base_url = "https://example.test"
    client.console = QuietConsole()
    response = type(
        "Response",
        (),
        {
            "content": b"subtitle",
            "raise_for_status": staticmethod(lambda: None),
        },
    )()
    monkeypatch.setattr(
        "library.SubDL.requests.get",
        lambda *_args, **_kwargs: response,
    )

    result = client._download_single_file("/movie.srt", "srt", media, "en")

    assert result == output_directory / "Movie.en.srt"
    assert result.read_text(encoding="utf-8") == "subtitle"


def test_subsource_legacy_archive_uses_external_output_directory(tmp_path):
    output_directory = tmp_path / "subtitles"
    media = tmp_path / "library" / "Movie.mkv"
    archive_paths = []
    client = object.__new__(SubSource)
    client.output_directory = output_directory
    client.console = QuietConsole()
    client._download_url_for = lambda _subtitle_id: "https://example.test/archive"
    client._get_raw = lambda _url: type(
        "Response",
        (),
        {"iter_content": staticmethod(lambda chunk_size: [b"archive"])},
    )()

    class FakeArchive:
        def names(self):
            return ["release.srt"]

        def read(self, _name):
            return b"subtitle"

        def close(self):
            return None

    def open_archive(path):
        archive_paths.append(path)
        return FakeArchive()

    client._open_archive = open_archive

    result = client._download_archive(
        {"id": "88"},
        media,
        "en",
        None,
        None,
        True,
    )

    assert archive_paths == [output_directory / "Movie.download"]
    assert result == output_directory / "Movie.en.srt"
    assert result.read_text(encoding="utf-8") == "subtitle"


def test_subdl_legacy_external_output_does_not_overwrite_existing_file(
    tmp_path,
    monkeypatch,
):
    output_directory = tmp_path / "subtitles"
    output_directory.mkdir()
    existing = output_directory / "Movie.en.srt"
    existing.write_text("old", encoding="utf-8")
    client = object.__new__(SubDL)
    client.output_directory = output_directory
    client.download_base_url = "https://example.test"
    client.console = QuietConsole()
    response = type(
        "Response",
        (),
        {
            "content": b"new",
            "raise_for_status": staticmethod(lambda: None),
        },
    )()
    monkeypatch.setattr(
        "library.SubDL.requests.get",
        lambda *_args, **_kwargs: response,
    )

    result = client._download_single_file(
        "/movie.srt",
        "srt",
        tmp_path / "library" / "Movie.mkv",
        "en",
    )

    assert result is None
    assert existing.read_text(encoding="utf-8") == "old"


def test_opensubtitles_legacy_external_output_does_not_overwrite_existing_file(
    tmp_path,
):
    output_directory = tmp_path / "subtitles"
    output_directory.mkdir()
    existing = output_directory / "Movie.en.srt"
    existing.write_text("old", encoding="utf-8")
    client = object.__new__(OpenSubtitles)
    client.output_directory = output_directory
    client.auto_select = True
    client.sync_audio_to_subs = False
    client.console = QuietConsole()
    client._gather_candidates = lambda *_args: ([{"id": "1"}], False)
    client.get_download_link = lambda _selected: "https://example.test/subtitle"
    client.print_subtitle_info = lambda _selected: None
    client.save_subtitle = lambda _url, path: path.write_text(
        "new",
        encoding="utf-8",
    )
    client.subtitle_utils = type(
        "Utils",
        (),
        {
            "sort_list_of_dicts_by_key": staticmethod(lambda rows, _key: rows),
            "auto_select_subtitle": staticmethod(lambda _name, rows: rows[0]),
            "clean_subtitles": staticmethod(lambda _path: None),
        },
    )()

    result = client.process_media_file(
        tmp_path / "library" / "Movie.mkv",
        "en",
    )

    assert result is False
    assert existing.read_text(encoding="utf-8") == "old"


def test_subsource_legacy_external_output_does_not_overwrite_existing_file(
    tmp_path,
):
    output_directory = tmp_path / "subtitles"
    output_directory.mkdir()
    existing = output_directory / "Movie.en.srt"
    existing.write_text("old", encoding="utf-8")
    client = object.__new__(SubSource)
    client.output_directory = output_directory
    client.console = QuietConsole()
    client._download_url_for = lambda _subtitle_id: "https://example.test/archive"
    client._get_raw = lambda _url: type(
        "Response",
        (),
        {"iter_content": staticmethod(lambda chunk_size: [b"archive"])},
    )()

    class FakeArchive:
        def names(self):
            return ["release.srt"]

        def read(self, _name):
            return b"new"

        def close(self):
            return None

    client._open_archive = lambda _path: FakeArchive()

    result = client._download_archive(
        {"id": "88"},
        tmp_path / "library" / "Movie.mkv",
        "en",
        None,
        None,
        True,
    )

    assert result is None
    assert existing.read_text(encoding="utf-8") == "old"
