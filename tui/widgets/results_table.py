"""Typed subtitle candidate table."""

from rich.text import Text
from textual.widgets import DataTable


class ResultsTable(DataTable):
    def __init__(self) -> None:
        super().__init__(id="results-table")
        self.cursor_type = "row"
        self.cell_padding = 0
        self._rendered_signature: tuple | None = None
        self._rendered_merge_mode: bool | None = None

    def on_mount(self) -> None:
        self._set_columns(merge_mode=False)

    def refresh_from_state(self, app) -> None:
        if self._rendered_merge_mode is not app.merge_mode:
            self.clear(columns=True)
            self._set_columns(app.merge_mode)
            self._rendered_signature = None
        signature = tuple(
            (
                candidate.key,
                candidate.release,
                candidate.language,
                candidate.provider,
                candidate.hash_match,
                candidate.hearing_impaired,
                candidate.ai_translated,
                candidate.download_count,
                candidate.score,
            )
            for candidate in app.candidates
        )
        if signature == self._rendered_signature:
            self.sync_cursor(app.cursor_index)
            return
        self.clear()
        for candidate in app.candidates:
            flags = []
            if candidate.hash_match:
                flags.append("[blue]↓hash[/blue]")
            if candidate.hearing_impaired:
                flags.append("HI")
            if candidate.ai_translated:
                flags.append("[yellow]⚙AI[/yellow]")
            cells = [
                candidate.release,
                f" {candidate.language.upper()}",
                Text.from_markup(f" {' '.join(flags)}"),
                f" {_count(candidate.download_count)}",
                _score(candidate.score),
            ]
            if app.merge_mode:
                cells.insert(2, f" {candidate.provider.label}")
            self.add_row(*cells, key=candidate.key)
        self._rendered_signature = signature
        if self.row_count:
            self.sync_cursor(app.cursor_index)

    def sync_cursor(self, index: int) -> None:
        """Move the visual cursor without rebuilding candidate rows."""
        if not self.row_count:
            return
        row = min(max(index, 0), self.row_count - 1)
        if self.cursor_row != row:
            self.move_cursor(row=row)

    def _set_columns(self, merge_mode: bool) -> None:
        self.add_column("Release", width=66 if merge_mode else 75)
        self.add_column("L", width=3)
        if merge_mode:
            self.add_column("Source", width=9)
        self.add_column("Flags", width=6)
        self.add_column("D/L", width=6)
        self.add_column("S", width=3)
        self._rendered_merge_mode = merge_mode


def _count(value: int) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


def _score(value: float) -> Text:
    return Text.from_markup(f" [yellow]{value:.0f}[/yellow]")
