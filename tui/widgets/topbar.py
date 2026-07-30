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
                f"F{index} {label}",
                id=f"tab-{view}",
                classes="tab",
                flat=True,
            )
        yield Static("", classes="top-spacer")
        yield Button("", id="chip-engine", classes="chip", flat=True)
        yield Button("", id="chip-language", classes="chip", flat=True)
        yield Button("⌘K COMMAND", id="chip-command", classes="chip utility", flat=True)
        yield Static("", id="chip-health", classes="health-chip")

    def refresh_from_state(self, app) -> None:
        for view in ("search", "queue", "history", "config"):
            button = self.query_one(f"#tab-{view}", Button)
            button.set_class(
                view == app.state.active_view,
                "active",
            )
        config_dirty = app.query_one("#config-view").dirty
        config_button = self.query_one("#tab-config", Button)
        config_button.label = "F4 Config •" if config_dirty else "F4 Config"
        config_button.set_class(config_dirty, "dirty")
        mode = app.state.engine_mode
        engine_label = (
            "All providers"
            if app.merge_mode
            else "Choose engine" if mode.value == "ask" else mode.label
        )
        self.query_one("#chip-engine", Button).label = (
            f"ENGINE [blue]{engine_label}[/blue]  ▾"
        )
        self.query_one("#chip-language", Button).label = (
            f"LANG [green]{app.state.language.upper()}[/green]  ▾"
        )
        provider = mode.provider
        health = app.health.get(provider) if provider else None
        if app.merge_mode:
            health_label = "ALL · LIVE"
        elif health is None:
            health_label = f"{mode.label.upper()} · READY"
        elif health.reachable:
            latency = (
                f"{health.latency_ms}MS"
                if health.latency_ms is not None
                else "LIVE"
            )
            health_label = f"{mode.label.upper()} · {latency}"
        else:
            health_label = f"{mode.label.upper()} · DEGRADED"
        self.query_one("#chip-health", Static).update(
            f"[green]● {health_label}[/green]"
        )
