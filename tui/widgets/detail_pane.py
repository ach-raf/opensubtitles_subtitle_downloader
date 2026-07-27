"""Selected subtitle details and available actions."""

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Static


class DetailPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        yield Static(
            "PREVIEW  ·  ROW 1",
            id="preview-heading",
            classes="panel-title",
        )
        yield Static("Select a result", id="detail-title")
        yield Static("", id="detail-provider")
        yield Static("", id="detail-kv")
        with Horizontal(id="detail-actions"):
            yield Button(
                "Get  ↵",
                id="download-selected",
                variant="primary",
            )
            yield Button("View  p", id="preview-selected")
            yield Button("URL  y", id="copy-url")

    def refresh_from_state(self, app) -> None:
        candidate = app.current_candidate()
        title = self.query_one("#detail-title", Static)
        provider = self.query_one("#detail-provider", Static)
        detail = self.query_one("#detail-kv", Static)
        download = self.query_one("#download-selected", Button)
        preview = self.query_one("#preview-selected", Button)
        copy = self.query_one("#copy-url", Button)
        if candidate is None:
            title.update("Select a result")
            provider.update("")
            detail.update("")
            download.disabled = True
            preview.disabled = True
            copy.disabled = True
            return
        title.update(candidate.release or "(unnamed release)")
        provider.update(
            f"[b]{candidate.provider.label}[/b] · {candidate.language.upper()}"
        )
        detail.update(
            f"[dim]Uploader[/dim]   {candidate.author or '—'}\n"
            f"[dim]Downloads[/dim]  {candidate.download_count:,}\n"
            f"[dim]Match[/dim]      [yellow]{candidate.score:.0f}[/yellow]"
            f"{' · [green]exact hash[/green]' if candidate.hash_match else ''}\n"
            f"[dim]Flags[/dim]      "
            f"HI {'yes' if candidate.hearing_impaired else 'no'} · "
            f"AI {'yes' if candidate.ai_translated else 'no'}"
        )
        download.disabled = False
        preview.disabled = False
        copy.disabled = candidate.public_url is None
