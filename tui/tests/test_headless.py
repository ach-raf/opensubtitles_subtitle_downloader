from pathlib import Path

import pytest

from tui.config import (
    ApplicationConfig,
    CleaningConfig,
    GeneralConfig,
    ProviderConfig,
)
from tui.domain import (
    Candidate,
    DownloadResult,
    PostProcessResult,
    Provider,
)
from tui.headless import HeadlessAllProvidersRunner, HeadlessBatchSummary
from tui.search import CoordinatedSearchResult


class FakeAdapter:
    pass


class FakeAllProvidersCoordinator:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    def all_providers(self, request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeJobs:
    def __init__(self, downloads=None, postprocess=None):
        self.download_results = list(downloads or [])
        self.postprocess_result = postprocess or PostProcessResult()
        self.downloaded = []
        self.postprocessed = []

    def download(self, candidate, media_path):
        media = Path(media_path)
        self.downloaded.append((candidate, media))
        if self.download_results:
            result = self.download_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        return DownloadResult(
            provider=candidate.provider,
            media_path=media,
            subtitle_path=media.with_suffix(".srt"),
        )

    def postprocess(self, download, **kwargs):
        self.postprocessed.append((download, kwargs))
        return self.postprocess_result


@pytest.fixture
def application_config():
    return ApplicationConfig(
        general=GeneralConfig(
            hearing_impaired="exclude",
            show_ai_translated=False,
            sync_audio_to_subs="always",
            auto_selection=False,
            opt_force_utf8=True,
        ),
        providers={
            provider: ProviderConfig(provider=provider) for provider in Provider
        },
        cleaning=CleaningConfig(
            enabled=True,
            ads_file_path=Path("ads.txt"),
        ),
    )


def candidate(provider_id="best", score=99):
    return Candidate(
        provider=Provider.OPENSUBTITLES,
        provider_id=provider_id,
        release=provider_id,
        language="ar",
        score=score,
    )


def result(*candidates, errors=None):
    return CoordinatedSearchResult(
        candidates=list(candidates),
        errors=errors or {},
    )


def test_headless_all_providers_downloads_only_first_ranked_candidate(
    tmp_path,
    application_config,
):
    media = tmp_path / "movie.mkv"
    media.touch()
    lower = Candidate(
        provider=Provider.SUBDL,
        provider_id="lower",
        release="lower",
        language="ar",
        score=80,
    )
    best = candidate()
    coordinator = FakeAllProvidersCoordinator([result(best, lower)])
    jobs = FakeJobs()
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=coordinator,
        jobs=jobs,
    )

    summary = runner.run([media], "ar")

    assert jobs.downloaded == [(best, media)]
    assert summary == HeadlessBatchSummary(attempted=1, succeeded=1, failed=0)
    request = coordinator.requests[0]
    assert request.media_path == media
    assert request.query == "movie"
    assert request.language == "ar"
    assert request.hearing_impaired == "exclude"
    assert request.show_ai_translated is False


def test_partial_provider_errors_are_emitted_and_best_candidate_downloads(
    tmp_path,
    application_config,
):
    media = tmp_path / "movie.mkv"
    media.touch()
    best = candidate()
    emitted = []
    jobs = FakeJobs()
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator(
            [result(best, errors={Provider.SUBDL: "service unavailable"})]
        ),
        jobs=jobs,
        emit=emitted.append,
    )

    summary = runner.run([media], "ar")

    assert summary.succeeded == 1
    assert jobs.downloaded == [(best, media)]
    assert any("SubDL" in message and "service unavailable" in message for message in emitted)


def test_no_candidates_fails_one_file_and_continues(
    tmp_path,
    application_config,
):
    first = tmp_path / "first.mkv"
    second = tmp_path / "second.mkv"
    first.touch()
    second.touch()
    best = candidate()
    jobs = FakeJobs()
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator([result(), result(best)]),
        jobs=jobs,
    )

    summary = runner.run([first, second], "ar")

    assert summary == HeadlessBatchSummary(attempted=2, succeeded=1, failed=1)
    assert summary.exit_code == 0
    assert jobs.downloaded == [(best, second)]


