import asyncio

from tui.app import ConfirmReplace, ConfirmSync, SubsApp
from tui.domain import (
    Candidate,
    DownloadResult,
    PostProcessResult,
    Provider,
    QueueStatus,
)
from tui.search import CoordinatedSearchResult


class FakeCoordinator:
    def __init__(self, candidate):
        self.candidate = candidate

    def concrete(self, provider, request):
        return CoordinatedSearchResult(candidates=[self.candidate])


class FakeJobs:
    def __init__(self, *, error=None, conflict=False, crash=False):
        self.error = error
        self.conflict = conflict
        self.crash = crash
        self.overwrite_calls = []
        self.postprocess_calls = []

    def download(self, candidate, media_path, overwrite=False):
        self.overwrite_calls.append(overwrite)
        if self.crash:
            raise RuntimeError("backend exploded")
        if self.conflict and not overwrite:
            return DownloadResult(
                provider=candidate.provider,
                media_path=media_path,
                conflict_path=media_path.with_name("Movie.en.srt"),
            )
        if self.error:
            return DownloadResult(
                provider=candidate.provider,
                media_path=media_path,
                error=self.error,
            )
        return DownloadResult(
            provider=candidate.provider,
            media_path=media_path,
            subtitle_path=media_path.with_name("Movie.en.srt"),
        )

    def postprocess(self, download, **kwargs):
        self.postprocess_calls.append(kwargs)
        return PostProcessResult(cleaned=download.succeeded)


def _app(tmp_path, jobs, sync_policy=False):
    media = tmp_path / "Movie.mkv"
    media.touch()
    candidate = Candidate(
        provider=Provider.SUBDL,
        provider_id="77",
        release="Movie WEB-DL",
        language="en",
    )
    return SubsApp(
        config={
            "general": {
                "preferred_backend": "subdl",
                "skip_interactive_menu": True,
                "sync_audio_to_subs": sync_policy,
            },
            "subdl": {
                "api_key": "configured",
                "languages": {"English": "en"},
            },
        },
        media_paths=[str(media)],
        overrides={},
        coordinator=FakeCoordinator(candidate),
        jobs=jobs,
    )


def test_download_records_source_aware_history_and_completes_queue(tmp_path):
    app = _app(tmp_path, FakeJobs())

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_download_cursor()
            await pilot.pause(0.2)
            assert app.state.queue[0].status is QueueStatus.DONE
            assert app.state.history[0].provider is Provider.SUBDL
            assert app.state.history[0].postprocess.cleaned

    asyncio.run(run())


def test_download_failure_is_contained_and_visible(tmp_path):
    app = _app(tmp_path, FakeJobs(error="network down"))

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_download_cursor()
            await pilot.pause(0.2)
            assert app.state.queue[0].status is QueueStatus.FAILED
            assert "network down" in app.state.queue[0].error

    asyncio.run(run())


def test_download_exception_is_contained(tmp_path):
    app = _app(tmp_path, FakeJobs(crash=True))

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_download_cursor()
            await pilot.pause(0.2)
            assert app.state.queue[0].status is QueueStatus.FAILED
            assert "backend exploded" in app.state.queue[0].error

    asyncio.run(run())


def test_existing_subtitle_requires_replace_confirmation(tmp_path):
    jobs = FakeJobs(conflict=True)
    app = _app(tmp_path, jobs)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_download_cursor()
            await pilot.pause(0.2)
            assert isinstance(app.screen, ConfirmReplace)
            assert jobs.overwrite_calls == [False]
            await pilot.press("y")
            await pilot.pause(0.2)
            assert jobs.overwrite_calls == [False, True]
            assert app.state.queue[0].status is QueueStatus.DONE

    asyncio.run(run())


def test_ask_sync_policy_prompts_and_honors_choice(tmp_path):
    jobs = FakeJobs()
    app = _app(tmp_path, jobs, sync_policy="ask")

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_download_cursor()
            await pilot.pause(0.2)
            assert isinstance(app.screen, ConfirmSync)
            await pilot.press("n")
            await pilot.pause(0.2)
            assert jobs.postprocess_calls[-1]["sync"] is False
            assert app.state.queue[0].status is QueueStatus.DONE

    asyncio.run(run())
