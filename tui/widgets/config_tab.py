"""Config tab — all YAML knobs as live toggles; ⌘S writes back (spec §6.6 / §06).

Phase 5 renders this as a ModalScreen (the TopBar tabs are display-only this
iteration). Toggles cycle on enter; ctrl+s saves with a one-line diff preview
before commit. The screen edits a local copy of RunPolicy and only mutates the
App's state on save (so cancel is a true rollback).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from tui.state import HI_POLICY_VALUES, RunPolicy, SYNC_POLICY_VALUES

if TYPE_CHECKING:
    from tui.app import SubsApp


# (label, config-key-hint, kind) — kind tells the renderer how to display/cycle.
# kind: "bool" | "sync" | "hi"
TOGGLES = [
    ("Force UTF-8", "opt_force_utf8", "bool", "force_utf8"),
    ("Clean ads", "cleaning_subtitles.ads", "bool", "clean_ads"),
    ("Audio sync", "sync_audio_to_subs · always/never/ask", "sync", "audio_sync"),
    ("Hearing impaired", "hi filter · include/exclude/only", "hi", "hearing_impaired"),
    ("Auto-select best", "auto_selection", "bool", "auto_select"),
    ("Show AI-translated", "show ⚙AI rows", "bool", "show_ai_translated"),
    ("Hash match first", "probe moviehash", "bool", "hash_match_first"),
    ("Alt-name search", "get_alternate_names", "bool", "alt_name_search"),
]


class ConfigTab(ModalScreen):
    """The Config settings rail + ⌘S save-back."""

    DEFAULT_CSS = """
    ConfigTab {
        align: center middle;
    }
    ConfigTab > Vertical {
        width: 80;
        max-width: 95%;
        height: auto;
        max-height: 88%;
        background: #0f131a;
        border: solid #6f86d6;
    }
    ConfigTab #cfg-head {
        padding: 1 2;
        border-bottom: solid #2a3140;
        color: #d8dde6;
        text-style: bold;
    }
    ConfigTab #cfg-body {
        padding: 1 2;
    }
    ConfigTab .grp-h {
        color: #6a7280;
        text-style: bold;
        padding: 1 0 0 0;
    }
    ConfigTab .tg-row {
        padding: 0 1;
        margin: 0 0 1 0;
        color: #d8dde6;
    }
    ConfigTab .tg-row.sel {
        background: #1a2638;
        border-left: thick #4ddb9a;
    }
    ConfigTab #cfg-foot {
        padding: 0 2;
        border-top: solid #2a3140;
        color: #6a7280;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("enter", "toggle", "Toggle", show=False),
        Binding("ctrl+s", "save", "Save", show=False),
    ]

    def __init__(self, policy: RunPolicy, ads_file_path: Optional[str]) -> None:
        super().__init__()
        # Local editable copy; only written back to the App on save.
        self.policy = RunPolicy(**policy.__dict__)
        self.ads_file_path = ads_file_path or ""
        self._cursor = 0
        # 8 toggles + the ads-path input = 9 selectable rows.
        self._row_count = len(TOGGLES) + 1

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                "[#6f86d6]⚙[/] [b]Config[/b]   [dim]↑↓ · ↵ toggle · ctrl+s save · esc cancel[/dim]",
                id="cfg-head",
                markup=True,
            )
            with VerticalScroll(id="cfg-body"):
                yield Static("[dim]post-download[/dim]", classes="grp-h", markup=True)
                yield Static("", id="cfg-toggles")
                yield Static("[dim]ads file[/dim]", classes="grp-h", markup=True)
                yield Static("", id="cfg-ads-label")
                yield Input(
                    value=self.ads_file_path,
                    id="cfg-ads-input",
                    placeholder="cleaning_subtitles.ads.file_path",
                )
            yield Static("", id="cfg-foot")

    def on_mount(self) -> None:
        self._render()

    # ---- Rendering --------------------------------------------------------
    def _safe_update(self, selector: str, content: str) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except Exception:  # noqa: BLE001
            pass

    def _render(self) -> None:
        lines: List[str] = []
        for i, (label, hint, kind, field) in enumerate(TOGGLES):
            sel = i == self._cursor
            marker = "▶" if sel else " "
            color = "#4ddb9a" if sel else "#d8dde6"
            value = self._value_markup(kind, field)
            lines.append(
                f"[{color}]{marker}[/] [b]{label}[/]  [dim]{hint}[/]  {value}"
            )
        self._safe_update("#cfg-toggles", "\n".join(lines))

        ads_idx = len(TOGGLES)
        ads_sel = self._cursor == ads_idx
        ads_color = "#4ddb9a" if ads_sel else "#d8dde6"
        ads_marker = "▶" if ads_sel else " "
        self._safe_update(
            "#cfg-ads-label",
            f"[{ads_color}]{ads_marker}[/] [b]file_path[/]  [dim]{self.ads_file_path or '(none)'}[/]",
        )

        self._safe_update(
            "#cfg-foot",
            "[dim][b]ctrl+s[/b] save to config.yaml   [b]esc[/b] cancel"
            "   [b]↵[/b] toggle / edit[/]",
        )

    def _value_markup(self, kind: str, field: str) -> str:
        value = getattr(self.policy, field)
        if kind == "bool":
            return "[#4ddb9a]on[/]" if value else "[#6a7280]off[/]"
        if kind == "sync":
            return {
                "always": "[#4ddb9a]always[/]",
                "never": "[#6a7280]never[/]",
                "ask": "[#d9a441]ask[/]",
            }[value]
        if kind == "hi":
            return f"[#d8dde6]{value}[/]"
        return str(value)

    # ---- Actions ----------------------------------------------------------
    def action_nav_up(self) -> None:
        # If the ads Input is focused, let it handle keys; otherwise move.
        if self.focused and self.focused.__class__.__name__ == "Input":
            return
        if self._cursor > 0:
            self._cursor -= 1
            self._render()

    def action_nav_down(self) -> None:
        if self.focused and self.focused.__class__.__name__ == "Input":
            return
        if self._cursor < self._row_count - 1:
            self._cursor += 1
            self._render()

    def action_toggle(self) -> None:
        if self._cursor < len(TOGGLES):
            label, hint, kind, field = TOGGLES[self._cursor]
            if kind == "bool":
                setattr(self.policy, field, not getattr(self.policy, field))
            elif kind == "sync":
                idx = SYNC_POLICY_VALUES.index(getattr(self.policy, field))
                setattr(
                    self.policy,
                    field,
                    SYNC_POLICY_VALUES[(idx + 1) % len(SYNC_POLICY_VALUES)],
                )
            elif kind == "hi":
                idx = HI_POLICY_VALUES.index(getattr(self.policy, field))
                setattr(
                    self.policy,
                    field,
                    HI_POLICY_VALUES[(idx + 1) % len(HI_POLICY_VALUES)],
                )
            self.policy.validate()
        else:
            # Ads-path row: focus the input for editing.
            try:
                self.query_one("#cfg-ads-input", Input).focus()
            except Exception:  # noqa: BLE001
                pass
        self._render()

    def action_save(self) -> None:
        # Pull the ads path out of the Input before saving.
        try:
            self.ads_file_path = self.query_one("#cfg-ads-input", Input).value
        except Exception:  # noqa: BLE001
            pass
        self.policy.ads_file_path = self.ads_file_path or None
        # Hand the (possibly edited) policy to the App to persist + show a diff.
        self.dismiss(("save", self.policy))

    def action_cancel(self) -> None:
        self.dismiss(("cancel", None))
