"""StatusBar — live mirror of every setting + key hints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from tui.state import Backend

if TYPE_CHECKING:
    from tui.app import SubsApp


class StatusBar(Horizontal):
    """Bottom bar: status pill + setting mirror + key hints."""

    def compose(self) -> ComposeResult:
        yield Static("", id="sb-status")
        yield Static("", id="sb-mirror")
        yield Static(
            "[dim]L lang · B engine · K palette · jk scroll · ↵ download · q quit[/dim]",
            id="sb-hints",
            markup=True,
        )

    def refresh_from_state(self, app: "SubsApp") -> None:
        status = self.query_one("#sb-status", Static)
        mirror = self.query_one("#sb-mirror", Static)

        # Status pill: how many queue items are done.
        done = sum(1 for it in app.queue if it.is_done())
        total = len(app.queue)
        if app.last_error:
            status.update(f"[#c75450]● error[/]")
        elif app.searching:
            status.update("[#4ddb9a]● searching…[/]")
        elif total:
            status.update(f"[#4ddb9a]● {done}/{total} done[/]")
        else:
            status.update("[#4ddb9a]● idle[/]")

        backend: Backend = app.backend
        policy = app.run_policy
        mirror.update(
            f"[dim]engine[/dim] [b]{backend.label}[/b]"
            "[dim] │ [/dim]"
            f"[dim]lang[/dim] [b]{app.language.upper()}[/b]"
            "[dim] │ [/dim]"
            f"[dim]utf-8[/dim] [{'#4ddb9a' if policy.force_utf8 else '#c75450'}]{'✓' if policy.force_utf8 else '✗'}[/]"
            "[dim] │ [/dim]"
            f"[dim]clean[/dim] [{'#4ddb9a' if policy.clean_ads else '#6a7280'}]{'✓' if policy.clean_ads else '✗'}[/]"
            "[dim] │ [/dim]"
            f"[dim]sync[/dim] [b]{policy.audio_sync}[/b]"
            "[dim] │ [/dim]"
            f"[dim]HI[/dim] [b]{policy.hearing_impaired}[/b]"
            + ("[dim] │ [/dim][#6f86d6]merge[/]" if app.merge_mode else "")
        )
