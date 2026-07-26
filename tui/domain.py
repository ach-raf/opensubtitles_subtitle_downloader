"""Typed, provider-safe domain objects shared by the TUI layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class Provider(StrEnum):
    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    SUBSOURCE = "subsource"

    @property
    def label(self) -> str:
        return {
            Provider.OPENSUBTITLES: "OpenSubtitles",
            Provider.SUBDL: "SubDL",
            Provider.SUBSOURCE: "SubSource",
        }[self]


class EngineMode(StrEnum):
    ASK = "ask"
    AUTO = "auto"
    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    SUBSOURCE = "subsource"

    @property
    def provider(self) -> Provider | None:
        try:
            return Provider(self.value)
        except ValueError:
            return None

    @property
    def label(self) -> str:
        return self.provider.label if self.provider else self.value.title()


@dataclass(frozen=True)
class SearchRequest:
    media_path: Path | str
    query: str
    language: str
    hearing_impaired: str = "include"
    show_ai_translated: bool = True


@dataclass
class Candidate:
    provider: Provider
    provider_id: str
    release: str
    language: str
    download_ref: Any = field(default=None, repr=False)
    public_url: str | None = None
    download_count: int = 0
    hash_match: bool = False
    hearing_impaired: bool = False
    ai_translated: bool = False
    author: str = "Unknown"
    score: float = 0.0
    raw_flags: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def key(self) -> str:
        return f"{self.provider.value}:{self.provider_id}"

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "provider": self.provider.value,
            "provider_id": self.provider_id,
            "release": self.release,
            "language": self.language,
            "public_url": self.public_url,
            "download_count": self.download_count,
            "hash_match": self.hash_match,
            "hearing_impaired": self.hearing_impaired,
            "ai_translated": self.ai_translated,
            "author": self.author,
            "score": self.score,
        }


@dataclass
class ProviderSearchResult:
    provider: Provider
    candidates: list[Candidate] = field(default_factory=list)
    error: str | None = None


@dataclass
class DownloadResult:
    provider: Provider
    media_path: Path
    subtitle_path: Path | None = None
    error: str | None = None
    conflict_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        return self.subtitle_path is not None and self.error is None


@dataclass
class PostProcessResult:
    utf8_normalized: bool = False
    cleaned: bool = False
    synced: bool = False
    utf8_error: str | None = None
    clean_error: str | None = None
    sync_error: str | None = None


@dataclass
class HealthResult:
    provider: Provider
    configured: bool
    reachable: bool
    authenticated: bool | None = None
    latency_ms: int | None = None
    reason: str | None = None


class QueueStatus(StrEnum):
    QUEUED = "queued"
    SEARCHING = "searching"
    AWAITING_PICK = "awaiting_pick"
    DOWNLOADING = "downloading"
    POST_PROCESSING = "post_processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class QueueItem:
    key: str
    path: Path
    language: str
    engine_mode: EngineMode
    status: QueueStatus = QueueStatus.QUEUED
    candidate_keys: list[str] = field(default_factory=list)
    selected_candidate_key: str | None = None
    error: str | None = None


@dataclass
class HistoryEntry:
    item_key: str
    media_path: Path
    candidate_key: str
    provider: Provider
    language: str
    subtitle_path: Path | None
    postprocess: PostProcessResult
    error: str | None = None
