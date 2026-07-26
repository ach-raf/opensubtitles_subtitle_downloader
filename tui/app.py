"""Minimal Textual app shell for the subtitle downloader TUI.

Phase 0: just boots full-screen and shows the brand label. Real state, widgets,
and services land in later phases. Nothing here touches ``library/`` yet.
"""

from __future__ import annotations

from typing import List, Optional

from textual.app import App, ComposeResult
from textual.widgets import Label


class SubsApp(App):
    """The subtitle downloader command deck.

    Phase 0 deliberately does almost nothing: it mounts a single brand label so
    we can prove the Textual wiring, CSS path, and ``q``-to-quit path work
    behind the ``--tui`` flag. The real surface is layered on in Phases 1-6.
    """

    CSS = """
    Screen {
        background: #0d1014;
        color: #d8dde6;
        align: center middle;
    }
    #brand {
        text-align: center;
        color: #e6e9ef;
        text-style: bold;
    }
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        media_paths: Optional[List[str]] = None,
        overrides: Optional[dict] = None,
    ) -> None:
        super().__init__()
        # Stored but unused this phase; later phases read them to seed AppState.
        self.config = config or {}
        self.media_paths = list(media_paths or [])
        self.overrides = overrides or {}

    def compose(self) -> ComposeResult:
        yield Label("[▸ subs.] [dim]· command deck[/dim]", id="brand", markup=True)


def run_tui(
    config: Optional[dict] = None,
    media_paths: Optional[List[str]] = None,
    overrides: Optional[dict] = None,
) -> None:
    """Launch the Textual app full-screen.

    Kept as a free function so ``download_subs.py`` can call it without
    importing the ``App`` class directly.
    """
    app = SubsApp(config=config, media_paths=media_paths, overrides=overrides)
    app.run()
