"""QueryBar — shows the current filename + result count + hash badge."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Input

if TYPE_CHECKING:
    from tui.app import SubsApp


class QueryBar(Horizontal):
    """The query line: prefilled filename, result count, hash-match badge.

    Phase 2 keeps the input read-mostly (the SearchWorker searches the first
    media path automatically); the Input is editable so the user can re-query.
    Pressing Enter on the input re-runs the search.
    """

    def compose(self) -> ComposeResult:
        yield Static("[dim]query[/dim]", id="query-label")
        yield Input(id="query-input")
        yield Static("", id="query-meta")
        yield Static("", id="hash-badge")

    def refresh_from_state(self, app: "SubsApp") -> None:
        inp = self.query_one("#query-input", Input)
        # Only prefill if empty so we don't clobber the user mid-edit.
        if not inp.value:
            inp.value = app.query

        meta = self.query_one("#query-meta", Static)
        n = len(app.results)
        meta.update(
            f"[dim]{n} result{'s' if n != 1 else ''}[/dim]"
        )

        hash_badge = self.query_one("#hash-badge", Static)
        current = app.current_result()
        if current is not None and _has_hash(current):
            hash_badge.update("[b]● hash match found[/b]")
        else:
            hash_badge.update("")


def _has_hash(row: dict) -> bool:
    attrs = row.get("attributes", {}) or {}
    return bool(attrs.get("moviehash_match", False))
