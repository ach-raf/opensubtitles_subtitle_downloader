import threading

from tui.domain import (
    Candidate,
    HealthResult,
    Provider,
    ProviderSearchResult,
    SearchRequest,
)
from tui.search import AUTO_PRIORITY, SearchCoordinator

REQUEST = SearchRequest(
    media_path="Movie.2026.mkv",
    query="Movie 2026",
    language="en",
)


def candidate(provider, provider_id):
    return Candidate(
        provider=provider,
        provider_id=provider_id,
        release=f"Movie {provider_id}",
        language="en",
    )


class FakeAdapter:
    def __init__(self, provider, candidates=(), error=None):
        self.provider = provider
        self.candidates = list(candidates)
        self.error = error
        self.calls = 0

    def search(self, request):
        self.calls += 1
        return ProviderSearchResult(
            provider=self.provider,
            candidates=list(self.candidates),
            error=self.error,
        )


class BarrierAdapter(FakeAdapter):
    def __init__(self, provider, barrier):
        super().__init__(provider, [candidate(provider, "42")])
        self.barrier = barrier

    def search(self, request):
        self.barrier.wait(timeout=2)
        return super().search(request)


def test_merge_retains_same_raw_id_from_all_providers():
    adapters = {
        provider: FakeAdapter(provider, [candidate(provider, "42")])
        for provider in Provider
    }

    result = SearchCoordinator(adapters).merge(REQUEST)

    assert {item.key for item in result.candidates} == {
        "opensubtitles:42",
        "subdl:42",
        "subsource:42",
    }


def test_merge_retains_successes_and_reports_partial_failure():
    adapters = {
        Provider.OPENSUBTITLES: FakeAdapter(
            Provider.OPENSUBTITLES, error="network down"
        ),
        Provider.SUBDL: FakeAdapter(Provider.SUBDL, [candidate(Provider.SUBDL, "1")]),
    }

    result = SearchCoordinator(adapters).merge(REQUEST)

    assert [item.key for item in result.candidates] == ["subdl:1"]
    assert result.errors[Provider.OPENSUBTITLES] == "network down"


def test_merge_runs_provider_calls_concurrently():
    gate = threading.Barrier(3)
    adapters = {provider: BarrierAdapter(provider, gate) for provider in Provider}

    result = SearchCoordinator(adapters).merge(REQUEST)

    assert len(result.candidates) == 3


def test_auto_falls_back_after_error_and_empty_success():
    adapters = {
        Provider.SUBSOURCE: FakeAdapter(Provider.SUBSOURCE, error="down"),
        Provider.OPENSUBTITLES: FakeAdapter(Provider.OPENSUBTITLES),
        Provider.SUBDL: FakeAdapter(Provider.SUBDL, [candidate(Provider.SUBDL, "8")]),
    }

    result = SearchCoordinator(adapters).auto(REQUEST)

    assert result.selected_provider is Provider.SUBDL
    assert result.attempted == list(AUTO_PRIORITY)


def test_health_does_not_exclude_a_working_provider():
    adapters = {
        Provider.OPENSUBTITLES: FakeAdapter(
            Provider.OPENSUBTITLES,
            [candidate(Provider.OPENSUBTITLES, "1")],
        )
    }

    result = SearchCoordinator(adapters).merge(
        REQUEST,
        health={
            Provider.OPENSUBTITLES: HealthResult(
                provider=Provider.OPENSUBTITLES,
                configured=True,
                reachable=False,
                reason="probe failed",
            )
        },
    )

    assert result.candidates[0].provider is Provider.OPENSUBTITLES


def test_shared_filters_apply_to_all_providers():
    ai = candidate(Provider.SUBDL, "ai")
    ai.ai_translated = True
    hi = candidate(Provider.SUBSOURCE, "hi")
    hi.hearing_impaired = True
    normal = candidate(Provider.OPENSUBTITLES, "normal")
    adapters = {
        Provider.SUBDL: FakeAdapter(Provider.SUBDL, [ai]),
        Provider.SUBSOURCE: FakeAdapter(Provider.SUBSOURCE, [hi]),
        Provider.OPENSUBTITLES: FakeAdapter(Provider.OPENSUBTITLES, [normal]),
    }
    request = SearchRequest(
        media_path=REQUEST.media_path,
        query=REQUEST.query,
        language="en",
        hearing_impaired="exclude",
        show_ai_translated=False,
    )

    result = SearchCoordinator(adapters).merge(request)

    assert [item.key for item in result.candidates] == ["opensubtitles:normal"]
