# Implementation Plan — TUI Command Deck Redesign

> **Spec:** `docs/superpowers/specs/2026-07-26-tui-command-deck-redesign.md`
> **Mockups:** `docs/tui-redesign/02-command-deck-live.html`
> **Hard rule:** `library/*` is never modified. All new code lives in `tui/` + a thin refactor of `download_subs.py`.

Each phase ends with something runnable/testable. Do not start a phase until the previous one passes its check.

---

## Phase 0 — Scaffold + Textual wired behind a flag

**Goal:** Textual installs; a minimal `SubsApp` boots full-screen behind `--tui`; nothing else changes.

**Files:**
- `requirements.txt` — add `textual`
- `tui/__init__.py` — new, package marker
- `tui/app.py` — new, minimal `SubsApp(App)` that mounts a single "subs · command deck" label; reads nothing yet
- `download_subs.py` — refactor: extract current `main()` body into `run_legacy(config, media_paths)`; new `main()` parses `--tui`/`--no-tui`/`--lang`/`--backend` and dispatches. Old numbered-menu path is the default (TUI is opt-in this phase so we never break the existing tool).
- `config.yaml.sample` — add `general.no_tui: false` (commented: TUI on by default after Phase 6)

**Check:**
- `uv pip install -r requirements.txt` succeeds.
- `python download_subs.py movie.mkv --no-tui` runs the old flow unchanged.
- `python download_subs.py movie.mkv --tui` opens the Textual app full-screen, shows the label, `q` quits.

---

## Phase 1 — AppState + Services (no UI)

**Goal:** The single source of truth + the only layer that calls `library/*`, fully unit-tested, no widgets.

