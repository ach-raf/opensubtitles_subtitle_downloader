"""Non-interactive all-provider search and download coordination."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tui.config import ApplicationConfig
from tui.domain import Provider, SearchRequest
from tui.jobs import JobCoordinator
from tui.providers.base import ProviderAdapter
from tui.search import SearchCoordinator


@dataclass(frozen=True)
class HeadlessBatchSummary:
    attempted: int
    succeeded: int
    failed: int

    @property
    def exit_code(self) -> int:
        return 0 if self.succeeded else 1


class HeadlessAllProvidersRunner:
    def __init__(
        self,
        config: ApplicationConfig,
        adapters: dict[Provider, ProviderAdapter],
        *,
        coordinator: SearchCoordinator | None = None,
        jobs: JobCoordinator | None = None,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self.adapters = adapters
        self.coordinator = coordinator or SearchCoordinator(adapters)
        self.jobs = jobs or JobCoordinator(
            adapters,
            output_directory=config.general.subtitle_output_directory or None,
        )
        self.emit = emit or print

    def run(
        self,
        media_paths: list[str | Path],
        language: str,
    ) -> HeadlessBatchSummary:
        if not self.adapters:
            self.emit(
                "Error: No configured provider is available. "
                "Add provider credentials to the configuration file."
            )
            return HeadlessBatchSummary(0, 0, 0)

        attempted = 0
        succeeded = 0
        sync_policy = self.config.general.sync_audio_to_subs
        if sync_policy == "ask":
            self.emit(
                "Notice: subtitle sync requires confirmation and is skipped "
                "in no-TUI mode."
            )

        for media_path in media_paths:
            media = Path(media_path)
            attempted += 1
            try:
                request = SearchRequest(
                    media_path=media,
                    query=media.stem,
                    language=language,
                    hearing_impaired=self.config.general.hearing_impaired,
                    show_ai_translated=self.config.general.show_ai_translated,
                )
                result = self.coordinator.all_providers(request)
                for provider, error in result.errors.items():
                    self.emit(f"Warning: {provider.label}: {error}")

                if not result.candidates:
                    self.emit(f"Error: No subtitles found for {media}.")
                    continue

                download = self.jobs.download(result.candidates[0], media)
                if download.conflict_path is not None:
                    self.emit(
                        f"Error: Subtitle already exists: {download.conflict_path}"
                    )
                    continue
                if not download.succeeded:
                    self.emit(
                        f"Error: Could not download subtitles for {media}: "
                        f"{download.error or 'download failed'}"
                    )
                    continue

                postprocess = self.jobs.postprocess(
                    download,
                    force_utf8=self.config.general.opt_force_utf8,
                    clean=self.config.cleaning.enabled,
                    sync=sync_policy == "always",
                    ads_path=self.config.cleaning.ads_file_path,
                )
                for warning in (
                    postprocess.utf8_error,
                    postprocess.clean_error,
                    postprocess.sync_error,
                ):
                    if warning:
                        self.emit(f"Warning: {warning}")
                succeeded += 1
            except Exception as exc:
                self.emit(
                    f"Error: Could not process {media}: "
                    f"{type(exc).__name__}: {exc}"
                )

        return HeadlessBatchSummary(
            attempted=attempted,
            succeeded=succeeded,
            failed=attempted - succeeded,
        )