def test_conflict_fails_without_postprocessing(tmp_path, application_config):
    media = tmp_path / "movie.mkv"
    media.touch()
    conflict = tmp_path / "movie.ar.srt"
    jobs = FakeJobs(
        [
            DownloadResult(
                provider=Provider.OPENSUBTITLES,
                media_path=media,
                conflict_path=conflict,
            )
        ]
    )
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator([result(candidate())]),
        jobs=jobs,
    )

    summary = runner.run([media], "ar")

    assert summary.failed == 1
    assert summary.exit_code == 1
    assert jobs.postprocessed == []


def test_download_failure_increments_failed(tmp_path, application_config):
    media = tmp_path / "movie.mkv"
    media.touch()
    jobs = FakeJobs(
        [
            DownloadResult(
                provider=Provider.OPENSUBTITLES,
                media_path=media,
                error="network failed",
            )
        ]
    )
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator([result(candidate())]),
        jobs=jobs,
    )

    summary = runner.run([media], "ar")

    assert summary == HeadlessBatchSummary(attempted=1, succeeded=0, failed=1)
    assert summary.exit_code == 1


def test_exception_fails_one_file_and_continues(tmp_path, application_config):
    first = tmp_path / "first.mkv"
    second = tmp_path / "second.mkv"
    first.touch()
    second.touch()
    best = candidate()
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator([RuntimeError("boom"), result(best)]),
        jobs=FakeJobs(),
    )

    summary = runner.run([first, second], "ar")

    assert summary == HeadlessBatchSummary(attempted=2, succeeded=1, failed=1)


def test_auto_selection_false_still_downloads_best_candidate(
    tmp_path,
    application_config,
):
    media = tmp_path / "movie.mkv"
    media.touch()
    application_config.general.auto_selection = False
    jobs = FakeJobs()
    best = candidate()
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator([result(best)]),
        jobs=jobs,
    )

    runner.run([media], "ar")

    assert jobs.downloaded == [(best, media)]


def test_sync_ask_skips_sync_and_emits_one_notice(tmp_path, application_config):
    media = tmp_path / "movie.mkv"
    media.touch()
    application_config.general.sync_audio_to_subs = "ask"
    emitted = []
    jobs = FakeJobs()
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator([result(candidate())]),
        jobs=jobs,
        emit=emitted.append,
    )

    runner.run([media], "ar")

    assert jobs.postprocessed[0][1] == {
        "force_utf8": True,
        "clean": True,
        "sync": False,
        "ads_path": Path("ads.txt"),
    }
    assert len([message for message in emitted if "sync" in message.lower()]) == 1


def test_postprocess_warnings_do_not_undo_success(tmp_path, application_config):
    media = tmp_path / "movie.mkv"
    media.touch()
    jobs = FakeJobs(
        postprocess=PostProcessResult(
            utf8_error="encoding warning",
            clean_error="clean warning",
            sync_error="sync warning",
        )
    )
    emitted = []
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={Provider.OPENSUBTITLES: FakeAdapter()},
        coordinator=FakeAllProvidersCoordinator([result(candidate())]),
        jobs=jobs,
        emit=emitted.append,
    )

    summary = runner.run([media], "ar")

    assert summary.succeeded == 1
    assert summary.failed == 0
    assert all(any(error in message for message in emitted) for error in (
        "encoding warning",
        "clean warning",
        "sync warning",
    ))


def test_empty_adapters_returns_zero_attempt_summary(application_config):
    emitted = []
    runner = HeadlessAllProvidersRunner(
        application_config,
        adapters={},
        emit=emitted.append,
    )

    summary = runner.run(["movie.mkv"], "ar")

    assert summary == HeadlessBatchSummary(attempted=0, succeeded=0, failed=0)
    assert summary.exit_code == 1
    assert any("configured provider" in message.lower() for message in emitted)