**Files:**
- `tui/state.py` — `RunPolicy`, `EngineHealth`, `QueueItem`, `HistoryEntry`, `LANG_NATIVE_NAMES` map, `AppState` (plain dataclass for now; Textual `reactive` wiring comes in Phase 2 when it's owned by the App).
- `tui/services.py`:
  - `SearchWorker.search(state, media_path) -> list[dict]` — picks engine(s) from `state.backend`/`state.merge_mode`, calls the backend `.search()`, standardizes via `SubtitleUtils.standardize_subtitle_object`, scores via `score_subtitle`, returns sorted candidates. Reuses the OpenSubtitles `.search` + alt-name logic from `library/OpenSubtitles.process_media_file` but as a pure function.
  - `DownloadWorker.download_and_postprocess(state, media_path, chosen) -> HistoryEntry` — gets download link, saves via `save_subtitle`, then runs clean/sync per `state.run_policy` and the auto-pick rule.
  - `HealthProbe.probe(config) -> dict[str, EngineHealth]` — wraps `_check_api_availability`, caches for 60s, returns latencies.
  - `ConfigIO` — load/save `config.yaml` (reuses existing read; adds a write that preserves comments via `ruamel.yaml` if available, else `pyyaml` round-trip).
- `tui/tests/test_state.py` — language scope transitions, policy defaults.
- `tui/tests/test_services.py` — mock `library/*`, assert SearchWorker dedups + scores, DownloadWorker applies policy, HealthProbe caches.

**Check:** `pytest tui/tests/` green. No UI yet.

---

## Phase 2 — Main screen widgets wired to state

**Goal:** The §01 main screen renders real data: TopBar, QueryBar, ResultsTable, DetailPane, StatusBar. Keyboard nav works (`j`/`k`/`↵`). One-file search end-to-end.

**Files:**
- `tui/app.py` — `SubsApp` now owns `AppState` as `reactive` attributes; `compose()` mounts the widgets; `on_mount` kicks off a search for the first media path via `SearchWorker` in a worker.
- `tui/style.tcss` — Textual CSS ported from the mockup tokens (dark paper, phosphor-green accent, amber accent-2, mono font).
- `tui/widgets/topbar.py` — `TopBar(Widget)`: brand, tabs (Search/Queue/History/Config — only Search active this phase), live `engine`/`lang` chips (display only; clickable in Phase 3), online badge.
- `tui/widgets/results_table.py` — `ResultsTable(DataTable)`: columns `# / Release / L / Flags / D/L / Match`; renders score bar in the Match cell; cursor row highlighted. Consumes `state.results`.
- `tui/widgets/detail_pane.py` — `DetailPane(Widget)`: renders cursor row's full attributes (movie, uploader, hash, machine-tr.) + action buttons.
- `tui/widgets/status_bar.py` — `StatusBar(Widget)`: live mirror of every setting + key hints.
- `tui/widgets/query_bar.py` — `QueryBar(Widget)`: filename prefilled, result count + hash badge.

**Check:** `python download_subs.py movie.mkv --tui` opens, searches the first backend from config, fills the table, cursor moves with `j`/`k`, DetailPane updates, `↵` triggers download (toast/worker come Phase 4 — for now just log "would download"). Multilingual names render (test with an Arabic/CJK filename).

---

## Phase 3 — Live overlays: language, engine, palette

**Goal:** §02, §03, §05. The chrome becomes mutable.

**Files:**
- `tui/widgets/overlays/lang_popover.py` — `L` or click lang chip. Lists `state.languages` in native script; `/` filter, `↑↓`/`↵`/`esc`. **Scope rule:** if `state.queue` has >1 non-done item, show scope picker (`a` all remaining / `c` current / `esc`); else instant. Mutates `state.language` → triggers re-search of current file.
- `tui/widgets/overlays/engine_switcher.py` — `B` or click engine chip. Lists OpenSubtitles/SubDL/SubSource/Auto with `HealthProbe` badges + latency. `r` re-probes, `m` toggles merge mode (adds `Source` column to ResultsTable). Mutates `state.backend`/`state.merge_mode`.
- `tui/widgets/overlays/palette.py` — `⌘K`. Fuzzy-filters a registry of all actions (built at startup from `tui/keymap.py`). `↑↓`/`↵`/`⌘↵`/`esc`.
- `tui/keymap.py` — keybinding registry + `ACTIONS` list (each: id, label, category, shortcut, callable). The palette indexes this.

**Check:** Change language mid-screen → table re-searches. Switch engine → health badges update, re-search. `⌘K` → "sync" → list filters correctly. All overlays close with `esc`.

---

## Phase 4 — Post-download toast + DownloadWorker

**Goal:** §04. Real downloads + clean/sync, with the 5s auto-pick rule.

**Files:**
- `tui/widgets/overlays/post_download_toast.py` — `Toast(Widget)`: `✓ file.srt → path/`, four actions (`Clean+Sync ↵` / `Clean c` / `Sync s` / `Done d`), `A` to pin default, countdown in footer. **Auto-pick rule:** if `run_policy.audio_sync` is `always` or `never`, auto-run default after 5s; if `ask`, wait indefinitely. Non-blocking (next file's search continues).
- `tui/services.py` — flesh out `DownloadWorker.download_and_postprocess`: get link → `save_subtitle` → clean via `clean_subtitles.clean_ads` → sync via `sync_subtitles.sync_subs_audio` (only if policy dictates). Catch sync failure (no `ffs`) → return `sync: skipped` + amber state.
- `tui/app.py` — wire `↵` on ResultsTable to: run `DownloadWorker` for the chosen sub → on completion, mount the toast → toast action runs the postprocessing → push `HistoryEntry`.

**Check:** Download a real subtitle (small test file). Toast appears, auto-picks after 5s when policy is `always`, waits when `ask`. Clean + sync run for real. Sync failure path shows amber toast.

---

## Phase 5 — Config tab with save-back

**Goal:** §06. All YAML knobs as live toggles; `⌘S` writes to `config.yaml`.

**Files:**
- `tui/widgets/config_tab.py` — toggles grouped (post-download / search behaviour / ads file), each bound to a `state.run_policy` field. `Browse…` for ads path (Textual file picker or typed input).
- `tui/services.py` — `ConfigIO.save(state, path)`: writes `state.run_policy` back to `config.yaml`, preserving other keys. `⌘S` shows a one-line diff confirmation modal before commit.
- `tui/app.py` — make Config tab active and functional.

**Check:** Flip toggles in Config → status bar updates live. `⌘S` → modal shows diff → confirm → `config.yaml` changed on disk → restart preserves changes.

---

## Phase 6 — TUI default + legacy refactor + docs

**Goal:** TUI becomes the default; legacy path is the explicit escape hatch; Readme documents both.

**Files:**
- `download_subs.py` — flip default: TUI runs unless `--no-tui` or `general.no_tui: true`. Move the old numbered-menu `SubtitleDownloader` into `tui/legacy.py` (or keep in `download_subs.py` as `run_legacy`) — must remain importable and unchanged.
- `config.yaml.sample` — uncomment/flip `no_tui: false` with a clear comment.
- `Readme.md` — new section: "TUI mode" with screenshot, keybinding table, `--no-tui` note for scripts/Send-To.

**Check:** `python download_subs.py movie.mkv` opens TUI by default. `python download_subs.py movie.mkv --no-tui` runs old flow. Existing `1_download_subs.bat` still works (verify it passes through argv). Readme accurate.

---

## Cross-cutting (every phase)
- **Type hints** on all new public functions.
- **No `print()`** in `tui/` — all output via Textual widgets.
- **Error containment:** backend exceptions caught in `services.py`, surfaced as `AppState` fields, never crash the UI.
- **UTF-8 everywhere** — `App` encoding set, file reads explicit `encoding="utf-8"`.
- **Commit per phase** with the phase number in the message.

## Estimated effort
~1,200–1,600 lines across `tui/`. Phases 0–2 are the spine (heaviest); 3–6 are feature layers on top.
