from pathlib import Path

from tui.domain import Candidate, EngineMode, Provider, SearchRequest


def test_candidate_key_is_provider_scoped():
    left = Candidate(
        provider=Provider.OPENSUBTITLES,
        provider_id="42",
        release="A",
        language="en",
    )
    right = Candidate(
        provider=Provider.SUBDL,
        provider_id="42",
        release="A",
        language="en",
    )

    assert left.key == "opensubtitles:42"
    assert right.key == "subdl:42"
    assert left.key != right.key


def test_candidate_public_mapping_excludes_private_download_reference():
    candidate = Candidate(
        provider=Provider.SUBDL,
        provider_id="7",
        release="Movie",
        language="en",
        download_ref={"url": "https://example.test/file.zip?api_key=secret"},
    )

    assert "download_ref" not in candidate.as_public_dict()
    assert "secret" not in repr(candidate)


def test_search_request_keeps_effective_query():
    request = SearchRequest(
        media_path=Path("Movie.mkv"),
        query="Director Cut",
        language="en",
    )

    assert request.query == "Director Cut"
    assert EngineMode.ASK.value == "ask"
