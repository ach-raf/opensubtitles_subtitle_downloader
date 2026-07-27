"""Production Textual command deck for multi-provider subtitle workflows."""

from __future__ import annotations

import copy
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Input,
    Select,
    Static,
    Switch,
)

from tui.config import (
    ApplicationConfig,
    ConfigDiff,
    ConfigRepository,
    normalize_sync_policy,
)
from tui.domain import (
    Candidate,
    EngineMode,
    HealthResult,
    HistoryEntry,
    Provider,
    QueueItem,
    QueueStatus,
    SearchRequest,
)
from tui.jobs import JobCoordinator
from tui.keymap import Action, Keymap
from tui.media import expand_media_paths
from tui.providers import create_adapters
from tui.search import CoordinatedSearchResult, SearchCoordinator
from tui.state import SessionState, native_name
from tui.widgets.overlays.engine_switcher import EngineSwitcher
from tui.widgets.overlays.lang_popover import LanguagePopover
from tui.widgets.overlays.palette import Palette
from tui.widgets.query_bar import QueryBar
from tui.widgets.results_table import ResultsTable
from tui.widgets.status_bar import StatusBar
from tui.widgets.topbar import TopBar
from tui.widgets.views import ConfigView, HistoryView, QueueView, SearchView

MEDIA_EXTENSIONS = {"avi", "m4v", "mkv", "mov", "mp4", "ts", "webm"}


