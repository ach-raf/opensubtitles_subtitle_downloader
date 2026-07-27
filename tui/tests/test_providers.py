from pathlib import Path

from library.OpenSubtitles import OpenSubtitles
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
