"""Clickable application navigation and session controls."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static


class TopBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("▸ SUBS", id="brand")
        for index, (label, view) in enumerate(
            (
                ("Search", "search"),
                ("Queue", "queue"),
                ("History", "history"),
                ("Config", "config"),
            ),
            1,
        ):
            yield Button(
                f"{index} {label}",
                id=f"tab-{view}",
                classes="tab",
                flat=True,
            )
        yield Static("", classes="top-spacer")
        yield Button("", id="chip-engine", classes="chip", flat=True)
        yield Button("", id="chip-language", classes="chip", flat=True)

    def refresh_from_state(self, app) -> None:
        for view in ("search", "queue", "history", "config"):
            button = self.query_one(f"#tab-{view}", Button)
            button.set_class(
                view == app.state.active_view,
                "active",
            )
        config_dirty = app.query_one("#config-view").dirty
        config_button = self.query_one("#tab-config", Button)
        config_button.label = "4 Config •" if config_dirty else "4 Config"
        config_button.set_class(config_dirty, "dirty")
        mode = app.state.engine_mode
        engine_label = "Choose engine" if mode.value == "ask" else mode.label
        self.query_one("#chip-engine", Button).label = f"{engine_label} ▾"
        self.query_one("#chip-language", Button).label = (
            f"{app.state.language.upper()} ▾"
        )
