"""Persistent operational status and discoverable shortcuts."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from tui.domain import QueueStatus


class StatusBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("", id="status-message")
        yield Static("", id="status-progress")
        yield Static(
            "↑/↓ or j/k move · ↵ download · b/l setup · / query · ? help · q quit",
            id="status-hints",
        )

    def refresh_from_state(self, app) -> None:
        message = self.query_one("#status-message", Static)
        if app.last_error:
            message.update(f"[red]Error · {app.last_error}[/red]")
        elif app.searching:
            message.update("[green]● Searching providers…[/green]")
        elif app.downloading:
            message.update("[green]● Downloading…[/green]")
        else:
            message.update(app.notice or "[green]● Ready[/green]")
        done = sum(item.status is QueueStatus.DONE for item in app.state.queue)
        self.query_one("#status-progress", Static).update(
            f"{done}/{len(app.state.queue)} complete"
            + (" · MERGE" if app.merge_mode else "")
        )
