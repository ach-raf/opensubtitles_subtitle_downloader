"""Keybinding registry + palette action index.

The palette (Phase 3) fuzzy-searches this registry. Each action carries an id,
human label, category, optional shortcut, and a callable that runs against the
App. Built once at startup from a static list; the App may add dynamic actions
(e.g. one per configured language) before showing the palette.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


@dataclass
class Action:
    id: str
    label: str
    category: str  # action | setting | batch | engine
    shortcut: Optional[str] = None
    run: Optional[Callable] = None  # called with the SubsApp instance

    def matches(self, query: str) -> bool:
        """Naive case-insensitive substring match across label + category."""
        q = query.lower().strip()
        if not q:
            return True
        hay = f"{self.label} {self.category} {self.shortcut or ''}".lower()
        return all(token in hay for token in q.split())


def default_actions() -> List[Action]:
    """The static set of indexed actions. Dynamic ones (per-language, per-engine)
    are appended by the App before the palette opens."""
    return [
        Action("nav.down", "Move cursor down", "action", "j",
               run=lambda app: app.action_cursor_down()),
        Action("nav.up", "Move cursor up", "action", "k",
               run=lambda app: app.action_cursor_up()),
        Action("download", "Download cursor row", "action", "↵",
               run=lambda app: app.action_download_cursor()),
        Action("focus-query", "Focus filter / search", "action", "/",
               run=lambda app: app.action_focus_query()),
        Action("lang.open", "Change language…", "setting", "L",
               run=lambda app: app.action_open_language()),
        Action("engine.open", "Switch subtitle engine…", "engine", "B",
               run=lambda app: app.action_open_engine()),
        Action("engine.merge", "Toggle merge mode (fan out to all engines)", "engine", "m",
               run=lambda app: setattr(app, "merge_mode", not app.merge_mode)),
        Action("engine.reprobe", "Re-probe engine health + latency", "engine", "r",
               run=lambda app: app.action_reprobe_engines()),
        Action("policy.utf8", "Toggle force-UTF-8", "setting",
               run=lambda app: app._toggle_policy("force_utf8")),
        Action("policy.clean", "Toggle clean-ads", "setting",
               run=lambda app: app._toggle_policy("clean_ads")),
        Action("policy.autoselect", "Toggle auto-select best", "setting",
               run=lambda app: app._toggle_policy("auto_select")),
        Action("policy.sync", "Set audio-sync policy: always / never / ask", "setting",
               run=lambda app: app._cycle_sync_policy()),
        Action("policy.hi", "Cycle hearing-impaired filter: include / exclude / only", "setting",
               run=lambda app: app._cycle_hi_policy()),
        Action("app.quit", "Quit", "action", "q",
               run=lambda app: app.exit()),
        Action("app.palette", "Open command palette", "action", "⌘K",
               run=lambda app: app.action_open_palette()),
        Action("config.open", "Open Config (settings + save to config.yaml)", "setting", "4",
               run=lambda app: app.action_open_config()),
    ]


@dataclass
class Keymap:
    actions: List[Action] = field(default_factory=default_actions)

    def by_id(self, action_id: str) -> Optional[Action]:
        return next((a for a in self.actions if a.id == action_id), None)

    def search(self, query: str) -> List[Action]:
        return [a for a in self.actions if a.matches(query)]
