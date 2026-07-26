"""AppState and friends — the single source of truth for the TUI.

Nothing here imports ``library/*`` (or ``download_subs``). This module is pure
data so it stays trivially unit-testable; the only layer that calls the backend
is the provider adapter layer. Legacy compatibility objects remain below while
the production application uses ``SessionState``.
fields in Textual ``reactive`` on the ``SubsApp``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tui.config import ApplicationConfig
from tui.domain import (
    Candidate,
    EngineMode,
)
from tui.domain import (
    HistoryEntry as DomainHistoryEntry,
)
from tui.domain import (
    QueueItem as DomainQueueItem,
)
from tui.domain import (
    QueueStatus as DomainQueueStatus,
)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class Backend(StrEnum):
    """The concrete subtitle engines the TUI can drive, plus ``AUTO``.

    Inherits ``str`` so ``Backend.OPENSUBTITLES == "opensubtitles"`` and the
    value serializes straight into config / argparse.
    """

    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    SUBSOURCE = "subsource"
    AUTO = "auto"

    @property
    def label(self) -> str:
        return {
            Backend.OPENSUBTITLES: "OpenSubtitles",
            Backend.SUBDL: "SubDL",
            Backend.SUBSOURCE: "SubSource",
            Backend.AUTO: "Auto",
        }[self]


# All engines the engine switcher can fan out to (excludes AUTO).
CONCRETE_BACKENDS: list[Backend] = [
    Backend.OPENSUBTITLES,
    Backend.SUBDL,
    Backend.SUBSOURCE,
]


# --------------------------------------------------------------------------- #
# Language native names
# --------------------------------------------------------------------------- #
# Keyed by ISO-639-1 code. Used by the language popover so the user picks
# "العربية" not "Arabic". Falls back to the code itself if absent. This is a
# small curated map; users can add languages by ISO code in the popover and
# those persist to config.yaml on the next save (see ConfigIO).
LANG_NATIVE_NAMES: dict[str, str] = {
    "en": "English",
    "ar": "العربية",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "es": "Español",
    "de": "Deutsch",
    "it": "Italiano",
    "pt": "Português",
    "pt-br": "Português (Brasil)",
    "ru": "Русский",
    "hi": "हिन्दी",
    "tr": "Türkçe",
    "pl": "Polski",
    "nl": "Nederlands",
    "id": "Bahasa Indonesia",
    "vi": "Tiếng Việt",
    "th": "ไทย",
    "sv": "Svenska",
    "da": "Dansk",
    "fi": "Suomi",
    "no": "Norsk",
    "cs": "Čeština",
    "el": "Ελληνικά",
    "he": "עברית",
    "hu": "Magyar",
    "ro": "Română",
    "uk": "Українська",
    "ms": "Melayu",
    "bn": "বাংলা",
    "fa": "فارسی",
    "ur": "اردو",
    "ta": "தமிழ்",
    "te": "తెలుగు",
    "tl": "Tagalog",
}


def native_name(code: str) -> str:
    """Return the native-script name for an ISO code, or the code itself."""
    if not code:
        return ""
    return LANG_NATIVE_NAMES.get(code.lower(), code)


# --------------------------------------------------------------------------- #
# Run policy
# --------------------------------------------------------------------------- #
# The config stores sync_audio_to_subs as true/false/ask. The TUI's richer
# policy maps that onto always/never/ask so the toast's auto-pick rule can
# decide deterministically.
SYNC_POLICY_VALUES = ("always", "never", "ask")
HI_POLICY_VALUES = ("include", "exclude", "only")


@dataclass
class RunPolicy:
    """Post-download + search-time behaviour, mirrored 1:1 to config.yaml."""

    force_utf8: bool = True
    clean_ads: bool = True
    audio_sync: str = "ask"  # always | never | ask
    hearing_impaired: str = "exclude"  # include | exclude | only
    auto_select: bool = False
    show_ai_translated: bool = True
    hash_match_first: bool = True
    alt_name_search: bool = True
    ads_file_path: str | None = None

    def validate(self) -> None:
        if self.audio_sync not in SYNC_POLICY_VALUES:
            raise ValueError(
                f"audio_sync must be one of {SYNC_POLICY_VALUES}, "
                f"got {self.audio_sync!r}"
            )
        if self.hearing_impaired not in HI_POLICY_VALUES:
            raise ValueError(
                f"hearing_impaired must be one of {HI_POLICY_VALUES}, "
                f"got {self.hearing_impaired!r}"
            )


# --------------------------------------------------------------------------- #
# Engine health
# --------------------------------------------------------------------------- #
@dataclass
class EngineHealth:
    """One engine's availability + latency, as probed by HealthProbe."""

    name: str
    online: bool = False
    latency_ms: int | None = None
    degraded: bool = False
    last_checked: float = 0.0  # epoch seconds; 0 == never probed

    @property
    def badge(self) -> str:
        """Single-word status for the engine switcher badge."""
        if self.degraded:
            return "degraded"
        return "online" if self.online else "offline"


