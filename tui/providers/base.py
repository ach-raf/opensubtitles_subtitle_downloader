"""Provider boundary: normalization, redaction, and typed failure handling."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

from tui.domain import (
    Candidate,
    DownloadResult,
    HealthResult,
    Provider,
    ProviderSearchResult,
    SearchRequest,
)

SENSITIVE_QUERY_KEYS = {
    "api_key",
    "apikey",
    "token",
    "key",
    "authorization",
    "signature",
}
LANGUAGE_ALIASES = {
    "arabic": "ar",
    "english": "en",
    "french": "fr",
    "german": "de",
    "japanese": "ja",
    "spanish": "es",
    "portuguese": "pt",
    "brazilian_portuguese": "pt-br",
    "chinese": "zh",
    "korean": "ko",
    "russian": "ru",
}


class ProviderRequestError(RuntimeError):
    """A provider request failed rather than returning a valid empty result."""


def redact_secrets(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)\b(api[_-]?key|token|authorization|signature|key)" r"=([^&\s]+)",
        r"\1=[redacted]",
        text,
    )
    return re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [redacted]",
        text,
    )


class ProviderAdapter(Protocol):
    provider: Provider

    def search(self, request: SearchRequest) -> ProviderSearchResult: ...

    def download(self, candidate: Candidate, media_path: Path) -> DownloadResult: ...

    def health(self) -> HealthResult: ...


def public_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
    return None if keys & SENSITIVE_QUERY_KEYS else url


def normalize_language(
    language: str, language_aliases: Mapping[str, str] | None = None
) -> str:
    normalized = language.strip().lower().replace(" ", "_")
    aliases = {**LANGUAGE_ALIASES, **(language_aliases or {})}
    return aliases.get(normalized, normalized)


def candidate_from_standardized(
    provider: Provider,
    row: dict[str, Any],
    *,
    language_aliases: Mapping[str, str] | None = None,
) -> Candidate:
    attributes = row.get("attributes") or {}
    provider_id = str(row.get("id") or "")
    if not provider_id:
        identity = (
            f"{attributes.get('release', '')}|"
            f"{attributes.get('language', '')}|"
            f"{attributes.get('url', '')}"
        )
        fingerprint = sha256(identity.encode()).hexdigest()[:16]
        provider_id = f"fingerprint-{fingerprint}"
    url = attributes.get("public_url") or attributes.get("url")
    return Candidate(
        provider=provider,
        provider_id=provider_id,
        release=str(
            attributes.get("release")
            or attributes.get("release_name")
            or row.get("release")
            or ""
        ),
        language=normalize_language(
            str(attributes.get("language") or ""),
            language_aliases,
        ),
        download_ref=copy.deepcopy(row),
        public_url=public_url(str(url)) if url else None,
        download_count=int(attributes.get("download_count") or 0),
        hash_match=bool(
            attributes.get("moviehash_match") or attributes.get("hash_match")
        ),
        hearing_impaired=bool(
            attributes.get("hi") or attributes.get("hearing_impaired")
        ),
        ai_translated=bool(
            attributes.get("ai_translated") or attributes.get("machine_translated")
        ),
        author=str(attributes.get("author") or "Unknown"),
    )


class StandardProviderAdapter:
    provider: Provider
    language_aliases: Mapping[str, str] = {}

    def __init__(self, client: Any) -> None:
        self.client = client

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        try:
            rows = self.client.search_candidates(
                Path(request.media_path),
                request.language,
                request.query,
            )
            candidates = [
                candidate_from_standardized(
                    self.provider,
                    row,
                    language_aliases=self.language_aliases,
                )
                for row in rows
            ]
        except Exception as exc:
            return ProviderSearchResult(
                provider=self.provider,
                error=redact_secrets(f"{type(exc).__name__}: {exc}"),
            )
        return ProviderSearchResult(
            provider=self.provider,
            candidates=candidates,
        )

    def health(self) -> HealthResult:
        configured = bool(getattr(self.client, "api_key", True))
        checker = getattr(self.client, "health", None)
        if checker is None:
            return HealthResult(
                provider=self.provider,
                configured=configured,
                reachable=False,
                reason="Not checked",
            )
        try:
            value = checker()
        except Exception as exc:
            return HealthResult(
                provider=self.provider,
                configured=configured,
                reachable=False,
                reason=redact_secrets(exc),
            )
        if isinstance(value, HealthResult):
            return value
        return HealthResult(
            provider=self.provider,
            configured=configured,
            reachable=bool(value),
        )

    def _invalid_candidate(
        self, candidate: Candidate, media_path: Path
    ) -> DownloadResult | None:
        if candidate.provider is self.provider:
            return None
        return DownloadResult(
            provider=self.provider,
            media_path=media_path,
            error=(
                f"Candidate belongs to {candidate.provider.label}, "
                f"not {self.provider.label}"
            ),
        )
