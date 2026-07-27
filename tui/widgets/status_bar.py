"""Persistent operational status and discoverable shortcuts."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from tui.domain import QueueStatus


class StatusBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("", id="status-message")
        yield Static("", id="status-progress")
        yield Static("", id="status-settings")
        yield Static(
            "L lang · B engine · K palette · q quit",
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
            message.update("[green]● IDLE[/green]")
        done = sum(item.status is QueueStatus.DONE for item in app.state.queue)
        self.query_one("#status-progress", Static).update(
            f"{done}/{len(app.state.queue)} DONE"
            + (" · MERGE" if app.merge_mode else "")
        )
        general = app.application_config.general
        clean = "✓" if app.application_config.cleaning.enabled else "off"
        utf8 = "✓" if general.opt_force_utf8 else "off"
        self.query_one("#status-settings", Static).update(
            f"engine [b]{app.state.engine_mode.label}[/b]  │  "
            f"lang [b]{app.state.language.upper()}[/b]  │  "
            f"utf-8 [b]{utf8}[/b]  │  clean [b]{clean}[/b]  │  "
            f"sync [b]{general.sync_audio_to_subs}[/b]  │  "
            f"HI [b]{general.hearing_impaired}[/b]"
        )
        hints = self.query_one("#status-hints", Static)
        if app.state.active_view == "config":
            hints.update("Tab move · Space toggle · Ctrl+S save · q quit")
        else:
            hints.update("L lang · B engine · K palette · q quit")
