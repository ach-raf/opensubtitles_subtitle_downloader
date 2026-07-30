import asyncio
from threading import Event

from textual.widgets import RichLog, Static

from tui.app import ConfirmReplace, ConfirmSync, SubsApp, SyncProgress
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


class StreamingJobs(FakeJobs):
    def __init__(self):
        super().__init__()
        self.sync_started = Event()
        self.finish_sync = Event()

    def postprocess(self, download, **kwargs):
        self.postprocess_calls.append(kwargs)
        if kwargs["sync"]:
            kwargs["sync_output"]("extracting speech segments from reference...")
            self.sync_started.set()
            self.finish_sync.wait(timeout=3)
            kwargs["sync_output"]("...done")
        return PostProcessResult(
            cleaned=download.succeeded,
            synced=kwargs["sync"],
        )


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
    exits = []
    app.exit = lambda *args, **kwargs: exits.append(True)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_download_cursor()
            await pilot.pause(0.2)
            assert app.state.queue[0].status is QueueStatus.DONE
            assert app.state.history[0].provider is Provider.SUBDL
            assert app.state.history[0].postprocess.cleaned
            assert exits == [True]

    asyncio.run(run())


def test_download_failure_is_contained_and_visible(tmp_path):
    app = _app(tmp_path, FakeJobs(error="network down"))
    exits = []
    app.exit = lambda *args, **kwargs: exits.append(True)

    async def run():
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            app.action_download_cursor()
            await pilot.pause(0.2)
            assert app.state.queue[0].status is QueueStatus.FAILED
            assert "network down" in app.state.queue[0].error
            assert exits == []

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
            title = app.screen.query_one(Static)
            assert title.region.x > 0
            assert title.region.y > 0
            assert title.region.width < app.screen.region.width
            await pilot.press("n")
            await pilot.pause(0.2)
            assert jobs.postprocess_calls[-1]["sync"] is False
            assert app.state.queue[0].status is QueueStatus.DONE

    asyncio.run(run())


def test_sync_choice_shows_live_ffsubsync_output_until_user_closes_it(tmp_path):
    jobs = StreamingJobs()
    app = _app(tmp_path, jobs, sync_policy="ask")
    exits = []
    app.exit = lambda *args, **kwargs: exits.append(True)

    async def run():
        try:
            async with app.run_test(size=(118, 32)) as pilot:
                await pilot.pause(0.2)
                app.action_download_cursor()
                await pilot.pause(0.2)
                await pilot.press("y")

                for _ in range(20):
                    await pilot.pause(0.05)
                    if jobs.sync_started.is_set():
                        break

                assert jobs.sync_started.is_set()
                assert isinstance(app.screen, SyncProgress)
                assert app.state.queue[0].status is QueueStatus.POST_PROCESSING
                log = app.screen.query_one(RichLog)
                assert "extracting speech segments" in "\n".join(
                    line.text for line in log.lines
                )

                jobs.finish_sync.set()
                await pilot.pause(0.3)

                assert app.state.queue[0].status is QueueStatus.DONE
                assert isinstance(app.screen, SyncProgress)
                assert "Sync complete" in "\n".join(
                    line.text for line in log.lines
                )
                assert exits == []
                await pilot.press("enter")
                await pilot.pause()
                assert not isinstance(app.screen, SyncProgress)
                assert app._sync_progress is None
                assert exits == [True]
        finally:
            jobs.finish_sync.set()

    asyncio.run(run())