# --------------------------------------------------------------------------- #
# Queue + history
# --------------------------------------------------------------------------- #
QueueStatus = str  # see VALID_QUEUE_STATUSES for the allowed literals
VALID_QUEUE_STATUSES = (
    "queued",
    "searching",
    "awaiting_pick",
    "downloading",
    "post",
    "done",
    "failed",
    "skipped",
)

# Statuses that mean the file still needs work (drives the language scope rule).
NON_DONE_STATUSES = frozenset(
    {"queued", "searching", "awaiting_pick", "downloading", "post"}
)


@dataclass
class QueueItem:
    """One media file moving through the pipeline."""

    path: str
    name: str  # display name (may be Arabic/CJK)
    status: QueueStatus = "queued"
    candidates: list[dict] = field(default_factory=list)
    chosen: dict | None = None
    error: str | None = None
    progress: float = 0.0  # 0..1

    def is_done(self) -> bool:
        return self.status in ("done", "failed", "skipped")


@dataclass
class HistoryEntry:
    """A completed (or attempted) download, shown in the History tab."""

    media_path: str
    subtitle_path: str | None
    release: str
    language: str
    backend: str
    cleaned: bool = False
    synced: bool = False
    sync_skipped: bool = False  # True when sync attempted but failed (no ffs)
    error: str | None = None


# --------------------------------------------------------------------------- #
# AppState
# --------------------------------------------------------------------------- #
@dataclass
class AppState:
    """The single source of truth.

    Phase 1 keeps this as a plain dataclass. Phase 2 promotes selected fields to
    Textual ``reactive`` on ``SubsApp`` so the UI re-renders on mutation; the
    shape and field names stay identical.
    """

    backend: Backend = Backend.OPENSUBTITLES
    language: str = "en"
    merge_mode: bool = False
    run_policy: RunPolicy = field(default_factory=RunPolicy)

    query: str = ""
    queue: list[QueueItem] = field(default_factory=list)
    cursor_index: int = 0
    history: list[HistoryEntry] = field(default_factory=list)
    engine_health: dict[str, EngineHealth] = field(default_factory=dict)

    # Languages configured for this session: ISO code -> native name.
    # Seeded from config; the popover can add entries that persist on save.
    languages: dict[str, str] = field(default_factory=lambda: {"en": "English"})

    # The currently-visible search results (already scored + sorted) plus the
    # score for each row's id, keyed by the candidate id.
    results: list[dict] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    last_error: str | None = None  # backend/network failure surfaced to UI

    # Convenience helpers ---------------------------------------------------

    def current_item(self) -> QueueItem | None:
        """The queue entry the user is currently interacting with, if any."""
        non_done = [it for it in self.queue if not it.is_done()]
        return non_done[0] if non_done else (self.queue[0] if self.queue else None)

    def remaining_count(self) -> int:
        """How many queue items still need work (drives the scope rule)."""
        return sum(1 for it in self.queue if not it.is_done())

    def needs_language_scope_confirm(self) -> bool:
        """True when a language change must prompt for scope.

        Per spec §6.2: only when more than one non-done item is queued. A
        single-file run changes language instantly with no prompt.
        """
        return self.remaining_count() > 1

    def reset_for_research(self) -> None:
        """Clear the visible results/scores/cursor; called when language or
        engine changes so the table re-fetches."""
        self.results = []
        self.scores = {}
        self.cursor_index = 0


class InvalidTransition(RuntimeError):
    """The requested queue mutation is invalid for the item's status."""


