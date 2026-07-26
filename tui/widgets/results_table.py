"""Typed subtitle candidate table."""

from textual.widgets import DataTable


class ResultsTable(DataTable):
    def __init__(self) -> None:
        super().__init__(id="results-table")
        self.cursor_type = "row"

    def on_mount(self) -> None:
        for label in ("#", "Release", "Lang", "Provider", "Flags", "D/L", "Match"):
            self.add_column(label)

    def refresh_from_state(self, app) -> None:
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
        if self.row_count:
            row = min(app.cursor_index, self.row_count - 1)
            self.move_cursor(row=row)


def _count(value: int) -> str:
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)
