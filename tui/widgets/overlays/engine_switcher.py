"""Engine switcher — switch backend mid-run (spec §6.3 / mockup §03).

Keys: up/down navigate, enter select, r re-probe, m toggle merge mode, esc.
Shows live health + latency per engine, mirroring SubtitleDownloader's AUTO
probe logic. Dismisses with a Backend (or None on cancel).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from tui.state import CONCRETE_BACKENDS, Backend, EngineHealth

if TYPE_CHECKING:
    pass

_ENGINE_INFO = {
    Backend.OPENSUBTITLES: "largest catalogue · hash match support",
    Backend.SUBDL: "strong for Arabic / Asian content",
    Backend.SUBSOURCE: "community · per-season TV",
    Backend.AUTO: "pick fastest available at run start",
}


class EngineSwitcher(ModalScreen):
    """The engine picker. Dismisses with a Backend or None."""

    DEFAULT_CSS = """
    EngineSwitcher {
        align: center middle;
    }
    EngineSwitcher > Vertical {
        width: 60;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        background: #0f131a;
        border: solid #6f86d6;
        padding: 0 0 1 0;
    }
    EngineSwitcher .pop-head {
        color: #8a93a3;
        padding: 1 2;
        border-bottom: solid #2a3140;
        text-style: bold;
    }
    EngineSwitcher .eng-row {
        padding: 0 2;
        margin: 1 1 0 1;
        color: #d8dde6;
    }
    EngineSwitcher .eng-row.sel {
        background: #1a2638;
        border: solid #4ddb9a;
    }
    EngineSwitcher .eng-row.auto {
        border: dashed #2a3140;
    }
    EngineSwitcher .pop-foot {
        color: #6a7280;
        padding: 1 2 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("enter", "select", "Select", show=False),
        Binding("r", "reprobe", "Re-probe", show=False),
        Binding("m", "toggle_merge", "Merge", show=False),
    ]

    def __init__(
        self,
        current: Backend,
        health: Dict[str, EngineHealth],
        merge_mode: bool,
    ) -> None:
        super().__init__()
        self.current = current
        self.health = dict(health)
        self.merge_mode = merge_mode
        # Order: the three concrete engines first, then AUTO last.
        self._engines: List[Backend] = list(CONCRETE_BACKENDS) + [Backend.AUTO]
        self._cursor = self._engines.index(current) if current in self._engines else 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "[#6f86d6]⇄[/] [b]Subtitle engine[/b]   [dim]↑↓ · ↵ · esc[/dim]",
                classes="pop-head",
                markup=True,
            )
            yield Static("", id="eng-list")
            yield Static(
                "[dim][b]r[/b] re-probe now   [b]m[/b] merge results from all 3"
                + ("   [#4ddb9a]merge: ON[/]" if self.merge_mode else ""),
                id="eng-foot",
                classes="pop-foot",
                markup=True,
            )

    def on_mount(self) -> None:
        self._render_rows()

    def _safe_update(self, selector: str, content: str) -> None:
        """Update a Static, ignoring queries that fire during screen teardown."""
        try:
            self.query_one(selector, Static).update(content)
        except Exception:  # noqa: BLE001 - NoMatches during dismiss is benign
            pass

    def _render_rows(self) -> None:
        lines: List[str] = []
        for i, be in enumerate(self._engines):
            sel = i == self._cursor
            marker = "▶" if sel else " "
            # Selected rows render in the phosphor accent; unselected in plain ink.
            row_color = "#4ddb9a" if sel else "#d8dde6"
            name = f"[b]{be.label}[/]" if be is not Backend.AUTO else f"[dim]{be.label}[/]"
            desc = _ENGINE_INFO.get(be, "")
            badge = self._badge_markup(be)
            latency = self._latency_markup(be)
            lines.append(
                f"[{row_color}]{marker}[/] {name}  [dim]{desc}[/]  {badge}  {latency}"
            )
        self._safe_update("#eng-list", "\n".join(lines))
        self._safe_update(
            "#eng-foot",
            "[dim][b]r[/b] re-probe now   [b]m[/b] merge results from all 3[/]"
            + ("   [#4ddb9a]merge: ON[/]" if self.merge_mode else ""),
        )

    def _badge_markup(self, be: Backend) -> str:
        if be is Backend.AUTO:
            return ""
        h = self.health.get(be.value)
        if h is None:
            return "[dim]—[/]"
        if h.online:
            return "[#4ddb9a]online[/]"
        if h.degraded:
            return "[#d9a441]degraded[/]"
        return "[#c75450]offline[/]"

    def _latency_markup(self, be: Backend) -> str:
        if be is Backend.AUTO:
            return ""
        h = self.health.get(be.value)
        if h and h.latency_ms is not None:
            return f"[dim]{h.latency_ms}ms[/]"
        return "[dim]—[/]"

    # ---- Actions ----------------------------------------------------------
    def action_nav_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._render_rows()

    def action_nav_down(self) -> None:
        if self._cursor < len(self._engines) - 1:
            self._cursor += 1
            self._render_rows()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select(self) -> None:
        self.dismiss(self._engines[self._cursor])

    def action_toggle_merge(self) -> None:
        self.merge_mode = not self.merge_mode
        self._render_rows()

    def action_reprobe(self) -> None:
        # Ask the host app to re-probe and hand back fresh health, then re-render.
        # We can't call services directly (no library imports here); post a
        # message the App handles. For Phase 3 we re-render with current data
        # and let the App refresh health on the next tick.
        self.app.action_reprobe_engines()
        self._render_rows()
