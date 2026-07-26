"""Language popover — change the active language mid-run (spec §6.2 / mockup §02).

Keys: / filter, up/down navigate, enter select, esc cancel.
Scope rule: if the queue has >1 non-done item, selecting a language opens a
scope picker (a = apply to all remaining, c = current file only, esc = cancel).
For a single-file run the language applies instantly with no prompt.
+ Add language by ISO code: typing a code not in the list and pressing enter
adds it for the session (and persists on the next ⌘S).
"""

from __future__ import annotations

from contextlib import suppress

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from tui.state import native_name

Scope = str  # "all" | "current" | None
LangResult = tuple[str, Scope]


class LanguagePopover(ModalScreen[LangResult]):
    """The language picker. Dismisses with (code, scope) or None."""

    # Shared CSS lives in tui/style.tcss; this is popover-specific tweaks.
    DEFAULT_CSS = """
    LanguagePopover {
        align: center middle;
    }
    LanguagePopover > #lang-dialog {
        width: 48;
        max-width: 80%;
        height: 16;
        background: #0f131a;
        border: solid #6f86d6;
        padding: 0 0 1 0;
    }
    LanguagePopover .pop-head {
        color: #8a93a3;
        padding: 1 2;
        border-bottom: solid #2a3140;
        text-style: bold;
    }
    LanguagePopover #lang-filter {
        margin: 1 2 0 2;
        border: solid #2a3140;
    }
    LanguagePopover #lang-list {
        padding: 0 1;
        height: auto;
        height: 5;
        overflow-y: auto;
    }
    LanguagePopover .lang-row {
        padding: 0 1;
        color: #d8dde6;
    }
    LanguagePopover .lang-row.sel {
        background: #1a2a24;
        color: #e6e9ef;
        border-left: thick #4ddb9a;
    }
    LanguagePopover .lang-row .code {
        color: #6a7280;
        width: 4;
    }
    LanguagePopover .lang-row .primary {
        color: #6a7280;
        text-style: bold;
    }
    LanguagePopover .lang-row .chk {
        color: #4ddb9a;
    }
    LanguagePopover .pop-foot {
        color: #6a7280;
        padding: 1 2 0 2;
    }
    LanguagePopover #scope-prompt {
        padding: 1 2;
        color: #d8dde6;
        background: #14181f;
        border-top: solid #2a3140;
    }
    LanguagePopover #scope-prompt .ttl {
        text-style: bold;
        color: #e6e9ef;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    def __init__(
        self,
        languages: dict[str, str],
        current: str,
        needs_scope_confirm: bool,
        remaining_files: list[str],
    ) -> None:
        super().__init__()
        self.languages = dict(languages)
        self.current = current
        self.needs_scope_confirm = needs_scope_confirm
        self.remaining_files = remaining_files
        self._filter = ""
        self._cursor = 0
        self._filtered: list[tuple[str, str]] = []  # (code, native)
        self._selected_code: str | None = None
        self._scope_mode = False

    # ---- Compose ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Vertical(id="lang-dialog"):
            yield Static(
                "[#6f86d6]▾[/] [b]Language[/b]   [dim]/ filter · ↑↓ · ↵ · esc[/dim]",
                id="pop-head",
                classes="pop-head",
                markup=True,
            )
            yield Input(
                placeholder="/ to filter, or type an ISO code to add…", id="lang-filter"
            )
            yield Vertical(
                Static("", id="lang-list"),
                id="lang-list-wrap",
            )
            yield Static("", id="scope-prompt")
            yield Static(
                "[dim][b]a[/b] all queued   " "[b]c[/b] current file only[/dim]",
                id="pop-foot",
                classes="pop-foot",
                markup=True,
            )

    def on_mount(self) -> None:
        self._rebuild_list()
        visible_rows = min(15, max(4, len(self._filtered)))
        self.query_one("#lang-list-wrap", Vertical).styles.height = visible_rows
        self.query_one("#lang-dialog", Vertical).styles.height = visible_rows + 11
        self.query_one("#scope-prompt", Static).display = False
        self.query_one("#lang-filter", Input).focus()

    # ---- List building ----------------------------------------------------
    def _all_entries(self) -> list[tuple[str, str]]:
        entries = [(code, name) for code, name in self.languages.items()]
        # Sort: current first, then alpha by native name.
        entries.sort(key=lambda c: (c[0] != self.current, c[1].lower()))
        return entries

    def _rebuild_list(self) -> None:
        q = self._filter.lower().strip()
        if q:
            self._filtered = [
                (code, name)
                for code, name in self._all_entries()
                if q in code.lower() or q in name.lower()
            ]
            # Also allow a raw ISO code add (not in the map yet).
            if q and q not in self.languages:
                self._filtered.append((q, native_name(q)))
        else:
            self._filtered = self._all_entries()
        if self._cursor >= len(self._filtered):
            self._cursor = max(0, len(self._filtered) - 1)
        self._render_list()

    def _safe_update(self, selector: str, content: str) -> None:
        with suppress(Exception):
            self.query_one(selector, Static).update(content)

    def _render_list(self) -> None:
        lines: list[str] = []
        for i, (code, name) in enumerate(self._filtered):
            is_current = code == self.current
            lines.append(self._row_markup(i, code, name, is_current))
        self._safe_update(
            "#lang-list", "\n".join(lines) if lines else "[dim]no languages match[/dim]"
        )

    def _row_markup(self, i: int, code: str, name: str, is_current: bool) -> str:
        sel_marker = "▶" if i == self._cursor else " "
        primary = "  [dim]PRIMARY[/]" if is_current else ""
        chk = "  [#4ddb9a]●[/]" if is_current else ""
        return f"{sel_marker} [dim]{code:<3}[/] {name}{primary}{chk}"

    # ---- Input handling ---------------------------------------------------
    @on(Input.Changed, "#lang-filter")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self._filter = event.value
        self._cursor = 0
        self._rebuild_list()

    @on(Input.Submitted, "#lang-filter")
    def _on_filter_submitted(self, event: Input.Submitted) -> None:
        # If the filter text matches a code exactly (or is a new code), select it.
        text = event.value.lower().strip()
        if text and text in {c for c, _ in self._filtered}:
            self._cursor = next(
                i for i, (c, _) in enumerate(self._filtered) if c == text
            )
        self.action_select()

    def on_key(self, event) -> None:
        # When scope mode is active, intercept a/c/esc here.
        if self._scope_mode:
            if event.key == "a":
                self.dismiss((self._selected_code, "all"))
            elif event.key == "c":
                self.dismiss((self._selected_code, "current"))
            elif event.key == "escape":
                self.dismiss(None)
            event.prevent_default()
            return

    # ---- Actions ----------------------------------------------------------
    def action_nav_up(self) -> None:
        if self._cursor > 0:
            self._cursor -= 1
            self._render_list()

    def action_nav_down(self) -> None:
        if self._cursor < len(self._filtered) - 1:
            self._cursor += 1
            self._render_list()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select(self) -> None:
        if not self._filtered:
            return
        code, name = self._filtered[self._cursor]
        self._selected_code = code
        # Persist a newly-added code for the session.
        if code not in self.languages:
            self.languages[code] = name

        if not self.needs_scope_confirm:
            # Single-file run: instant.
            self.dismiss((code, "current"))
            return

        # Show the scope picker.
        self._scope_mode = True
        self.query_one("#scope-prompt", Static).display = True
        dialog = self.query_one("#lang-dialog", Vertical)
        dialog.styles.height = min(30, int(dialog.size.height) + 7)
        # Drop focus from the filter Input so the scope keys (a/c/esc) reach
        # on_key instead of being typed into the filter.
        with suppress(Exception):
            self.query_one("#lang-filter", Input).blur()
        self._render_scope_prompt(code, name)

    def _render_scope_prompt(self, code: str, name: str) -> None:
        preview = " · ".join(self.remaining_files[:3])
        more = (
            f" (+{len(self.remaining_files) - 3} more)"
            if len(self.remaining_files) > 3
            else ""
        )
        self._safe_update(
            "#scope-prompt",
            f"[b]Apply[/b] [#4ddb9a]{name}[/] [b]to:[/b]\n\n"
            f"[dim]remaining {len(self.remaining_files)} files:[/dim] "
            f"{preview}{more}\n\n"
            f"[b][#4ddb9a]a[/][/] all remaining   "
            f"[b][#4ddb9a]c[/][/] current file only   "
            f"[b]esc[/] cancel",
        )