class ConfirmReplace(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmReplace {
        align: center middle;
        background: rgba(3, 6, 11, 0.72);
    }
    ConfirmReplace > Vertical {
        width: 58;
        height: 9;
        padding: 1 2;
        background: #111820;
        border: round #e7b96a;
    }
    """
    BINDINGS = [
        Binding("y", "confirm", "Replace", show=False),
        Binding("n", "cancel", "Keep existing", show=False),
        Binding("escape", "cancel", "Keep existing", show=False),
    ]

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[b]Subtitle already exists[/b]")
            yield Static(
                f"{self.path.name}\n\n"
                "[b]y[/b] replace atomically   [b]n[/b] keep existing"
            )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmSync(ModalScreen[bool]):
    DEFAULT_CSS = ConfirmReplace.DEFAULT_CSS.replace(
        "ConfirmReplace",
        "ConfirmSync",
    )
    BINDINGS = [
        Binding("y", "confirm", "Sync", show=False),
        Binding("n", "cancel", "Do not sync", show=False),
        Binding("escape", "cancel", "Do not sync", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[b]Sync this subtitle to the media audio?[/b]")
            yield Static(
                "ffsubsync may take a moment.\n\n"
                "[b]y[/b] sync now   [b]n[/b] keep original timing"
            )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class CandidatePreview(ModalScreen[None]):
    DEFAULT_CSS = """
    CandidatePreview {
        align: center middle;
        background: rgba(3, 6, 11, 0.72);
    }
    CandidatePreview > Vertical {
        width: 72;
        max-width: 92%;
        height: 19;
        padding: 1 2;
        background: #111820;
        border: round #75a7ff;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("p", "close", "Close", show=False),
    ]

    def __init__(self, candidate: Candidate) -> None:
        super().__init__()
        self.candidate = candidate

    def compose(self) -> ComposeResult:
        candidate = self.candidate
        with Vertical():
            yield Static("[b]Candidate preview[/b]")
            yield Static(
                f"\n[b]{candidate.release}[/b]\n\n"
                f"Provider     {candidate.provider.label}\n"
                f"Language     {candidate.language.upper()}\n"
                f"Uploader     {candidate.author}\n"
                f"Downloads    {candidate.download_count:,}\n"
                f"Match score  {candidate.score:.0f}\n"
                f"Hash / HI / AI  "
                f"{'yes' if candidate.hash_match else 'no'} / "
                f"{'yes' if candidate.hearing_impaired else 'no'} / "
                f"{'yes' if candidate.ai_translated else 'no'}\n\n"
                "[dim]esc or p to close[/dim]"
            )

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmQuit(ModalScreen[bool]):
    DEFAULT_CSS = ConfirmReplace.DEFAULT_CSS.replace(
        "ConfirmReplace",
        "ConfirmQuit",
    )
    BINDINGS = [
        Binding("y", "confirm", "Quit", show=False),
        Binding("n", "cancel", "Stay", show=False),
        Binding("escape", "cancel", "Stay", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[b]Leave the command deck?[/b]")
            yield Static(
                "Queued work or unsaved settings may be left unfinished.\n\n"
                "[b]y[/b] quit   [b]n[/b] stay"
            )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmConfigSave(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmConfigSave {
        align: center middle;
        background: rgba(3, 6, 11, 0.72);
    }
    ConfirmConfigSave > Vertical {
        width: 68;
        max-width: 92%;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        background: #111820;
        border: round #e7b96a;
    }
    ConfirmConfigSave Horizontal {
        height: 3;
        margin-top: 1;
    }
    ConfirmConfigSave Button {
        width: 18;
        margin-right: 1;
    }
    """
    BINDINGS = [
        Binding("enter", "confirm", "Save", show=False),
        Binding("y", "confirm", "Save", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, diff: ConfigDiff) -> None:
        super().__init__()
        self.diff = diff

    def compose(self) -> ComposeResult:
        fields = self.diff.changed_fields
        visible = fields[:10]
        remaining = len(fields) - len(visible)
        lines = "\n".join(f"  • {field}" for field in visible)
        if remaining:
            lines += f"\n  • …and {remaining} more"
        with Vertical():
            yield Static("[b]Save configuration changes?[/b]")
            yield Static(
                f"\n{lines}\n\n"
                "[dim]Only field names are shown; secret values are never "
                "included.[/dim]"
            )
            with Horizontal():
                yield Button("Save", id="confirm-config-save", variant="primary")
                yield Button("Cancel", id="cancel-config-save")

    @on(Button.Pressed, "#confirm-config-save")
    def on_confirm(self) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#cancel-config-save")
    def on_cancel(self) -> None:
        self.action_cancel()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ConfirmConfigExit(ModalScreen[str | None]):
    DEFAULT_CSS = ConfirmConfigSave.DEFAULT_CSS.replace(
        "ConfirmConfigSave",
        "ConfirmConfigExit",
    )
    BINDINGS = [
        Binding("s", "save", "Save", show=False),
        Binding("d", "discard", "Discard", show=False),
        Binding("escape", "stay", "Stay", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[b]Unsaved configuration changes[/b]")
            yield Static(
                "\nSave the draft, discard it, or stay in Config.\n\n"
                "[b]s[/b] save   [b]d[/b] discard   [b]esc[/b] stay"
            )
            with Horizontal():
                yield Button("Save", id="exit-config-save", variant="primary")
                yield Button("Discard", id="exit-config-discard")
                yield Button("Stay", id="exit-config-stay")

    @on(Button.Pressed)
    def on_choice(self, event: Button.Pressed) -> None:
        result = {
            "exit-config-save": "save",
            "exit-config-discard": "discard",
            "exit-config-stay": None,
        }.get(event.button.id)
        self.dismiss(result)

    def action_save(self) -> None:
        self.dismiss("save")

    def action_discard(self) -> None:
        self.dismiss("discard")

    def action_stay(self) -> None:
        self.dismiss(None)


class SubsApp(App):
    CSS_PATH = "style.tcss"
    TITLE = "subs — command deck"

    BINDINGS = [
        Binding("1", "show_view('search')", "Search", show=False),
        Binding("2", "show_view('queue')", "Queue", show=False),
        Binding("3", "show_view('history')", "History", show=False),
        Binding("4", "show_view('config')", "Config", show=False),
        Binding("b", "open_engine", "Engine", show=False),
        Binding("B", "open_engine", "Engine", show=False),
        Binding("l", "open_language", "Language", show=False),
        Binding("L", "open_language", "Language", show=False),
        Binding("slash", "focus_query", "Query", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "download_cursor", "Download", show=False),
        Binding("p", "preview", "Preview", show=False),
        Binding("y", "copy_url", "Copy URL", show=False),
        Binding("m", "toggle_merge", "Merge", show=False),
        Binding("r", "reprobe", "Re-probe", show=False),
        Binding("ctrl+k", "open_palette", "Commands", show=False),
        Binding("ctrl+s", "save_config", "Save config", show=False),
        Binding("escape", "focus_workspace", "Back to workspace", show=False),
        Binding("question_mark", "help", "Help", show=False),
        Binding("q", "request_quit", "Quit", show=False),
    ]

    candidates: reactive[list[Candidate]] = reactive(list, layout=False)
    cursor_index: reactive[int] = reactive(0, layout=False)
    query: reactive[str] = reactive("", layout=False)
    merge_mode: reactive[bool] = reactive(False, layout=False)
    searching: reactive[bool] = reactive(False, layout=False)
    downloading: reactive[bool] = reactive(False, layout=False)
    last_error: reactive[str | None] = reactive(None, layout=False)
    notice: reactive[str] = reactive("", layout=False)
    health: reactive[dict[Provider, HealthResult]] = reactive(
        dict,
        layout=False,
    )

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        media_paths: list[str] | None = None,
        overrides: dict[str, Any] | None = None,
        config_path: str | None = None,
        *,
        coordinator: SearchCoordinator | None = None,
        jobs: JobCoordinator | None = None,
    ) -> None:
        super().__init__()
        self.raw_config = copy.deepcopy(config or {})
        self.overrides = overrides or {}
        self.config_path = Path(config_path) if config_path else None
        self.config_repository = ConfigRepository(
            self.config_path or Path("config.yaml")
        )
        if self.config_path and self.config_path.exists():
            self.application_config = self.config_repository.load()
        else:
            self.application_config = ConfigRepository(
                Path("__missing_config__.yaml")
            ).load()
            self._overlay_raw_config(self.raw_config)
        self._apply_overrides()
        self.set_reactive(
            SubsApp.merge_mode,
            self.application_config.general.merge_results,
        )
        self.config_draft = copy.deepcopy(self.application_config)
        self.config_draft_language = ""
        self._pending_config_draft: ApplicationConfig | None = None
        self._pending_config_language: str | None = None
        self._after_config_save: Callable[[], None] | None = None

        expansion = expand_media_paths(media_paths or [], MEDIA_EXTENSIONS)
        queue = [
            QueueItem(
                key=str(path),
                path=path,
                language=self._initial_language(),
                engine_mode=self.application_config.general.preferred_backend,
            )
            for path in expansion.paths
        ]
        self.media_issues = expansion.issues
        self.state = SessionState.from_config(self.application_config, queue)
        if language := self.overrides.get("lang"):
            self.state.set_language(str(language), scope="remaining")
        if engine := self.overrides.get("backend"):
            mode = EngineMode(str(engine))
            if mode is not EngineMode.ASK:
                self.state.choose_engine(mode)

        self.adapters = create_adapters(self.application_config)
        selected_provider = self.state.engine_mode.provider
        if selected_provider and selected_provider not in self.adapters:
            self.state.engine_mode = EngineMode.ASK
            for item in self.state.queue:
                item.engine_mode = EngineMode.ASK
        self.coordinator = coordinator or SearchCoordinator(self.adapters)
        self.jobs = jobs or JobCoordinator(self.adapters)
        self.keymap = Keymap()
        self._rebuild_keymap()
        self.last_search_request: SearchRequest | None = None
        self._pending_download: Candidate | None = None
        self.search_generation = 0
        self._language_provider_scope: set[Provider] = set()
        self.config_draft_language = self.state.language

    def compose(self) -> ComposeResult:
        yield TopBar()
        with ContentSwitcher(initial="search-view", id="workspace"):
            yield SearchView(id="search-view")
            yield QueueView(id="queue-view")
            yield HistoryView(id="history-view")
            yield ConfigView(id="config-view")
        yield StatusBar()

    def on_mount(self) -> None:
        active = self.state.active_item
        self.query = active.path.stem if active else ""
        self._refresh_all()
        if self.media_issues:
            self.notice = (
                f"{len(self.media_issues)} input"
                f"{'s' if len(self.media_issues) != 1 else ''} skipped"
            )
        if self.state.needs_engine_setup:
            self.call_after_refresh(self.action_open_engine)
        elif self.state.needs_language_setup:
            self.call_after_refresh(self.action_open_language)
        elif active:
            self.call_after_refresh(self.start_search)

    def _overlay_raw_config(self, raw: dict[str, Any]) -> None:
        general = raw.get("general") or {}
        for name in (
            "merge_results",
            "skip_interactive_menu",
            "auto_selection",
            "opt_force_utf8",
            "no_tui",
            "hearing_impaired",
            "show_ai_translated",
        ):
            if name in general:
                setattr(self.application_config.general, name, general[name])
        if "sync_audio_to_subs" in general:
            self.application_config.general.sync_audio_to_subs = normalize_sync_policy(
                general["sync_audio_to_subs"]
            )
        if "preferred_backend" in general:
            try:
                self.application_config.general.preferred_backend = EngineMode(
                    str(general["preferred_backend"])
                )
            except ValueError:
                self.application_config.general.preferred_backend = EngineMode.ASK
        for provider in Provider:
            values = raw.get(provider.value) or {}
            self.application_config.providers[provider].values = {
                key: value for key, value in values.items() if key != "languages"
            }
            self.application_config.providers[provider].languages = {
                str(name): str(code)
                for name, code in (values.get("languages") or {}).items()
            }
        cleaning = raw.get("cleaning_subtitles") or {}
        self.application_config.cleaning.enabled = bool(cleaning.get("enabled", True))
        ads = cleaning.get("ads") or {}
        ads_path = str(ads.get("file_path") or "").strip()
        self.application_config.cleaning.ads_file_path = (
            Path(ads_path) if ads_path else None
        )
        self.application_config.cleaning.separator = str(ads.get("separator", ","))
        self.application_config.cleaning.supported_media = list(
            cleaning.get("supported_media") or []
        )

    def _apply_overrides(self) -> None:
        if backend := self.overrides.get("backend"):
            self.application_config.general.preferred_backend = EngineMode(str(backend))
            self.application_config.general.merge_results = False
        if self.overrides.get("lang"):
            self.application_config.general.skip_interactive_menu = True

    def _initial_language(self) -> str:
        if language := self.overrides.get("lang"):
            return str(language).lower()
        mode = self.application_config.general.preferred_backend
        providers = [mode.provider] if mode.provider else list(Provider)
        for provider in providers:
            languages = self.application_config.providers[provider].languages
            if languages:
                return next(iter(languages.values())).lower()
        return "en"

    def current_candidate(self) -> Candidate | None:
        if 0 <= self.cursor_index < len(self.candidates):
            return self.candidates[self.cursor_index]
        return None

    def start_search(self) -> None:
        item = self.state.active_item
        if item is None or self.state.engine_mode is EngineMode.ASK:
            return
        if item.status is not QueueStatus.QUEUED:
            item.status = QueueStatus.QUEUED
            item.candidate_keys.clear()
        request = SearchRequest(
            media_path=item.path,
            query=self.query.strip() or item.path.stem,
            language=item.language,
            hearing_impaired=self.application_config.general.hearing_impaired,
            show_ai_translated=(self.application_config.general.show_ai_translated),
        )
        self.last_search_request = request
        self.search_generation += 1
        self.run_search(
            item.key,
            self.search_generation,
            request,
            self.state.engine_mode,
            self.merge_mode,
        )

    @work(thread=True, exclusive=True, group="search")
    def run_search(
        self,
        item_key: str,
        generation: int,
        request: SearchRequest,
        mode: EngineMode,
        merge: bool,
    ) -> None:
        self.call_from_thread(self._search_started, item_key, generation)
        if merge:
            result = self.coordinator.merge(request, self.health)
        elif mode is EngineMode.AUTO:
            result = self.coordinator.auto(request, self.health)
        elif mode.provider:
            result = self.coordinator.concrete(mode.provider, request)
        else:
            result = CoordinatedSearchResult()
        self.call_from_thread(
            self._search_finished,
            item_key,
            generation,
            request,
            result,
        )

    def _search_started(self, item_key: str, generation: int) -> None:
        if generation != self.search_generation:
            return
        self.searching = True
        self.last_error = None
        self.state.begin_search(item_key)
        self._refresh_queue()

    def _search_finished(
        self,
        item_key: str,
        generation: int,
        request: SearchRequest,
        result: CoordinatedSearchResult,
    ) -> None:
        active = self.state.active_item
        if (
            generation != self.search_generation
            or active is None
            or active.key != item_key
            or request is not self.last_search_request
        ):
            return
        self.searching = False
        summary = "; ".join(
            f"{provider.label}: {error}" for provider, error in result.errors.items()
        )
        if result.errors and not result.candidates:
            self.state.mark_failed(item_key, summary)
            self.candidates = []
            self.last_error = summary
            self._advance_queue()
            return
        self.state.set_candidates(item_key, result.candidates)
        self.candidates = result.candidates
        self.cursor_index = 0
        if result.errors:
            self.notice = f"Partial results · {summary}"
        elif not result.candidates:
            self.notice = "No subtitles found. Try a broader query or Merge."
        else:
            self.notice = f"{len(result.candidates)} candidates ready"
        self._refresh_all()
        self.call_after_refresh(self._focus_results)
        if result.candidates and self.application_config.general.auto_selection:
            self.action_download_cursor()

    def _focus_results(self) -> None:
        if self.candidates and self.state.active_view == "search":
            self.query_one(ResultsTable).focus()

    def action_show_view(self, view: str) -> None:
        if (
            view != "config"
            and self.state.active_view == "config"
            and self.query_one(ConfigView).dirty
        ):
            self.push_screen(
                ConfirmConfigExit(),
                lambda decision: self._config_exit_decided(decision, view),
            )
            return
        if view == "config" and self.state.active_view != "config":
            self.config_draft = copy.deepcopy(self.application_config)
            self.config_draft_language = self.state.language
            self.query_one(ConfigView).mark_clean()
        self._finish_view_change(view)

    def _finish_view_change(self, view: str) -> None:
        self.state.active_view = view
        self.query_one("#workspace", ContentSwitcher).current = f"{view}-view"
        self._refresh_topbar()
        {
            "search": self._refresh_search,
            "queue": self._refresh_queue,
            "history": self._refresh_history,
            "config": self._refresh_config,
        }[view]()
        self._refresh_status()
        self.call_after_refresh(self.action_focus_workspace)

    def _config_exit_decided(self, decision: str | None, view: str) -> None:
        if decision == "discard":
            self._discard_config_draft()
            self._finish_view_change(view)
        elif decision == "save":
            self._request_config_save(after_save=lambda: self._finish_view_change(view))

    def action_focus_query(self) -> None:
        self.action_show_view("search")
        self.call_after_refresh(lambda: self.query_one("#query-input", Input).focus())

    def action_focus_workspace(self) -> None:
        selector = {
            "search": ("#results-table" if self.candidates else "#query-input"),
            "queue": "#queue-table",
            "history": "#history-table",
            "config": "#config-engine",
        }[self.state.active_view]
        self.query_one(selector).focus()

    def action_cursor_down(self) -> None:
        if isinstance(self.focused, Input):
            return
        if isinstance(self.focused, DataTable):
            self.focused.action_cursor_down()
            return
        if self.candidates:
            self.cursor_index = min(
                self.cursor_index + 1,
                len(self.candidates) - 1,
            )

    def action_cursor_up(self) -> None:
        if isinstance(self.focused, Input):
            return
        if isinstance(self.focused, DataTable):
            self.focused.action_cursor_up()
            return
        self.cursor_index = max(0, self.cursor_index - 1)

    def action_toggle_merge(self) -> None:
        self.merge_mode = not self.merge_mode
        self.notice = (
            "Merge searches all configured providers"
            if self.merge_mode
            else "Merge off"
        )
        self._refresh_all()

    def action_reprobe(self) -> None:
        self.run_health_probe()

    @work(thread=True, exclusive=True, group="health")
    def run_health_probe(self) -> None:
        results = {
            provider: adapter.health() for provider, adapter in self.adapters.items()
        }
        self.call_from_thread(self._health_finished, results)

    def _health_finished(
        self,
        results: dict[Provider, HealthResult],
    ) -> None:
        self.health = results
        self.notice = "Provider diagnostics refreshed"
        self._refresh_all()

    def action_open_engine(self) -> None:
        current = self.state.engine_mode
        if self.state.active_view == "config":
            current = self.config_draft.general.preferred_backend
        self.push_screen(
            EngineSwitcher(
                current=current,
                health=self.health,
                merge_mode=self.merge_mode,
                configured=set(self.adapters),
            ),
            self._engine_chosen,
        )

    def _engine_chosen(self, result) -> None:
        if not result:
            return
        mode, merge = result
        if self.state.active_view == "config":
            self.config_draft.general.preferred_backend = mode
            self.config_draft.general.merge_results = merge
            view = self.query_one(ConfigView)
            view.mark_dirty()
            view.refresh_from_state(self)
            return
        self.merge_mode = merge
        self.state.choose_engine(mode)
        self.application_config.general.preferred_backend = mode
        self.application_config.general.merge_results = merge
        self._refresh_all()
        if self.state.needs_language_setup:
            self.action_open_language()
        else:
            self.start_search()

    def action_open_language(self) -> None:
        mode = self.state.engine_mode
        config = self.application_config
        if self.state.active_view == "config":
            config = self.config_draft
            mode = config.general.preferred_backend
        if self.merge_mode or mode in {EngineMode.AUTO, EngineMode.ASK}:
            provider_scope = set(self.adapters) or set(Provider)
        else:
            provider_scope = {mode.provider} if mode.provider else set(Provider)
        self._language_provider_scope = provider_scope
        languages: dict[str, str] = {}
        for provider in provider_scope:
            provider_config = config.providers[provider]
            for name, code in provider_config.languages.items():
                languages.setdefault(code.lower(), name)
        current_language = (
            self.config_draft_language
            if self.state.active_view == "config"
            else self.state.language
        )
        languages.setdefault(current_language, native_name(current_language))
        remaining = [
            str(item.path)
            for item in self.state.queue
            if item.status
            not in {QueueStatus.DONE, QueueStatus.FAILED, QueueStatus.SKIPPED}
        ]
        self.push_screen(
            LanguagePopover(
                languages=languages,
                current=current_language,
                needs_scope_confirm=len(remaining) > 1,
                remaining_files=remaining,
            ),
            self._language_chosen,
        )

    def _language_chosen(self, result) -> None:
        if not result:
            return
        code, scope = result
        if self.state.active_view == "config":
            self.config_draft_language = code
            for provider in self._language_provider_scope:
                provider_config = self.config_draft.providers[provider]
                if code not in provider_config.languages.values():
                    provider_config.languages[native_name(code)] = code
            view = self.query_one(ConfigView)
            view.mark_dirty()
            view.refresh_from_state(self)
            return
        normalized_scope = "remaining" if scope == "all" else scope
        self.state.set_language(code, normalized_scope)
        for provider in self._language_provider_scope:
            provider_config = self.application_config.providers[provider]
            if code not in provider_config.languages.values():
                provider_config.languages[native_name(code)] = code
        self._refresh_all()
        self.start_search()

    def action_open_palette(self) -> None:
        self._rebuild_keymap()
        self.push_screen(Palette(self.keymap), self._palette_chosen)

    def _palette_chosen(self, action) -> None:
        if action and action.run:
            action.run(self)

    def _rebuild_keymap(self) -> None:
        actions = Keymap().actions
        language_codes = {
            code.lower()
            for provider in self.application_config.providers.values()
            for code in provider.languages.values()
        }
        for code in sorted(language_codes):
            actions.append(
                Action(
                    f"lang.set.{code}",
                    f"Set language to {native_name(code)} ({code})",
                    "language",
                    run=lambda app, code=code: app._set_language_action(code),
                )
            )
        for provider in Provider:
            mode = EngineMode(provider.value)
            actions.append(
                Action(
                    f"engine.set.{provider.value}",
                    f"Use {provider.label}",
                    "engine",
                    run=lambda app, mode=mode: app._set_engine_action(mode),
                )
            )
        self.keymap = Keymap(actions)

    def _set_language_action(self, code: str) -> None:
        self.state.set_language(code)
        self.start_search()

    def _set_engine_action(self, mode: EngineMode) -> None:
        self.state.choose_engine(mode)
        self.application_config.general.preferred_backend = mode
        self.start_search()

    def action_download_cursor(self) -> None:
        candidate = self.current_candidate()
        item = self.state.active_item
        if candidate is None or item is None or self.downloading:
            return
        self._pending_download = candidate
        self.run_download(item.key, candidate, False)

    def action_copy_url(self) -> None:
        candidate = self.current_candidate()
        if candidate is None:
            return
        if candidate.public_url is None:
            self.notice = "This provider has no safe public URL to copy"
        else:
            self.copy_to_clipboard(candidate.public_url)
            self.notice = "Public URL copied"
        self._refresh_status()

    def action_preview(self) -> None:
        candidate = self.current_candidate()
        if candidate:
            self.push_screen(CandidatePreview(candidate))

    @work(thread=True, exclusive=True, group="download")
    def run_download(
        self,
        item_key: str,
        candidate: Candidate,
        overwrite: bool,
    ) -> None:
        self.call_from_thread(self._download_started, item_key, candidate.key)
        item = next(item for item in self.state.queue if item.key == item_key)
        try:
            download = self.jobs.download(
                candidate,
                item.path,
                overwrite=overwrite,
            )
            sync_policy = self.application_config.general.sync_audio_to_subs
            if download.succeeded and sync_policy == "ask":
                self.call_from_thread(
                    self._request_sync,
                    item_key,
                    candidate,
                    download,
                )
                return
            postprocess = self.jobs.postprocess(
                download,
                force_utf8=self.application_config.general.opt_force_utf8,
                clean=self.application_config.cleaning.enabled,
                sync=sync_policy == "always",
                ads_path=self.application_config.cleaning.ads_file_path,
            )
        except Exception as exc:
            self.call_from_thread(
                self._download_crashed,
                item_key,
                f"{type(exc).__name__}: {exc}",
            )
            return
        self.call_from_thread(
            self._download_finished,
            item_key,
            candidate,
            download,
            postprocess,
        )

    def _request_sync(
        self,
        item_key: str,
        candidate: Candidate,
        download,
    ) -> None:
        self.push_screen(
            ConfirmSync(),
            lambda confirmed: self.run_postprocess(
                item_key,
                candidate,
                download,
                confirmed,
            ),
        )

    @work(thread=True, exclusive=True, group="postprocess")
    def run_postprocess(
        self,
        item_key: str,
        candidate: Candidate,
        download,
        sync: bool,
    ) -> None:
        try:
            postprocess = self.jobs.postprocess(
                download,
                force_utf8=self.application_config.general.opt_force_utf8,
                clean=self.application_config.cleaning.enabled,
                sync=sync,
                ads_path=self.application_config.cleaning.ads_file_path,
            )
        except Exception as exc:
            self.call_from_thread(
                self._download_crashed,
                item_key,
                f"{type(exc).__name__}: {exc}",
            )
            return
        self.call_from_thread(
            self._download_finished,
            item_key,
            candidate,
            download,
            postprocess,
        )

    def _download_started(self, item_key: str, candidate_key: str) -> None:
        item = next(item for item in self.state.queue if item.key == item_key)
        if item.status is not QueueStatus.AWAITING_PICK:
            item.status = QueueStatus.AWAITING_PICK
        self.state.begin_download(item_key, candidate_key)
        self.downloading = True
        self._refresh_all()

    def _download_finished(
        self,
        item_key: str,
        candidate: Candidate,
        download,
        postprocess,
    ) -> None:
        self.downloading = False
        if download.conflict_path:
            item = next(item for item in self.state.queue if item.key == item_key)
            item.status = QueueStatus.AWAITING_PICK
            self.push_screen(
                ConfirmReplace(download.conflict_path),
                lambda confirmed: self._replace_decided(
                    confirmed,
                    item_key,
                    candidate,
                ),
            )
            self._refresh_all()
            return
        if not download.succeeded:
            self.state.mark_failed(item_key, download.error or "Download failed")
            self.last_error = download.error
            self._advance_queue()
            return
        history = HistoryEntry(
            item_key=item_key,
            media_path=download.media_path,
            candidate_key=candidate.key,
            provider=candidate.provider,
            language=candidate.language,
            subtitle_path=download.subtitle_path,
            postprocess=postprocess,
            error=None,
        )
        self.state.mark_complete(item_key, history)
        self.notice = f"Saved {download.subtitle_path.name}"
        self.candidates = []
        self._refresh_all()
        if self.state.active_item:
            self.query = self.state.active_item.path.stem
            self.start_search()

    def _replace_decided(
        self,
        confirmed: bool,
        item_key: str,
        candidate: Candidate,
    ) -> None:
        if confirmed:
            self.run_download(item_key, candidate, True)
        else:
            self.notice = "Kept the existing subtitle"
            self._refresh_all()

    def _download_crashed(self, item_key: str, error: str) -> None:
        self.downloading = False
        self.state.mark_failed(item_key, error)
        self.last_error = error
        self._advance_queue()

    def _advance_queue(self) -> None:
        self._refresh_all()
        item = self.state.active_item
        if item:
            self.query = item.path.stem
            self.start_search()

    def action_help(self) -> None:
        self.notify(
            "1–4 views · b engine · l language · / query · "
            "j/k move · Enter download · m merge · q quit",
            title="Command deck shortcuts",
            timeout=8,
        )

    def action_request_quit(self) -> None:
        config_dirty = self.query_one(ConfigView).dirty
        unfinished = any(
            item.status
            not in {QueueStatus.DONE, QueueStatus.FAILED, QueueStatus.SKIPPED}
            for item in self.state.queue
        )
        if self.searching or self.downloading or unfinished or config_dirty:
            self.push_screen(
                ConfirmQuit(),
                lambda confirmed: self.exit() if confirmed else None,
            )
            return
        self.exit()

    def on_resize(self, event) -> None:
        try:
            width = event.size.width
            self.query_one("#detail-panel").display = width >= 115
            self.query_one("#chip-health").display = width >= 120
            self.query_one("#chip-command").display = width >= 105
            self.query_one("#status-settings").display = width >= 110
            self.query_one("#status-progress").display = width >= 70
            self.query_one("#status-hints").display = width >= 60
        except NoMatches:
            return

    @on(Input.Submitted, "#query-input")
    def on_query_submitted(self, event: Input.Submitted) -> None:
        self.query = event.value.strip()
        self.start_search()

    @on(Button.Pressed, "#query-submit")
    def on_query_button(self) -> None:
        self.query = self.query_one("#query-input", Input).value.strip()
        self.start_search()

    @on(DataTable.RowHighlighted, "#results-table")
    def on_result_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row != self.query_one(ResultsTable).cursor_row:
            return
        self.cursor_index = event.cursor_row

    @on(DataTable.RowSelected, "#results-table")
    def on_result_selected(self) -> None:
        self.action_download_cursor()

    @on(Button.Pressed)
    def on_button(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("tab-"):
            self.action_show_view(button_id.removeprefix("tab-"))
        elif button_id in {"chip-engine", "config-engine"}:
            self.action_open_engine()
        elif button_id in {"chip-language", "config-language"}:
            self.action_open_language()
        elif button_id == "chip-command":
            self.action_open_palette()
        elif button_id == "download-selected":
            self.action_download_cursor()
        elif button_id == "preview-selected":
            self.action_preview()
        elif button_id == "copy-url":
            self.action_copy_url()
        elif button_id == "config-save":
            self.action_save_config()
        elif button_id == "config-discard":
            self._discard_config_draft()
        elif button_id == "queue-skip":
            item = self.state.active_item
            if item:
                self.state.skip(item.key)
                self.notice = f"Skipped {item.path.name}"
                self._advance_queue()
        elif button_id == "queue-retry":
            failed = next(
                (
                    item
                    for item in self.state.queue
                    if item.status is QueueStatus.FAILED
                ),
                None,
            )
            if failed:
                self.state.retry(failed.key)
                self.notice = f"Retrying {failed.path.name}"
                self._refresh_all()
                self.start_search()

    def action_save_config(self) -> None:
        if self.state.active_view != "config":
            self.notice = "Open Config before saving settings"
            self._refresh_status()
            return
        self._request_config_save()

    def _draft_from_config_view(self) -> ApplicationConfig:
        view = self.query_one(ConfigView)
        draft = copy.deepcopy(self.config_draft)
        general = draft.general
        general.sync_audio_to_subs = str(view.query_one("#config-sync", Select).value)
        general.hearing_impaired = str(view.query_one("#config-hi", Select).value)
        general.skip_interactive_menu = view.query_one("#config-skip", Switch).value
        general.no_tui = view.query_one("#config-no-tui", Switch).value
        general.opt_force_utf8 = view.query_one("#config-utf8", Switch).value
        general.auto_selection = view.query_one("#config-auto", Switch).value
        general.show_ai_translated = view.query_one("#config-ai", Switch).value
        draft.cleaning.enabled = view.query_one("#config-clean", Switch).value
        ads = view.query_one("#config-ads", Input).value.strip()
        draft.cleaning.ads_file_path = Path(ads) if ads else None
        return draft

    def _request_config_save(
        self,
        *,
        after_save: Callable[[], None] | None = None,
    ) -> None:
        draft = self._draft_from_config_view()
        diff = self.config_repository.preview_diff(draft)
        changed_fields = list(diff.changed_fields)
        if self.config_draft_language != self.state.language:
            changed_fields.append("session.language")
        diff = ConfigDiff(changed_fields=sorted(changed_fields))
        if not changed_fields:
            self.config_draft = draft
            self.query_one(ConfigView).mark_clean()
            self.notice = "Configuration is already up to date"
            self._refresh_all()
            if after_save:
                after_save()
            return
        self._pending_config_draft = draft
        self._pending_config_language = self.config_draft_language
        self._after_config_save = after_save
        self.push_screen(ConfirmConfigSave(diff), self._config_save_decided)

    def _config_save_decided(self, confirmed: bool) -> None:
        draft = self._pending_config_draft
        language = self._pending_config_language
        after_save = self._after_config_save
        self._pending_config_draft = None
        self._pending_config_language = None
        self._after_config_save = None
        if not confirmed or draft is None:
            self.notice = "Configuration save cancelled"
            self._refresh_status()
            return
        preferred = draft.general.preferred_backend
        merge_changed = draft.general.merge_results != self.merge_mode
        engine_changed = (
            preferred is not EngineMode.ASK and preferred is not self.state.engine_mode
        ) or merge_changed
        language_changed = bool(language and language != self.state.language)
        if not self.config_path:
            self.notice = "Session updated; no config path was supplied"
        else:
            try:
                diff = self.config_repository.save(draft)
            except Exception as exc:
                self.last_error = (
                    "Could not save configuration "
                    f"({type(exc).__name__}); draft kept"
                )
                self._refresh_all()
                return
            self.notice = (
                f"Saved {len(diff.changed_fields)} config field"
                f"{'s' if len(diff.changed_fields) != 1 else ''}"
            )
        self.application_config = copy.deepcopy(draft)
        self.config_draft = copy.deepcopy(draft)
        self.merge_mode = draft.general.merge_results
        if preferred is not EngineMode.ASK:
            self.state.choose_engine(preferred)
        if language:
            self.state.set_language(language)
        restart_search = False
        item = self.state.active_item
        if (
            (engine_changed or language_changed)
            and item is not None
            and item.status
            in {
                QueueStatus.QUEUED,
                QueueStatus.SEARCHING,
                QueueStatus.AWAITING_PICK,
            }
        ):
            self.search_generation += 1
            self.searching = False
            self.state.restart_search(item.key)
            self.candidates = []
            self.cursor_index = 0
            restart_search = True
        self.last_error = None
        self.query_one(ConfigView).mark_clean()
        self._refresh_all()
        if after_save:
            after_save()
        if restart_search:
            self.start_search()

    def _discard_config_draft(self) -> None:
        self.config_draft = copy.deepcopy(self.application_config)
        self.config_draft_language = self.state.language
        view = self.query_one(ConfigView)
        view.mark_clean()
        view.refresh_from_state(self)
        self.notice = "Discarded unsaved configuration changes"
        self._refresh_status()

    def watch_candidates(self, _value) -> None:
        self._refresh_search()

    def watch_cursor_index(self, _value) -> None:
        with suppress(NoMatches):
            self.query_one(ResultsTable).sync_cursor(self.cursor_index)
        self._safe_refresh_by_id("#detail-panel")

    def watch_query(self, _value) -> None:
        self._refresh_query()

    def watch_searching(self, _value) -> None:
        self._refresh_status()

    def watch_downloading(self, _value) -> None:
        self._refresh_status()

    def watch_last_error(self, _value) -> None:
        self._refresh_status()

    def watch_notice(self, _value) -> None:
        self._refresh_status()

    def watch_merge_mode(self, _value) -> None:
        self._refresh_status()

    def _refresh_all(self) -> None:
        self._refresh_topbar()
        self._refresh_query()
        self._refresh_search()
        self._refresh_queue()
        self._refresh_history()
        self._refresh_config()
        self._refresh_status()

    def _refresh_topbar(self) -> None:
        self._safe_refresh(TopBar)

    def _refresh_query(self) -> None:
        self._safe_refresh(QueryBar)

    def _refresh_search(self) -> None:
        self._safe_refresh(SearchView)
        self._safe_refresh(ResultsTable)
        self._safe_refresh_by_id("#detail-panel")

    def _refresh_queue(self) -> None:
        self._safe_refresh(QueueView)

    def _refresh_history(self) -> None:
        self._safe_refresh(HistoryView)

    def _refresh_config(self) -> None:
        self._safe_refresh(ConfigView)

    def _refresh_status(self) -> None:
        self._safe_refresh(StatusBar)

    def _safe_refresh(self, widget_type) -> None:
        try:
            self.query_one(widget_type).refresh_from_state(self)
        except NoMatches:
            return

    def _safe_refresh_by_id(self, selector: str) -> None:
        try:
            self.query_one(selector).refresh_from_state(self)
        except NoMatches:
            return


def run_tui(
    *,
    config: dict[str, Any],
    media_paths: list[str],
    overrides: dict[str, Any],
    config_path: str,
) -> None:
    SubsApp(
        config=config,
        media_paths=media_paths,
        overrides=overrides,
        config_path=config_path,
    ).run()
