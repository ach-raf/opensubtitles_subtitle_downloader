"""Source-aware download staging and truthful post-processing."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from tui.domain import (
    Candidate,
    DownloadResult,
    PostProcessResult,
    Provider,
)
from tui.providers.base import ProviderAdapter


class SubtitleCleaner:
    def clean(
        self,
        subtitle_path: Path,
        ads_path: Path | None = None,
    ) -> bool:
        from library.subtitle_utils import SubtitleUtils

        return SubtitleUtils().clean_subtitles_strict(
            subtitle_path,
            ads_path=ads_path,
        )


class SubtitleSynchronizer:
    def sync(
        self,
        media_path: Path,
        subtitle_path: Path,
        on_output: Callable[[str], None] | None = None,
    ) -> bool:
        from library.subtitle_utils import SubtitleUtils

        return SubtitleUtils().sync_subtitles_strict(
            media_path,
            subtitle_path,
            on_output=on_output,
        )


class JobCoordinator:
    def __init__(
        self,
        adapters: dict[Provider, ProviderAdapter],
        *,
        cleaner: Any | None = None,
        synchronizer: Any | None = None,
        output_directory: str | Path | None = None,
    ) -> None:
        self.adapters = adapters
        self.cleaner = cleaner or SubtitleCleaner()
        self.synchronizer = synchronizer or SubtitleSynchronizer()
        self.output_directory = (
            Path(output_directory) if output_directory is not None else None
        )

    def download(
        self,
        candidate: Candidate,
        media_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> DownloadResult:
        media = Path(media_path)
        adapter = self.adapters.get(candidate.provider)
        if adapter is None:
            return DownloadResult(
                provider=candidate.provider,
                media_path=media,
                error=f"{candidate.provider.label} is not configured",
            )

        destination = self.output_directory or media.parent
        if self.output_directory is not None:
            try:
                destination.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return DownloadResult(
                    provider=candidate.provider,
                    media_path=media,
                    error=f"Could not create subtitle output directory: {exc}",
                )

        expected_target = destination / f"{media.stem}.{candidate.language}.srt"
        if expected_target.exists() and not overwrite:
            return DownloadResult(
                provider=candidate.provider,
                media_path=media,
                conflict_path=expected_target,
            )

        try:
            return self._stage_download(
                adapter,
                candidate,
                media,
                destination,
                overwrite,
            )
        except OSError as exc:
            return DownloadResult(
                provider=candidate.provider,
                media_path=media,
                error=f"Could not write subtitle output: {exc}",
            )

    @staticmethod
    def _stage_download(
        adapter: ProviderAdapter,
        candidate: Candidate,
        media: Path,
        destination: Path,
        overwrite: bool,
    ) -> DownloadResult:
        with TemporaryDirectory(
            prefix=".subtitle-download-",
            dir=destination,
        ) as temporary:
            staging_media = Path(temporary) / media.name
            staged = adapter.download(candidate, staging_media)
            if not staged.succeeded or staged.subtitle_path is None:
                return DownloadResult(
                    provider=candidate.provider,
                    media_path=media,
                    error=staged.error or "Subtitle download failed",
                )
            staged_path = staged.subtitle_path.resolve()
            staging_root = Path(temporary).resolve()
            if staged_path.parent != staging_root:
                return DownloadResult(
                    provider=candidate.provider,
                    media_path=media,
                    error="Provider wrote outside the download staging directory",
                )

            target = destination / staged_path.name
            if target.exists() and not overwrite:
                return DownloadResult(
                    provider=candidate.provider,
                    media_path=media,
                    conflict_path=target,
                )
            os.replace(staged_path, target)
            return DownloadResult(
                provider=candidate.provider,
                media_path=media,
                subtitle_path=target,
            )

    def postprocess(
        self,
        download: DownloadResult,
        *,
        force_utf8: bool = False,
        clean: bool,
        sync: bool,
        ads_path: Path | None = None,
        sync_output: Callable[[str], None] | None = None,
    ) -> PostProcessResult:
        result = PostProcessResult()
        if not download.succeeded or download.subtitle_path is None:
            return result
        if force_utf8:
            try:
                self._normalize_utf8(download.subtitle_path)
                result.utf8_normalized = True
            except Exception as exc:
                result.utf8_error = str(exc)
        if clean:
            try:
                cleaned = self.cleaner.clean(
                    download.subtitle_path,
                    ads_path=ads_path,
                )
                if cleaned is not True:
                    raise RuntimeError("Cleaner did not report success")
                result.cleaned = True
            except Exception as exc:
                result.clean_error = str(exc)
        if sync:
            try:
                synced = self.synchronizer.sync(
                    download.media_path,
                    download.subtitle_path,
                    on_output=sync_output,
                )
                if synced is not True:
                    raise RuntimeError("Synchronizer did not report success")
                result.synced = True
            except Exception as exc:
                result.sync_error = str(exc)
        return result

    @staticmethod
    def _normalize_utf8(subtitle_path: Path) -> None:
        data = subtitle_path.read_bytes()
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = data.decode("utf-16")
        else:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("cp1252")
        temporary = subtitle_path.with_name(f".{subtitle_path.name}.utf8.tmp")
        try:
            temporary.write_text(text, encoding="utf-8", newline="\n")
            os.replace(temporary, subtitle_path)
        finally:
            if temporary.exists():
                temporary.unlink()
