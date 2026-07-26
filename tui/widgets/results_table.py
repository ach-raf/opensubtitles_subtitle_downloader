"""Typed subtitle candidate table."""

from textual.widgets import DataTable


class ResultsTable(DataTable):
    def __init__(self) -> None:
        super().__init__(id="results-table")
        self.cursor_type = "row"
        self._rendered_signature: tuple | None = None

    def on_mount(self) -> None:
        for label in ("#", "Release", "Lang", "Provider", "Flags", "D/L", "Match"):
            self.add_column(label)

    def refresh_from_state(self, app) -> None:
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
        for index, candidate in enumerate(app.candidates, 1):
            flags = []
            if candidate.hash_match:
                flags.append("HASH")
            if candidate.hearing_impaired:
                flags.append("HI")
            if candidate.ai_translated:
                flags.append("AI")
            self.add_row(
                str(index),
                candidate.release,
                candidate.language.upper(),
                candidate.provider.label,
                " · ".join(flags),
                _count(candidate.download_count),
                f"{candidate.score:.0f}",
                key=candidate.key,
            )
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


def _count(value: int) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)
