"""One discoverable action registry shared by shortcuts and the palette."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Action:
    id: str
    label: str
    category: str
    shortcut: str | None = None
    run: Callable[[Any], None] | None = None

    def matches(self, query: str) -> bool:
        tokens = query.casefold().split()
        haystack = f"{self.label} {self.category} {self.shortcut or ''}".casefold()
        return all(token in haystack for token in tokens)


def default_actions() -> list[Action]:
    return [
        Action(
            f"view.{view}",
            f"Open {view.title()} view",
            "navigation",
            f"F{index}",
            lambda app, view=view: app.action_show_view(view),
        )
        for index, view in enumerate(
            ("search", "queue", "history", "config"),
            1,
        )
    ] + [
        Action(
            "lang.open",
            "Change language",
            "search",
            "l",
            lambda app: app.action_open_language(),
        ),
        Action(
            "engine.open",
            "Change subtitle engine",
            "search",
            "e",
            lambda app: app.action_open_engine(),
        ),
        Action(
            "engine.all-providers",
            "Toggle All providers mode",
            "engine",
            "m",
            lambda app: app.action_toggle_all_providers(),
        ),
        Action(
            "engine.reprobe",
            "Refresh engine diagnostics",
            "engine",
            "r",
            lambda app: app.action_reprobe(),
        ),
        Action(
            "query.focus",
            "Edit search query",
            "search",
            "/",
            lambda app: app.action_focus_query(),
        ),
        Action(
            "download",
            "Download selected subtitle",
            "result",
            "Enter",
            lambda app: app.action_download_cursor(),
        ),
        Action(
            "result.copy-url",
            "Copy selected public subtitle URL",
            "result",
            "y",
            lambda app: app.action_copy_url(),
        ),
        Action(
            "result.preview",
            "Preview selected candidate",
            "result",
            "p",
            lambda app: app.action_preview(),
        ),
        Action(
            "config.save",
            "Review and save configuration",
            "config",
            "Ctrl+S",
            lambda app: app.action_save_config(),
        ),
        Action(
            "app.help",
            "Show keyboard help",
            "application",
            "?",
            lambda app: app.action_help(),
        ),
        Action(
            "app.quit",
            "Quit",
            "application",
            "q",
            lambda app: app.action_request_quit(),
        ),
    ]


@dataclass
class Keymap:
    actions: list[Action] = field(default_factory=default_actions)

    def by_id(self, action_id: str) -> Action | None:
        return next(
            (action for action in self.actions if action.id == action_id),
            None,
        )

    def search(self, query: str) -> list[Action]:
        return [action for action in self.actions if action.matches(query)]
