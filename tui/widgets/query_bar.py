"""Editable query with explicit search affordance and result feedback."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Static


class QueryBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("QUERY", id="query-label")
        yield Input(
            id="query-input",
            placeholder="Filename or a better title search…",
        )
        yield Static("", id="query-meta")

    def refresh_from_state(self, app) -> None:
        query = self.query_one("#query-input", Input)
        if not query.has_focus and query.value != app.query:
            query.value = app.query
        count = len(app.candidates)
        suffix = "" if count == 1 else "s"
        self.query_one("#query-meta", Static).update(
            "[green]● SEARCHING[/green]"
            if app.searching
            else f"{count} RESULT{suffix.upper()}"
        )
