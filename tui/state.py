"""AppState and friends — the single source of truth for the TUI.

Nothing here imports ``library/*`` (or ``download_subs``). This module is pure
data so it stays trivially unit-testable; the only layer that calls the backend
is ``tui.services``. Phase 1 uses plain dataclasses; Phase 2 wraps selected
fields in Textual ``reactive`` on the ``SubsApp``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class Backend(str, Enum):
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
CONCRETE_BACKENDS: List[Backend] = [
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
LANG_NATIVE_NAMES: Dict[str, str] = {
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
    ads_file_path: Optional[str] = None

    def validate(self) -> None:
        if self.audio_sync not in SYNC_POLICY_VALUES:
            raise ValueError(
                f"audio_sync must be one of {SYNC_POLICY_VALUES}, got {self.audio_sync!r}"
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
    latency_ms: Optional[int] = None
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
    candidates: List[dict] = field(default_factory=list)
    chosen: Optional[dict] = None
    error: Optional[str] = None
    progress: float = 0.0  # 0..1

    def is_done(self) -> bool:
        return self.status in ("done", "failed", "skipped")


@dataclass
class HistoryEntry:
    """A completed (or attempted) download, shown in the History tab."""

    media_path: str
    subtitle_path: Optional[str]
    release: str
    language: str
    backend: str
    cleaned: bool = False
    synced: bool = False
    sync_skipped: bool = False  # True when sync attempted but failed (no ffs)
    error: Optional[str] = None


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
    queue: List[QueueItem] = field(default_factory=list)
    cursor_index: int = 0
    history: List[HistoryEntry] = field(default_factory=list)
    engine_health: Dict[str, EngineHealth] = field(default_factory=dict)

    # Languages configured for this session: ISO code -> native name.
    # Seeded from config; the popover can add entries that persist on save.
    languages: Dict[str, str] = field(default_factory=lambda: {"en": "English"})

    # The currently-visible search results (already scored + sorted) plus the
    # score for each row's id, keyed by the candidate id.
    results: List[dict] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    last_error: Optional[str] = None  # backend/network failure surfaced to UI

    # Convenience helpers ---------------------------------------------------

    def current_item(self) -> Optional[QueueItem]:
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
