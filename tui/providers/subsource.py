"""SubSource adapter."""

from pathlib import Path

from tui.domain import Candidate, DownloadResult, Provider
from tui.providers.base import StandardProviderAdapter, redact_secrets


class SubSourceAdapter(StandardProviderAdapter):
    provider = Provider.SUBSOURCE

    def download(self, candidate: Candidate, media_path: Path) -> DownloadResult:
        invalid = self._invalid_candidate(candidate, media_path)
        if invalid:
            return invalid
        try:
            path = self.client.download_single_subtitle(
                candidate.download_ref,
                media_path,
                candidate.language,
            )
        except Exception as exc:
            return DownloadResult(
                provider=self.provider,
                media_path=media_path,
                error=redact_secrets(f"{type(exc).__name__}: {exc}"),
            )
        return DownloadResult(
            provider=self.provider,
            media_path=media_path,
            subtitle_path=Path(path) if path else None,
            error=None if path else "Provider did not produce a subtitle file",
        )
