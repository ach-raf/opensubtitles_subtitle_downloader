"""SubsApp — the Textual command deck.

Phase 2 wires the §01 main screen to real state: TopBar, QueryBar, ResultsTable,
DetailPane, StatusBar. Phase 3 adds the live overlays: language popover (L),
engine switcher (B), command palette (⌘K / Ctrl+K), merge toggle (m),
re-probe (r). The App owns the source-of-truth state as Textual ``reactive``
attributes; mutating them re-renders the affected widgets via the ``watch_*``
hooks. A ``@work`` SearchWorker runs the first media-path search on mount
without blocking the UI.

Keyboard:
    j / k       move cursor in the results table
    Enter       download the cursor row (Phase 4 wires the real worker)
    /           focus the query input
    L           open the language popover (scope-confirm if a batch is in flight)
    B           open the engine switcher (live health + latency)
    m           toggle merge mode (fan out to all engines)
    r           re-probe engine health + latency
    ⌘K / Ctrl+K open the command palette
    q           quit

Multilingual names render via UTF-8 (spec §11); the App sets no special encoding
because Textual is UTF-8 by default and relies on the terminal font.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Static

from tui.keymap import Keymap
from tui.services import (
    ConfigIO,
    DownloadWorker,
    HealthProbe,
    SearchWorker,
)
from tui.state import (
    HI_POLICY_VALUES,
    SYNC_POLICY_VALUES,
    AppState,
    Backend,
    EngineHealth,
    HistoryEntry,
    QueueItem,
    RunPolicy,
    native_name,
)
from tui.widgets.config_tab import ConfigTab
from tui.widgets.detail_pane import DetailPane
from tui.widgets.overlays.engine_switcher import EngineSwitcher
from tui.widgets.overlays.lang_popover import LanguagePopover
from tui.widgets.overlays.palette import Palette
from tui.widgets.overlays.post_download_toast import PostAction, PostDownloadToast
from tui.widgets.query_bar import QueryBar
from tui.widgets.results_table import ResultsTable
from tui.widgets.status_bar import StatusBar
from tui.widgets.topbar import TopBar

logger = logging.getLogger("tui.app")

_CSS_PATH = "style.tcss"


class SubsApp(App):
    """The subtitle downloader command deck."""

    CSS_PATH = _CSS_PATH

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("enter", "download_cursor", "Download", show=False),
        Binding("slash", "focus_query", "Filter", show=False),
        Binding("L", "open_language", "Language", show=False),
        Binding("B", "open_engine", "Engine", show=False),
        Binding("m", "toggle_merge", "Merge", show=False),
        Binding("r", "reprobe", "Re-probe", show=False),
        Binding("ctrl+k", "open_palette", "Palette", show=False),
        Binding("4", "open_config", "Config", show=False),
    ]

    # ---- Source-of-truth reactives (Phase 2 subset) -----------------------
    # These mirror AppState fields 1:1. Later phases add more (history tab,
    # config tab) without renaming these.
    backend: reactive[Backend] = reactive(Backend.OPENSUBTITLES, layout=False)
    language: reactive[str] = reactive("en", layout=False)
    merge_mode: reactive[bool] = reactive(False, layout=False)
    run_policy: reactive[RunPolicy] = reactive(RunPolicy, layout=False)
    query: reactive[str] = reactive("", layout=False)
    results: reactive[List[dict]] = reactive(list, layout=False)
    scores: reactive[Dict[str, float]] = reactive(dict, layout=False)
    cursor_index: reactive[int] = reactive(0, layout=False)
    engine_health: reactive[Dict[str, EngineHealth]] = reactive(dict, layout=False)
    last_error: reactive[Optional[str]] = reactive(None, layout=False)
    searching: reactive[bool] = reactive(False, layout=False)

    def __init__(
        self,
        config: Optional[dict] = None,
        media_paths: Optional[List[str]] = None,
        overrides: Optional[dict] = None,
        config_path: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.config: Dict[str, Any] = config or {}
        self.media_paths: List[str] = list(media_paths or [])
        self.overrides: Dict[str, Any] = overrides or {}
        self.history: List[HistoryEntry] = []
        # Plain (non-reactive) queue; Phase 2 only ever has the first file.
        self.queue: List[QueueItem] = []
        self.languages: Dict[str, str] = {"en": "English"}

        # Services — constructed from config. They import library/* lazily.
        self.search_worker = SearchWorker(self.config)
        self.download_worker = DownloadWorker(self.config)
        self.health_probe = HealthProbe(self.config)
        self.config_path: Optional[str] = config_path
        # The command palette indexes this; rebuilt on mount + when languages
        # / engines change so dynamic actions stay current.
        self.keymap = Keymap()

    # ---- Lifecycle --------------------------------------------------------
    def on_mount(self) -> None:
        self._seed_from_config()
        # Seed the queue from media_paths so the StatusBar shows progress.
        if self.media_paths:
            for p in self.media_paths:
                self.queue.append(QueueItem(path=p, name=Path(p).stem))
        self._rebuild_keymap()
        self._refresh_all_widgets()
        # Default focus on the results table so j/k work immediately; '/' jumps
        # to the query input.
        try:
            self.query_one(ResultsTable).focus()
        except Exception:  # noqa: BLE001
            pass
        # Probe engine health in the background so the badges populate.
        self.run_health_probe(force=False)
        if self.media_paths:
            self.run_search(self.media_paths[0])

    def _seed_from_config(self) -> None:
        """Translate config.yaml into the reactive seed values."""
        try:
            policy = ConfigIO.run_policy_from_config(self.config)
        except Exception as exc:  # noqa: BLE001
            logger.warning("run_policy_from_config failed: %s", exc)
            policy = RunPolicy()
        self.run_policy = policy

        try:
            self.languages = ConfigIO.languages_from_config(self.config)
        except Exception:  # noqa: BLE001
            self.languages = {"en": "English"}

        backend = ConfigIO.backend_from_config(
            self.config, override=self.overrides.get("backend")
        )
        self.backend = backend

        lang_override = self.overrides.get("lang")
        if lang_override:
            self.language = lang_override.lower()
        elif self.languages:
            # Default to the first configured language.
            self.language = next(iter(self.languages))

    # ---- Compose ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield TopBar()
        yield QueryBar()
        yield Container(
            Container(
                Static("[dim]results · sorted by match[/dim]", classes="panel-h", markup=True),
                ResultsTable(),
                id="results-panel",
            ),
            DetailPane(id="detail-panel"),
            id="main-split",
        )
        yield StatusBar()

    # ---- Helpers exposed to widgets --------------------------------------
    def current_result(self) -> Optional[dict]:
        """The result row under the cursor, or None."""
        if not self.results:
            return None
        idx = self.cursor_index
        if idx < 0 or idx >= len(self.results):
            return None
        return self.results[idx]

    def _snapshot_state(self) -> AppState:
        """Build an ephemeral AppState the services layer can consume."""
        return AppState(
            backend=self.backend,
            language=self.language,
            merge_mode=self.merge_mode,
            run_policy=self.run_policy,
            query=self.query,
            queue=list(self.queue),
            cursor_index=self.cursor_index,
            history=list(self.history),
            engine_health=dict(self.engine_health),
            languages=dict(self.languages),
            results=list(self.results),
            scores=dict(self.scores),
            last_error=self.last_error,
        )

    # ---- Watch hooks: re-render widgets when reactives change ------------
    def watch_backend(self, _: Backend) -> None:
        self._refresh_topbar_status()

    def watch_language(self, _: str) -> None:
        self._refresh_topbar_status()

    def watch_engine_health(self, _: dict) -> None:
        self._refresh_topbar_status()

    def watch_merge_mode(self, _: bool) -> None:
        self._refresh_results()
        self._refresh_status()

    def watch_results(self, _: list) -> None:
        self._refresh_results()
        self._refresh_querybar()
        self._refresh_detail()
        self._refresh_status()

    def watch_cursor_index(self, _: int) -> None:
        self._refresh_detail()

    def watch_last_error(self, _: Optional[str]) -> None:
        self._refresh_status()

    def watch_searching(self, _: bool) -> None:
        self._refresh_status()

    def watch_run_policy(self, _: RunPolicy) -> None:
        self._refresh_status()

    # ---- Widget refresh helpers ------------------------------------------
    def _refresh_all_widgets(self) -> None:
        for name in (
            "_refresh_topbar_status",
            "_refresh_querybar",
            "_refresh_results",
            "_refresh_detail",
            "_refresh_status",
        ):
            getattr(self, name)()

    def _refresh_topbar_status(self) -> None:
        try:
            self.query_one(TopBar).refresh_from_state(self)
            self.query_one(StatusBar).refresh_from_state(self)
        except Exception as exc:  # noqa: BLE001 - pre-mount; skip
            logger.debug("refresh topbar/status skipped: %s", exc)

    def _refresh_querybar(self) -> None:
        try:
            self.query_one(QueryBar).refresh_from_state(self)
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh querybar skipped: %s", exc)

    def _refresh_results(self) -> None:
        try:
            self.query_one(ResultsTable).refresh_from_state(self)
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh results skipped: %s", exc)

    def _refresh_detail(self) -> None:
        try:
            self.query_one(DetailPane).refresh_from_state(self)
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh detail skipped: %s", exc)

    def _refresh_status(self) -> None:
        try:
            self.query_one(StatusBar).refresh_from_state(self)
        except Exception as exc:  # noqa: BLE001
            logger.debug("refresh status skipped: %s", exc)

    # ---- Search worker ----------------------------------------------------
    @work(thread=True, exclusive=True, name="search")
    def run_search(self, media_path: str) -> None:
        """Search one media file off-thread; post results back on mutation.

        ``exclusive=True`` cancels any in-flight search when a new one starts
        (e.g. user changed language/engine mid-search).
        """
        self.call_from_thread(self._begin_search, media_path)
        state = self._snapshot_state()
        try:
            results = self.search_worker.search(state, media_path)
        except Exception as exc:  # noqa: BLE001 - never crash the UI
            logger.exception("search failed")
            self.call_from_thread(self._end_search, [], {}, str(exc))
            return
        scores = {str(r.get("id")): float(r.get("_score", 0.0)) for r in results}
        self.call_from_thread(self._end_search, results, scores, state.last_error)

    def _begin_search(self, media_path: str) -> None:
        self.searching = True
        if not self.query:
            self.query = Path(media_path).stem
        # Mark the queue item as searching for the StatusBar.
        for item in self.queue:
            if item.path == media_path:
                item.status = "searching"

    def _end_search(
        self,
        results: List[dict],
        scores: Dict[str, float],
        error: Optional[str],
    ) -> None:
        self.searching = False
        self.results = results
        self.scores = scores
        self.cursor_index = 0
        self.last_error = error
        # Mark the first queue item as awaiting a pick.
        for item in self.queue:
            if item.status == "searching":
                item.status = "awaiting_pick" if results else "queued"

    # ---- Keybindings ------------------------------------------------------
    def action_cursor_down(self) -> None:
        if self.focused and self.focused.__class__.__name__ == "Input":
            return  # let Input handle its own keys
        if self.results:
            self.cursor_index = min(self.cursor_index + 1, len(self.results) - 1)

    def action_cursor_up(self) -> None:
        if self.focused and self.focused.__class__.__name__ == "Input":
            return
        if self.cursor_index > 0:
            self.cursor_index -= 1

    def action_focus_query(self) -> None:
        try:
            self.query_one("#query-input").focus()
        except Exception:  # noqa: BLE001
            pass

    def action_open_language(self) -> None:
        """Push the language popover. Applies with scope-confirm if a batch is in flight."""
        remaining = [it.path for it in self.queue if not it.is_done()]
        needs_confirm = len(remaining) > 1
        popover = LanguagePopover(
            languages=self.languages,
            current=self.language,
            needs_scope_confirm=needs_confirm,
            remaining_files=remaining,
        )
        self.push_screen(popover, self._on_language_chosen)

    def _on_language_chosen(self, result) -> None:
        """Apply the chosen (code, scope) from the language popover."""
        if not result:
            return
        code, scope = result
        # Persist any newly-added code into the session language map.
        if code not in self.languages:
            self.languages[code] = native_name(code)
        self.language = code
        self._rebuild_keymap()

        # If a batch is in flight and scope is "all", update every remaining
        # queue item so they fetch in the new language.
        if scope == "all":
            for item in self.queue:
                if not item.is_done():
                    item.status = "queued"

        # Re-search the current file in the new language.
        self._research_current()

    def action_open_engine(self) -> None:
        """Push the engine switcher."""
        screen = EngineSwitcher(
            current=self.backend,
            health=self.engine_health,
            merge_mode=self.merge_mode,
        )
        self.push_screen(screen, self._on_engine_chosen)

    def _on_engine_chosen(self, result) -> None:
        if result is None:
            # Even on cancel, pick up any merge-mode toggle the user did in-screen.
            return
        backend: Backend = result
        if backend == self.backend:
            return
        self.backend = backend
        self._research_current()

    def action_open_palette(self) -> None:
        """Push the ⌘K command palette."""
        self._rebuild_keymap()
        self.push_screen(Palette(self.keymap), self._on_palette_run)

    def _on_palette_run(self, action) -> None:
        from tui.keymap import Action

        if not isinstance(action, Action) or action.run is None:
            return
        try:
            action.run(self)
        except Exception as exc:  # noqa: BLE001
            logger.exception("palette action %s failed", action.id)
            self._notify(f"{action.label} failed: {exc}", severity="error")

    def action_open_config(self) -> None:
        """Push the Config settings rail."""
        screen = ConfigTab(
            policy=self.run_policy,
            ads_file_path=self.run_policy.ads_file_path,
        )
        self.push_screen(screen, self._on_config_result)

    def _on_config_result(self, result) -> None:
        """Apply the edited RunPolicy, then prompt a one-line diff before save."""
        if not result or result[0] != "save":
            return  # cancel
        new_policy: RunPolicy = result[1]
        if new_policy is None:
            return
        # Compute the diff from the CURRENT (pre-assignment) policy first, so
        # the comparison actually sees the change.
        diff = self._config_diff_summary(new_policy)

        # Update the live reactive so the StatusBar mirrors the new settings.
        self.run_policy = new_policy

        if not diff:
            self._notify("config.yaml: no changes")
            return
        # Confirm modal: writes on yes, cancels on no.
        self.push_screen(
            _ConfirmScreen(f"Write to config.yaml?\n[dim]{diff}[/]"),
            lambda confirmed: self._on_save_confirm(confirmed, new_policy),
        )

    def _config_diff_summary(self, new_policy: RunPolicy) -> str:
        """One-line summary of what would change, without touching disk.

        Compares against ``self.run_policy`` (the value BEFORE assignment in the
        caller), so call this before mutating the reactive.
        """
        if not self.config_path:
            return "(no config path — changes apply this session only)"
        try:
            changes: List[str] = []
            old = self.run_policy
            if old.force_utf8 != new_policy.force_utf8:
                changes.append("opt_force_utf8")
            if old.audio_sync != new_policy.audio_sync:
                changes.append("sync_audio_to_subs")
            if old.auto_select != new_policy.auto_select:
                changes.append("auto_selection")
            if (old.ads_file_path or "") != (new_policy.ads_file_path or ""):
                changes.append("ads.file_path")
            if not changes:
                return ""
            return "config.yaml: " + ", ".join(changes)
        except Exception as exc:  # noqa: BLE001
            return f"(diff unavailable: {exc})"

    def _on_save_confirm(self, confirmed, new_policy: RunPolicy) -> None:
        if not confirmed:
            self._notify("save cancelled")
            return
        if not self.config_path:
            self._notify("changes apply this session only (no config path)")
            return
        try:
            from tui.services import ConfigIO

            snap = self._snapshot_state()
            snap.run_policy = new_policy
            summary = ConfigIO.save(snap, self.config_path)
            self._notify(summary)
        except Exception as exc:  # noqa: BLE001
            logger.exception("config save failed")
            self._notify(f"save failed: {exc}", severity="error")

    def action_toggle_merge(self) -> None:
        self.merge_mode = not self.merge_mode

    def action_reprobe(self) -> None:
        self.action_reprobe_engines()

    def action_reprobe_engines(self) -> None:
        """Re-probe every engine's health off-thread."""
        self.run_health_probe(force=True)

    # ---- Policy toggles (used by the palette + future Config tab) ---------
    def _toggle_policy(self, field: str) -> None:
        new_policy = copy.copy(self.run_policy)
        setattr(new_policy, field, not getattr(new_policy, field))
        new_policy.validate()
        self.run_policy = new_policy
        self._refresh_status()

    def _cycle_sync_policy(self) -> None:
        idx = SYNC_POLICY_VALUES.index(self.run_policy.audio_sync)
        new_policy = copy.copy(self.run_policy)
        new_policy.audio_sync = SYNC_POLICY_VALUES[(idx + 1) % len(SYNC_POLICY_VALUES)]
        self.run_policy = new_policy
        self._refresh_status()

    def _cycle_hi_policy(self) -> None:
        idx = HI_POLICY_VALUES.index(self.run_policy.hearing_impaired)
        new_policy = copy.copy(self.run_policy)
        new_policy.hearing_impaired = HI_POLICY_VALUES[(idx + 1) % len(HI_POLICY_VALUES)]
        self.run_policy = new_policy
        self._refresh_status()

    # ---- Keymap (dynamic actions) ----------------------------------------
    def _rebuild_keymap(self) -> None:
        """Rebuild the palette registry, adding per-language + per-engine actions."""
        from tui.keymap import Action, default_actions

        actions = default_actions()
        # One action per configured language.
        for code, name in self.languages.items():
            actions.append(
                Action(
                    id=f"lang.set.{code}",
                    label=f"Set language: {name} ({code})",
                    category="setting",
                    run=lambda app, c=code: (
                        setattr(app, "language", c),
                        app._research_current(),
                    ),
                )
            )
        # One action per concrete engine.
        from tui.state import CONCRETE_BACKENDS

        for be in CONCRETE_BACKENDS:
            actions.append(
                Action(
                    id=f"engine.set.{be.value}",
                    label=f"Use engine: {be.label}",
                    category="engine",
                    run=lambda app, b=be: (
                        setattr(app, "backend", b),
                        app._research_current(),
                    ),
                )
            )
        self.keymap.actions = actions

    def _research_current(self) -> None:
        """Re-run the search for the current (first non-done) media file."""
        current = next((it.path for it in self.queue if not it.is_done()), None)
        if current is None and self.media_paths:
            current = self.media_paths[0]
        if current:
            self.run_search(current)

    def action_download_cursor(self) -> None:
        row = self.current_result()
        if row is None:
            self._notify("No row to download.", severity="warning")
            return
        if not self.media_paths:
            self._notify("No media file to download for.", severity="warning")
            return
        media_path = self.media_paths[0]
        # Mark the queue item as downloading.
        for item in self.queue:
            if item.path == media_path:
                item.status = "downloading"
                item.chosen = row
        self.run_download(media_path, row)

    @work(thread=True, exclusive=False, name="download")
    def run_download(self, media_path: str, chosen: dict) -> None:
        """Download the chosen subtitle off-thread; mount the toast on success.

        Failures are surfaced via a notification + an amber/red toast so the UI
        never crashes (spec §12).
        """
        state = self._snapshot_state()
        try:
            result = self.download_worker.download(state, media_path, chosen)
        except Exception as exc:  # noqa: BLE001
            logger.exception("download failed")
            self.call_from_thread(
                self._notify, f"Download failed: {exc}", "error"
            )
            self._mark_queue(media_path, "failed", str(exc))
            return

        if not result.downloaded:
            self.call_from_thread(
                self._notify,
                f"Download failed: {result.error or 'unknown error'}",
                "error",
            )
            self._mark_queue(media_path, "failed", result.error)
            return

        # Mount the post-download toast with the result + current sync policy.
        self.call_from_thread(self._show_post_download_toast, result, media_path)

    def _show_post_download_toast(self, result, media_path: str) -> None:
        toast = PostDownloadToast(
            result=result,
            audio_sync_policy=self.run_policy.audio_sync,
        )
        self.push_screen(toast, lambda choice: self._on_post_choice(result, media_path, choice))

    def _on_post_choice(self, result, media_path: str, choice) -> None:
        """Run the chosen postprocessing and record the HistoryEntry."""
        if choice is None:
            # Skipped (esc) — still record a 'done, no post' entry.
            entry = self.download_worker.postprocess(result, do_clean=False, do_sync=False)
            self.history.append(entry)
            self._mark_queue(media_path, "done")
            return

        action, pinned, auto = choice
        # If the user pinned a default, write it back to config (spec §6.4 'A').
        if pinned:
            self._pin_sync_default(action)

        entry = self.download_worker.postprocess(
            result, do_clean=action.do_clean, do_sync=action.do_sync
        )
        self.history.append(entry)
        self._mark_queue(media_path, "done")
        # Surface the outcome.
        if entry.sync_skipped:
            self._notify(f"{result.release}: sync skipped (no ffs)", severity="warning")
        elif entry.error:
            self._notify(f"{result.release}: {entry.error}", severity="warning")
        else:
            tag = "cleaned+synced" if (entry.cleaned and entry.synced) else (
                "cleaned" if entry.cleaned else ("synced" if entry.synced else "saved")
            )
            self._notify(f"{result.release}: {tag}")

    def _pin_sync_default(self, action: "PostAction") -> None:
        """Pin the chosen action as the new audio-sync default + persist to config."""
        new_policy = "always" if action.do_sync else "never"
        new_run = copy.copy(self.run_policy)
        new_run.audio_sync = new_policy
        self.run_policy = new_run
        # Persist back to config.yaml if we know the path.
        if self.config_path:
            try:
                from tui.services import ConfigIO

                ConfigIO.save(self._snapshot_state_for_config(), self.config_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("pin default save failed: %s", exc)

    def _snapshot_state_for_config(self) -> "AppState":
        return self._snapshot_state()

    def _mark_queue(self, media_path: str, status: str, error: Optional[str] = None) -> None:
        for item in self.queue:
            if item.path == media_path:
                item.status = status
                if error:
                    item.error = error
        self._refresh_status()

    def _notify(self, message: str, severity: str = "information") -> None:
        """Surface a one-line message. Uses Textual's toast when available."""
        try:
            self.notify(message, severity=severity, timeout=3)
        except Exception:  # noqa: BLE001
            logger.info("notify: %s", message)

    # ---- Health probe worker ---------------------------------------------
    @work(thread=True, exclusive=True, name="health")
    def run_health_probe(self, force: bool = False) -> None:
        try:
            health = self.health_probe.probe(force=force)
        except Exception as exc:  # noqa: BLE001
            logger.warning("health probe failed: %s", exc)
            return
        self.call_from_thread(self._apply_health, health)

    def _apply_health(self, health: Dict[str, EngineHealth]) -> None:
        # Merge into the reactive so watch_engine_health fires a refresh.
        merged = dict(self.engine_health)
        merged.update(health)
        self.engine_health = merged


class _ConfirmScreen(ModalScreen):
    """Tiny yes/no confirmation modal used by the Config save-back flow."""

    DEFAULT_CSS = """
    _ConfirmScreen {
        align: center middle;
    }
    _ConfirmScreen > Vertical {
        width: 60;
        max-width: 90%;
        background: #0f131a;
        border: solid #d9a441;
        padding: 1 2;
    }
    _ConfirmScreen #cf-msg {
        color: #d8dde6;
        padding: 0 0 1 0;
    }
    _ConfirmScreen #cf-foot {
        color: #6a7280;
    }
    """

    BINDINGS = [
        Binding("y", "yes", "Yes", show=False),
        Binding("n", "no", "No", show=False),
        Binding("escape", "no", "No", show=False),
        Binding("enter", "yes", "Yes", show=False),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        from textual.containers import Vertical
        yield Vertical(
            Static(self._message, id="cf-msg", markup=True),
            Static("[dim][b]y[/b]/↵ confirm   [b]n[/b]/esc cancel[/]", id="cf-foot", markup=True),
        )

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


def run_tui(
    config: Optional[dict] = None,
    media_paths: Optional[List[str]] = None,
    overrides: Optional[dict] = None,
    config_path: Optional[str] = None,
) -> None:
    """Launch the Textual app full-screen.

    Kept as a free function so ``download_subs.py`` can call it without
    importing the ``App`` class directly.
    """
    app = SubsApp(
        config=config,
        media_paths=media_paths,
        overrides=overrides,
        config_path=config_path,
    )
    app.run()
