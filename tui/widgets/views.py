"""The four real command-deck workspaces."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Select,
    Static,
    Switch,
)

from tui.domain import EngineMode, Provider
from tui.widgets.detail_pane import DetailPane
from tui.widgets.query_bar import QueryBar
from tui.widgets.results_table import ResultsTable


class SearchView(Container):
    def compose(self) -> ComposeResult:
        yield QueryBar()
        yield Static("", id="search-state")
        with Horizontal(id="search-split"):
            with Container(id="results-panel"):
                yield Static(
                    "RESULTS  ·  SORTED BY MATCH",
                    id="results-heading",
                    classes="panel-title",
                )
                yield ResultsTable()
            yield DetailPane(id="detail-panel")

    def refresh_from_state(self, app) -> None:
        item = app.state.active_item
        state = self.query_one("#search-state", Static)
        if item is None:
            state.update("[green]Batch complete[/green]")
        elif app.last_error:
            state.update(f"[red]{app.last_error}[/red]")
        elif app.searching:
            state.update(
                f"[green]Searching[/green] · {item.path.name} · "
                f"{app.state.engine_mode.label} · "
                f"{app.state.language.upper()}"
            )
        else:
            state.update(
                f"{item.status.value.replace('_', ' ').title()} · " f"{item.path.name}"
            )


class QueueView(Container):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rendered_signature: tuple | None = None

    def compose(self) -> ComposeResult:
        yield Static("QUEUE", classes="view-title")
        yield Static(
            "Every file keeps its own language, engine, and progress.",
            classes="view-subtitle",
        )
        yield DataTable(id="queue-table")
        with Horizontal(classes="queue-actions"):
            yield Button("Skip current", id="queue-skip")
            yield Button("Retry failed", id="queue-retry")

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.cursor_type = "row"
        for label in ("#", "Media", "Language", "Engine", "Status", "Error"):
            table.add_column(label)

    def refresh_from_state(self, app) -> None:
        signature = tuple(
            (
                item.key,
                item.path.name,
                item.language,
                item.engine_mode,
                item.status,
                item.error,
            )
            for item in app.state.queue
        )
        if signature == self._rendered_signature:
            return
        table = self.query_one("#queue-table", DataTable)
        table.clear()
        for index, item in enumerate(app.state.queue, 1):
            table.add_row(
                str(index),
                item.path.name,
                item.language.upper(),
                item.engine_mode.label,
                item.status.value.replace("_", " "),
                item.error or "",
                key=item.key,
            )
        self._rendered_signature = signature


class HistoryView(Container):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._rendered_signature: tuple | None = None

    def compose(self) -> ComposeResult:
        yield Static("HISTORY", classes="view-title")
        yield Static(
            "Completed downloads and the real post-processing outcome.",
            classes="view-subtitle",
        )
        yield DataTable(id="history-table")

    def on_mount(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.cursor_type = "row"
        for label in (
            "Media",
            "Provider",
            "Language",
            "Subtitle",
            "UTF-8",
            "Clean",
            "Sync",
            "Error",
        ):
            table.add_column(label)

    def refresh_from_state(self, app) -> None:
        signature = tuple(
            (
                entry.item_key,
                entry.subtitle_path,
                entry.error,
                entry.postprocess.utf8_normalized,
                entry.postprocess.cleaned,
                entry.postprocess.synced,
                entry.postprocess.utf8_error,
                entry.postprocess.clean_error,
                entry.postprocess.sync_error,
            )
            for entry in app.state.history
        )
        if signature == self._rendered_signature:
            return
        table = self.query_one("#history-table", DataTable)
        table.clear()
        for entry in app.state.history:
            table.add_row(
                entry.media_path.name,
                entry.provider.label,
                entry.language.upper(),
                entry.subtitle_path.name if entry.subtitle_path else "—",
                "yes" if entry.postprocess.utf8_normalized else "no",
                "yes" if entry.postprocess.cleaned else "no",
                "yes" if entry.postprocess.synced else "no",
                entry.error
                or entry.postprocess.utf8_error
                or entry.postprocess.clean_error
                or entry.postprocess.sync_error
                or "",
                key=entry.item_key,
            )
        self._rendered_signature = signature


class ConfigView(Container):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.dirty = False

    def compose(self) -> ComposeResult:
        yield Static("CONFIG", classes="view-title")
        yield Static(
            "Edit a draft here. Ctrl+S reviews and saves every supported "
            "field atomically.",
            classes="view-subtitle",
        )
        with VerticalScroll(id="config-scroll"):
            yield Label("Startup & search", classes="config-heading")
            with Horizontal(classes="config-row"):
                yield Label("Preferred engine")
                yield Button("Choose…", id="config-engine")
            with Horizontal(classes="config-row"):
                yield Label("Language")
                yield Button("Choose…", id="config-language")
            with Horizontal(classes="config-row"):
                yield Label("Audio sync")
                yield Select(
                    [
                        ("Ask", "ask"),
                        ("Always", "always"),
                        ("Never", "never"),
                    ],
                    value="ask",
                    id="config-sync",
                )
            with Horizontal(classes="config-row"):
                yield Label("Hearing impaired")
                yield Select(
                    [
                        ("Include", "include"),
                        ("Exclude", "exclude"),
                        ("Only", "only"),
                    ],
                    value="include",
                    id="config-hi",
                )
            for label, widget_id in (
                ("Skip engine/language setup next run", "config-skip"),
                ("Use legacy CLI next run", "config-no-tui"),
                ("Force UTF-8", "config-utf8"),
                ("Auto-select best match", "config-auto"),
                ("Show AI-translated subtitles", "config-ai"),
                ("Clean ads after download", "config-clean"),
            ):
                with Horizontal(classes="config-row"):
                    yield Label(label)
                    yield Switch(id=widget_id)
            with Horizontal(classes="config-row"):
                yield Label("Ads pattern file")
                yield Input(
                    id="config-ads",
                    placeholder="Optional path to ads.txt",
                )
            yield Label("Provider languages", classes="config-heading")
            yield Static("", id="config-provider-languages")
        with Horizontal(id="config-actions"):
            yield Button("Save config", id="config-save", variant="primary")
            yield Button("Discard changes", id="config-discard")
            yield Static("", id="config-save-status")

    def refresh_from_state(self, app) -> None:
        config = app.config_draft
        self.query_one("#config-engine", Button).label = (
            "All providers"
            if config.general.preferred_backend is EngineMode.ALL_PROVIDERS
            else config.general.preferred_backend.label
        )
        self.query_one("#config-language", Button).label = (
            app.config_draft_language.upper()
        )
        status = self.query_one("#config-save-status", Static)
        if self.dirty:
            status.update("[yellow]Unsaved changes[/yellow]")
            return
        general = config.general
        with self.prevent(Switch.Changed, Select.Changed, Input.Changed):
            self.query_one("#config-sync", Select).value = general.sync_audio_to_subs
            self.query_one("#config-hi", Select).value = general.hearing_impaired
            self.query_one("#config-skip", Switch).value = general.skip_interactive_menu
            self.query_one("#config-no-tui", Switch).value = general.no_tui
            self.query_one("#config-utf8", Switch).value = general.opt_force_utf8
            self.query_one("#config-auto", Switch).value = general.auto_selection
            self.query_one("#config-ai", Switch).value = general.show_ai_translated
            self.query_one("#config-clean", Switch).value = config.cleaning.enabled
            self.query_one("#config-ads", Input).value = (
                str(config.cleaning.ads_file_path)
                if config.cleaning.ads_file_path
                else ""
            )
        lines = []
        for provider in Provider:
            languages = config.providers[provider].languages
            values = ", ".join(f"{name} ({code})" for name, code in languages.items())
            configured = (
                "configured"
                if config.providers[provider].configured
                else "credentials missing"
            )
            lines.append(
                f"[b]{provider.label}[/b] · {configured}\n"
                f"[dim]{values or 'No languages configured'}[/dim]"
            )
        self.query_one("#config-provider-languages", Static).update("\n\n".join(lines))
        status.update("[dim]No unsaved changes[/dim]")

    def mark_clean(self) -> None:
        self.dirty = False
        if self.is_mounted:
            self.app._refresh_topbar()

    @on(Switch.Changed)
    @on(Select.Changed)
    @on(Input.Changed)
    def mark_dirty(self) -> None:
        self.dirty = True
        self.query_one("#config-save-status", Static).update(
            "[yellow]Unsaved changes[/yellow]"
        )
        self.app._refresh_topbar()
