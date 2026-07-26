"""Selected subtitle details and available actions."""

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Static


class DetailPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static("PREVIEW", classes="panel-title")
        yield Static("Select a result", id="detail-title")
        yield Static("", id="detail-provider")
        yield Static("", id="detail-kv")
        yield Button(
            "Download selected  ↵",
            id="download-selected",
            variant="primary",
        )
        yield Button("Copy public URL  y", id="copy-url")

    def refresh_from_state(self, app) -> None:
        candidate = app.current_candidate()
        title = self.query_one("#detail-title", Static)
        provider = self.query_one("#detail-provider", Static)
        detail = self.query_one("#detail-kv", Static)
        download = self.query_one("#download-selected", Button)
        copy = self.query_one("#copy-url", Button)
        if candidate is None:
            title.update("Select a result")
            provider.update("")
            detail.update("")
            download.disabled = True
            copy.disabled = True
            return
        title.update(candidate.release or "(unnamed release)")
        provider.update(
            f"[b]{candidate.provider.label}[/b] · {candidate.language.upper()}"
        )
        detail.update(
            f"Uploader    {candidate.author}\n"
            f"Downloads   {candidate.download_count:,}\n"
            f"Hash match  {'yes' if candidate.hash_match else 'no'}\n"
            f"Hearing impaired  {'yes' if candidate.hearing_impaired else 'no'}\n"
            f"AI translated     {'yes' if candidate.ai_translated else 'no'}"
        )
        download.disabled = False
        copy.disabled = candidate.public_url is None
