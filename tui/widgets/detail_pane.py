"""DetailPane — rich preview of the cursor row + action buttons (static labels)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

if TYPE_CHECKING:
    from tui.app import SubsApp


class DetailPane(VerticalScroll):
    """Preview of the currently-highlighted result row.

    Action buttons are rendered as styled labels in Phase 2 (clickable buttons
    + keybindings wired in Phase 4 alongside the download worker).
    """

    def compose(self) -> ComposeResult:
        yield Static("[dim]preview[/dim]", classes="panel-h", markup=True)
        yield Static("[dim]select a row[/dim]", id="detail-title", markup=True)
        yield Static("", id="detail-movie", markup=True)
        yield Static("", id="detail-kv", markup=True)
        yield Static("", id="detail-actions", markup=True)

    def refresh_from_state(self, app: "SubsApp") -> None:
        row = app.current_result()
        title = self.query_one("#detail-title", Static)
        movie = self.query_one("#detail-movie", Static)
        kv = self.query_one("#detail-kv", Static)
        actions = self.query_one("#detail-actions", Static)

        if row is None:
            title.update("[dim]no row selected[/dim]")
            movie.update("")
            kv.update("")
            actions.update("")
            return

        attrs = row.get("attributes", {}) or {}
        release = attrs.get("release", "") or "(no release)"
        title.update(f"[b]{release}[/b]")

        # Movie name from feature_details if present (OpenSubtitles), else blank.
        feature = attrs.get("feature_details", {}) or {}
        movie_name = feature.get("movie_name", "") if isinstance(feature, dict) else ""
        movie.update(movie_name)

        kv.update(self._kv_markup(row, attrs))
        actions.update(
            "[b][#4ddb9a]Download[/b] [dim]↵[/dim]   "
            "[dim]Preview p · Copy URL y[/dim]"
        )

    @staticmethod
    def _kv_markup(row: dict, attrs: dict) -> str:
        language = (attrs.get("language", "") or "").lower()
        uploader = attrs.get("author") or attrs.get("uploader") or "Unknown"
        dl = attrs.get("download_count", 0)
        hash_match = bool(attrs.get("moviehash_match", False))
        machine = bool(attrs.get("ai_translated") or attrs.get("machine_translated"))

        hash_line = (
            "[#4ddb9a]✔ yes — exact file[/]" if hash_match else "[dim]no[/]"
        )
        machine_line = "[#d9a441]yes[/]" if machine else "[dim]no[/]"

        return (
            f"[dim]Language[/dim]   {language}\n"
            f"[dim]Uploader[/dim]   {uploader} · {dl} downloads\n"
            f"[dim]Hash match[/dim] {hash_line}\n"
            f"[dim]Machine tr.[/dim] {machine_line}"
        )
