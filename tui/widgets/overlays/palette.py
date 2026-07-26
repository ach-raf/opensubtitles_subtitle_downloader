"""Command palette — ⌘K (Ctrl+K) do-anything surface (spec §6.5 / mockup §05).

Keys: type to fuzzy-filter, up/down navigate, enter run (and close),
ctrl+enter run and keep open, esc close.
"""

from __future__ import annotations

from contextlib import suppress

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from tui.keymap import Action, Keymap


class Palette(ModalScreen):
    """The command palette. Dismisses with an Action to run, or None."""

    DEFAULT_CSS = """
    Palette {
        align: center top;
        padding-top: 2;
    }
    Palette > Vertical {
        width: 72;
        max-width: 95%;
        height: 28;
        background: #0f131a;
        border: solid #4ddb9a;
    }
    Palette #pal-input {
        padding: 1 2;
        border-bottom: solid #2a3140;
    }
    Palette #pal-list {
        padding: 1;
        max-height: 40;
        overflow-y: auto;
    }
    Palette .pal-item {
        padding: 0 1;
        color: #d8dde6;
    }
    Palette .pal-item.sel {
        background: #1a2a24;
        border-left: thick #4ddb9a;
    }
    Palette .pal-item .cat {
        color: #6a7280;
    }
    Palette .pal-item .sc {
        color: #6a7280;
    }
    Palette #pal-foot {
        color: #6a7280;
        padding: 0 2;
        border-top: solid #2a3140;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("enter", "run", "Run", show=False),
        Binding("ctrl+enter", "run_keep", "Run + keep", show=False),
    ]

    def __init__(self, keymap: Keymap) -> None:
        super().__init__()
        self.keymap = keymap
        self._filtered: list[Action] = []
        self._cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Input(placeholder="› type to search actions…", id="pal-input")
            yield Static("", id="pal-list")
            yield Static(
                "[dim]↑↓ navigate   ↵ run   ⌘↵ run + keep open   esc close[/dim]",
                id="pal-foot",
                markup=True,
            )

    def on_mount(self) -> None:
        self._filtered = self.keymap.search("")
        self._render_rows()
        self.query_one("#pal-input", Input).focus()

    # ---- Filtering --------------------------------------------------------
    @on(Input.Changed, "#pal-input")
    def _on_filter(self, event: Input.Changed) -> None:
        self._filtered = self.keymap.search(event.value)
        self._cursor = 0
        self._render_rows()

    @on(Input.Submitted, "#pal-input")
    def _on_submit(self, event: Input.Submitted) -> None:
        self.action_run()

    def _safe_update(self, selector: str, content: str) -> None:
        with suppress(Exception):
            self.query_one(selector, Static).update(content)

    def _render_rows(self) -> None:
        lines: list[str] = []
        for i, action in enumerate(self._filtered):
            is_sel = i == self._cursor
            marker = "▶" if is_sel else " "
            # Selected rows render in the phosphor accent; shortcut shown plainly.
            row_color = "#4ddb9a" if is_sel else "#d8dde6"
            sc = action.shortcut or ""
            lines.append(
                f"[{row_color}]{marker}[/] {action.label}  "
                f"[dim]{action.category}[/]  [dim]{sc}[/]"
            )
        count = f"   [dim]{len(self._filtered)} matches[/]"
        self._safe_update(
            "#pal-list", "\n".join(lines) if lines else "[dim]no actions match[/dim]"
        )
        self._safe_update(
            "#pal-foot",
            "[dim]↑↓ navigate   ↵ run   ⌘↵ run + keep open   esc close[/]" + count,
        )

    # ---- Actions ----------------------------------------------------------
    def action_nav_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._render_rows()

    def action_nav_down(self) -> None:
        if self._cursor < len(self._filtered) - 1:
            self._cursor += 1
            self._render_rows()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_run(self) -> None:
        self._run(keep_open=False)

    def action_run_keep(self) -> None:
        self._run(keep_open=True)

    def _run(self, keep_open: bool) -> None:
        if not self._filtered:
            return
        action = self._filtered[self._cursor]
        if keep_open:
            # Run without dismissing; the host app executes the action.
            self._filtered = self.keymap.search("")
            self._cursor = 0
            self._render_rows()
        self.dismiss(action)