@dataclass
class SessionState:
    """Explicit session choices and validated queue progression."""

    engine_mode: EngineMode = EngineMode.ASK
    language: str = "en"
    queue: list[DomainQueueItem] = field(default_factory=list)
    history: list[DomainHistoryEntry] = field(default_factory=list)
    candidates: dict[str, Candidate] = field(default_factory=dict)
    active_view: str = "search"
    language_confirmed: bool = True

    @classmethod
    def from_config(
        cls,
        config: ApplicationConfig,
        queue: list[DomainQueueItem] | None = None,
    ) -> SessionState:
        mode = config.general.preferred_backend
        language = "en"
        ordered_providers = (
            [mode.provider] if mode.provider is not None else list(config.providers)
        )
        for provider in ordered_providers:
            languages = config.providers[provider].languages
            if languages:
                language = next(iter(languages.values()))
                break
        return cls(
            engine_mode=mode,
            language=language,
            queue=list(queue or []),
            language_confirmed=config.general.skip_interactive_menu,
        )

    @property
    def needs_engine_setup(self) -> bool:
        return self.engine_mode is EngineMode.ASK

    @property
    def needs_language_setup(self) -> bool:
        return not self.needs_engine_setup and not self.language_confirmed

    @property
    def active_item(self) -> DomainQueueItem | None:
        return next(
            (
                item
                for item in self.queue
                if item.status
                not in {
                    DomainQueueStatus.DONE,
                    DomainQueueStatus.FAILED,
                    DomainQueueStatus.SKIPPED,
                }
            ),
            None,
        )

    def choose_engine(
        self,
        mode: EngineMode,
        scope: str = "remaining",
    ) -> None:
        if mode is EngineMode.ASK:
            raise ValueError("ASK is a startup prompt, not a concrete choice")
        self.engine_mode = mode
        for item in self._scoped_items(scope):
            item.engine_mode = mode

    def set_language(self, code: str, scope: str = "remaining") -> None:
        normalized = code.strip().lower()
        if not normalized:
            raise ValueError("Language code cannot be empty")
        self.language = normalized
        self.language_confirmed = True
        for item in self._scoped_items(scope):
            item.language = normalized

    def begin_search(self, item_key: str) -> None:
        item = self._item(item_key)
        self._require(item, {DomainQueueStatus.QUEUED})
        item.status = DomainQueueStatus.SEARCHING
        item.error = None

    def set_candidates(
        self,
        item_key: str,
        candidates: list[Candidate],
    ) -> None:
        item = self._item(item_key)
        self._require(item, {DomainQueueStatus.SEARCHING})
        for candidate in candidates:
            self.candidates[candidate.key] = candidate
        item.candidate_keys = [candidate.key for candidate in candidates]
        item.status = DomainQueueStatus.AWAITING_PICK

    def restart_search(self, item_key: str) -> None:
        """Invalidate a queued/search result after its search inputs change."""
        item = self._item(item_key)
        self._require(
            item,
            {
                DomainQueueStatus.QUEUED,
                DomainQueueStatus.SEARCHING,
                DomainQueueStatus.AWAITING_PICK,
            },
        )
        item.status = DomainQueueStatus.QUEUED
        item.error = None
        item.candidate_keys.clear()
        item.selected_candidate_key = None

    def begin_download(
        self,
        item_key: str,
        candidate_key: str,
    ) -> None:
        item = self._item(item_key)
        self._require(item, {DomainQueueStatus.AWAITING_PICK})
        if candidate_key not in item.candidate_keys:
            raise InvalidTransition(
                f"Candidate {candidate_key!r} does not belong to {item_key!r}"
            )
        item.selected_candidate_key = candidate_key
        item.status = DomainQueueStatus.DOWNLOADING

    def begin_postprocess(self, item_key: str) -> None:
        item = self._item(item_key)
        self._require(item, {DomainQueueStatus.DOWNLOADING})
        item.status = DomainQueueStatus.POST_PROCESSING

    def mark_complete(
        self,
        item_key: str,
        history: DomainHistoryEntry,
    ) -> None:
        item = self._item(item_key)
        self._require(
            item,
            {
                DomainQueueStatus.AWAITING_PICK,
                DomainQueueStatus.DOWNLOADING,
                DomainQueueStatus.POST_PROCESSING,
            },
        )
        item.status = DomainQueueStatus.DONE
        item.error = None
        self.history.append(history)

    def mark_failed(self, item_key: str, error: str) -> None:
        item = self._item(item_key)
        if item.status in {
            DomainQueueStatus.DONE,
            DomainQueueStatus.SKIPPED,
        }:
            raise InvalidTransition(f"Cannot fail an item in {item.status.value}")
        item.status = DomainQueueStatus.FAILED
        item.error = error

    def retry(self, item_key: str) -> None:
        item = self._item(item_key)
        self._require(
            item,
            {DomainQueueStatus.FAILED, DomainQueueStatus.SKIPPED},
        )
        item.status = DomainQueueStatus.QUEUED
        item.error = None
        item.candidate_keys.clear()
        item.selected_candidate_key = None

    def skip(self, item_key: str) -> None:
        item = self._item(item_key)
        if item.status in {
            DomainQueueStatus.DONE,
            DomainQueueStatus.FAILED,
            DomainQueueStatus.SKIPPED,
        }:
            raise InvalidTransition(f"Cannot skip an item in {item.status.value}")
        item.status = DomainQueueStatus.SKIPPED

    def _item(self, item_key: str) -> DomainQueueItem:
        for item in self.queue:
            if item.key == item_key:
                return item
        raise KeyError(item_key)

    def _scoped_items(self, scope: str) -> list[DomainQueueItem]:
        if scope == "current":
            return [self.active_item] if self.active_item else []
        if scope != "remaining":
            raise ValueError("scope must be 'current' or 'remaining'")
        return [
            item
            for item in self.queue
            if item.status
            not in {
                DomainQueueStatus.DONE,
                DomainQueueStatus.FAILED,
                DomainQueueStatus.SKIPPED,
            }
        ]

    @staticmethod
    def _require(
        item: DomainQueueItem,
        allowed: set[DomainQueueStatus],
    ) -> None:
        if item.status not in allowed:
            expected = ", ".join(status.value for status in allowed)
            raise InvalidTransition(
                f"{item.key!r} is {item.status.value}; expected {expected}"
            )
