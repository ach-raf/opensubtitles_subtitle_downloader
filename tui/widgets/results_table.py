"""ResultsTable — DataTable of candidate subtitles, sorted by match score.

Columns: # | Release | L | Flags | D/L | Match (with score bar).
The cursor row is the source of truth for the DetailPane.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from textual.widgets import DataTable

if TYPE_CHECKING:
    from tui.app import SubsApp

# Columns shown in the table. The key is the column id; the value is its header label.
COLUMNS = [
    ("idx", "#"),
    ("release", "Release"),
    ("lang", "L"),
    ("flags", "Flags"),
    ("dl", "D/L"),
    ("match", "Match"),
]

# When merge_mode is on we also show which engine each row came from.
MERGE_COLUMN = ("source", "Source")


class ResultsTable(DataTable):
    """The candidate list, sorted by score descending.

    Cursor movement is delegated to DataTable's built-in j/k handling; the App
    adds j/k/Enter bindings that call ``move_cursor`` / read ``cursor_row``.
    """

    def __init__(self) -> None:
        super().__init__(id="results-table")
        self.cursor_type = "row"
        self.zebra_stripes = False

    def on_mount(self) -> None:
        for key, label in COLUMNS:
            self.add_column(label, key=key)
        # Merge-mode Source column is added/removed dynamically.

    def refresh_from_state(self, app: "SubsApp") -> None:
        results: List[dict] = app.results
        scores = app.scores

        # Reconcile the Source column with merge_mode.
        self._sync_source_column(app.merge_mode)

        self.clear()
        if not results:
            return

        for i, row in enumerate(results, start=1):
            attrs = row.get("attributes", {}) or {}
            rid = row.get("id", "")
            release = attrs.get("release", "") or ""
            language = (attrs.get("language", "") or "").upper()
            flags = _flags_markup(attrs, row.get("_score") or scores.get(str(rid)) or 0)
            dl = _download_count(attrs.get("download_count", 0))
            score = row.get("_score") or scores.get(str(rid)) or 0
            match = _match_markup(score)
            values = [str(i), release, language, flags, dl, match]
            if app.merge_mode:
                values.append(_source_markup(row.get("_source", "")))
            self.add_row(*values, key=str(rid))

        # Restore the cursor if it's still in range.
        cursor = app.cursor_index
        if cursor >= len(results):
            cursor = max(0, len(results) - 1)
            app.cursor_index = cursor
        if 0 <= cursor < self.row_count:
            try:
                self.move_cursor(row=cursor)
            except Exception:
                pass

    def _sync_source_column(self, merge_mode: bool) -> None:
        has_source = MERGE_COLUMN[0] in {c.key for c in self.columns.values()}
        if merge_mode and not has_source:
            self.add_column(MERGE_COLUMN[1], key=MERGE_COLUMN[0])
        elif not merge_mode and has_source:
            try:
                self.remove_column(MERGE_COLUMN[0])
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Cell formatters
# --------------------------------------------------------------------------- #
def _flags_markup(attrs: dict, score: float) -> str:
    """Build the Flags cell: hash badge, quality tags, AI/machine-tr marker."""
    parts: List[str] = []
    if attrs.get("moviehash_match"):
        parts.append("[#6f86d6]⤓hash[/]")
    # Quality tags scraped from the release name.
    release = (attrs.get("release", "") or "").lower()
    for tag in ("1080p", "2160p", "4k", "720p", "webdl", "webrip", "bluray", "bd"):
        if tag in release:
            parts.append(tag.upper() if tag in ("1080p", "720p", "2160p") else tag.capitalize())
            if tag in ("1080p", "720p", "2160p", "bluray", "bd"):
                break
    if attrs.get("ai_translated") or attrs.get("machine_translated"):
        parts.append("[#d9a441]⚙AI[/]")
    return " ".join(parts) if parts else ""


def _download_count(count: Any) -> str:
    """Human-readable download count: 48000 -> '48k'."""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return "—"
    if n >= 1000:
        return f"{n // 1000}k"
    return str(n)


def _match_markup(score: float) -> str:
    """Score number + a short bar drawn from block chars (no widget needed)."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        s = 0.0
    s = max(0.0, min(100.0, s))
    # 8-cell bar; each cell ~12.5%. Use partial-block unicode for sub-steps.
    filled = int(round(s / 100 * 8))
    bar = "█" * filled + "░" * (8 - filled)
    return f"[#d9a441]{bar}[/] {int(s)}"


def _source_markup(source: str) -> str:
    return {"opensubtitles": "OS", "subdl": "SD", "subsource": "SS"}.get(source, source or "—")
