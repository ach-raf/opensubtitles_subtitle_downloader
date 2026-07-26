"""TopBar widget — brand, tabs, and live engine/lang/online chips.

Phase 2: chips are display-only (clickable + overlays come in Phase 3). The
Search tab is the only active one this phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from tui.state import Backend, EngineHealth, native_name

if TYPE_CHECKING:
    from tui.app import SubsApp


class TopBar(Horizontal):
    """Brand + tab strip + live engine/lang/health chips."""

    DEFAULT_CSS = ""

    def compose(self) -> ComposeResult:
        yield Static("[▸ subs.] [dim]command deck[/dim]", id="brand", markup=True, classes="brand")
        # Tab strip — only Search is active in Phase 2. The counts/toggles
        # become functional in later phases.
        yield Static(
            "[▸][b]Search[/b]   "
            "[dim]Queue[/dim]   "
            "[dim]History[/dim]   "
            "[dim]Config[/dim]",
            id="tabs",
            markup=True,
        )
        yield Static("", id="chip-engine", classes="chip eng", markup=True)
        yield Static("", id="chip-lang", classes="chip lang", markup=True)
        yield Static("", id="chip-palette", classes="chip", markup=True)
        yield Static("", id="online-badge", classes="badge", markup=True)

    def refresh_from_state(self, app: "SubsApp") -> None:
        backend: Backend = app.backend
        health_map: dict = app.engine_health
        language: str = app.language

        # Engine chip.
        engine_chip = self.query_one("#chip-engine", Static)
        engine_chip.update(
            f"[dim]engine[/dim] [b]{backend.label}[/b][dim]▾[/dim]"
        )

        # Language chip — show ISO code upper-cased.
        lang_chip = self.query_one("#chip-lang", Static)
        lang_chip.update(
            f"[dim]lang[/dim] [b]{language.upper()}[/b][dim]▾[/dim]"
        )

        # Palette chip (placeholder until Phase 3 wires ⌘K).
        pal_chip = self.query_one("#chip-palette", Static)
        pal_chip.update("[dim]⌘K[/dim] [b]command[/b]")

        # Online badge — show the active engine's health + latency, or 'auto'.
        badge = self.query_one("#online-badge", Static)
        if backend is Backend.AUTO:
            badge.update("[b]AUTO[/b]")
        else:
            health = health_map.get(backend.value)
            badge.update(self._badge_markup(backend, health))

    @staticmethod
    def _badge_markup(backend: Backend, health: "EngineHealth | None") -> str:
        if health is None:
            return f"[dim]{backend.label}[/dim]"
        short = backend.label[:2].upper() if backend is not Backend.OPENSUBTITLES else "OS"
        latency = f"{health.latency_ms}ms" if health.latency_ms is not None else "—"
        if health.online:
            return f"[b]{short} · {latency}[/b]"
        if health.degraded:
            return f"[#d9a441]{short} · degraded[/]"
        return f"[#c75450]{short} · offline[/]"
