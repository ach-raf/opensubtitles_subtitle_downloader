# TUI Production UX Pass Design

**Status:** Approved direction  
**Date:** 2026-07-26  
**Reference:** `docs/tui-redesign/02-command-deck-live.html`

## 1. Goal

Turn the current Textual command deck into a complete, production-quality
subtitle workflow. The result must expose the choices users already have,
support both keyboard and mouse interaction, process multi-file queues
correctly, persist every editable setting it presents, and pass modern Python
linting without deprecated `typing` aliases.

The existing backend adapters and most of `tui/services.py` remain the
foundation. The presentation and orchestration layers are rebuilt where their
current structure prevents the approved experience.

## 2. Audit Findings

The current implementation has a tested service core but does not meet its own
UX specification:

- The visible `L` and `B` shortcuts are uppercase-only. Normal `l` and `b`
  input does nothing.
- The rendered top bar and most query/status controls are clipped by their
  layout rules.
- Engine, language, palette, and tab labels are not clickable.
- Queue and History are labels rather than usable views. Config is a modal
  presented as a tab.
- The engine switcher's merge-mode change is local to the modal and is lost.
- The query input has no submit behavior.
- Preview, copy URL, help, and in-flight quit confirmation are advertised but
  absent.
- Downloads always target the first original media path, and a completed item
  does not advance the batch reliably.
- Config displays eight policy controls but saves only four.
- A language added in the language picker is not written to configuration.
- Broad exception handling hides lifecycle and rendering faults.
- Ruff reports deprecated `typing.Dict`, `typing.List`, `typing.Tuple`, and
  `typing.Optional` usage throughout the TUI.
- Existing tests validate many methods in isolation but do not cover the
  broken visible shortcuts, clipping, tab navigation, or queue progression.

## 3. Design Principles

1. **Visible choices are actionable.** A displayed tab, chip, button, key hint,
   or setting must work.
2. **The current job is always clear.** The active media file, queue progress,
   engine, language, search state, and next action remain visible.
3. **Keyboard-first, mouse-complete.** Every primary action has a discoverable
   key path and a clickable path.
4. **No silent scope changes.** Mid-batch engine or language changes explicitly
   apply to the current item or all remaining items.
5. **No fake persistence.** Every setting shown as editable is saved and
   restored, or is clearly labelled session-only.
6. **Failures stay local.** A failed engine, search, download, clean, or sync
   operation does not crash the application or lose the rest of the queue.
7. **Compact terminals remain usable.** At narrow widths the detail pane
   collapses before controls become clipped.

## 4. Application Structure

### 4.1 State ownership

`SubsApp` owns one coherent `AppState`-compatible session:

- active view;
- active queue item;
- queue and history;
- engine and merge mode;
- selected language;
- per-engine configured languages;
- search results and selected result;
- run policy;
- engine health;
- transient notice or error.

Textual reactives may mirror fields needed for rendering, but state mutation is
centralized in named application methods. Widgets emit intent and do not call
backend libraries.

### 4.2 Service boundary

`tui/services.py` remains the only TUI module that calls `library/*`.
Production changes to it are limited to behavior needed by the UX:

- engine-aware language resolution;
- complete configuration round trips;
- policy filtering;
- deterministic queue/download results;
- accurate health summaries;
- typed result objects where raw tuples currently obscure intent.

### 4.3 Views and overlays

The main application contains four real views:

1. **Search** — query bar, result table, detail/actions pane.
2. **Queue** — every media item, status, chosen language/engine, progress, and
   retry/cancel actions.
3. **History** — completed and failed operations with subtitle path,
   post-processing outcome, and retry/open-location actions where available.
4. **Config** — grouped live settings and engine/language configuration with
   explicit dirty and saved states.

Language picker, engine picker, command palette, help, scope confirmation,
post-download decision, save confirmation, and quit confirmation remain
overlays because they temporarily interrupt the current view.

## 5. Navigation and Layout

### 5.1 Top bar

The top bar contains:

- brand and current view;
- Search, Queue, History, and Config tabs with keys `1`–`4`;
- engine chip showing engine and health;
- language chip showing native name plus code;
- command palette button.

Tabs and chips react to clicks. Active, focused, disabled, degraded, and dirty
states use distinct styling. No control relies on hover alone.

### 5.2 Search workspace

The query bar exposes the current filename/search term, result count, current
engine/language, and search status. Enter submits the edited query; Escape
restores the media-derived query.

The results table supports arrow keys and `j`/`k`, Enter to download, `p` to
preview, and `y` to copy the URL. It has explicit loading, zero-results,
offline, and failed states. Merge mode adds a Source column without rebuilding
the entire view.

At wide widths, results and detail sit side by side. At compact widths, the
detail pane is hidden and its information is available through preview.

### 5.3 Footer

The footer has two stable zones:

- current operation and queue progress;
- context-sensitive key hints.

It does not attempt to mirror every configuration value. Relevant policy
details live in Config and the post-download overlay.

## 6. Engine and Language Experience

### 6.1 Engine picker

Lowercase `b`, the engine chip, and the command palette open the picker.
It lists OpenSubtitles, SubDL, SubSource, and Auto with:

- configured/unconfigured state;
- online/degraded/offline/unchecked state;
- measured latency when meaningful;
- a concise capability description;
- the number of configured languages.

Unavailable engines remain visible with the reason they cannot be selected.
`r` re-probes. `m` toggles merge mode and returns that change to the app.

### 6.2 Language picker

Lowercase `l`, the language chip, and the command palette open the picker.
The default list is the active engine's configured language set. Each row
shows:

- native name;
- configured label;
- ISO code;
- availability across engines when merge mode is active.

Users can filter by any of those values. Adding a valid code asks which engine
configurations should receive it. Added languages persist to `config.yaml`
after confirmation.

Changing language during a batch opens a scope choice:

- current file only;
- current and all remaining files.

The chosen scope updates per-item queue settings rather than only changing a
global field.

## 7. Queue and Batch Processing

Every `QueueItem` stores the effective engine and language used for that item.
The app derives the active item from the first non-terminal queue entry, never
from `media_paths[0]`.

Normal progression is:

1. mark active item searching;
2. show candidates and await a choice, or auto-select when enabled;
3. download the selected candidate;
4. run or request post-processing;
5. append a history entry;
6. mark the item complete or failed;
7. advance to the next non-terminal item and search it.

A failure stops only that item. The Queue view offers retry and skip. Batch
completion shows a concise summary of successes, failures, cleaned files, and
synced files.

## 8. Configuration

Config is a full view, not a modal. It groups:

- general behavior: preferred backend, skip interaction, auto-selection;
- post-processing: force UTF-8, clean ads, audio sync policy, ads path;
- search filters: hearing-impaired policy and AI-translated visibility;
- engine setup: configured status and language mappings for each backend.

Search behaviors not supported by the backend implementation are not exposed
as pretend settings. Any new supported keys are documented in
`config.yaml.sample`.

Edits update a local draft. `Ctrl+S` presents a compact field-level diff,
writes atomically after confirmation, refreshes the app's live policy, and
clears the dirty marker. Escape or switching views with unsaved edits asks
whether to discard them.

Credentials are never printed in full. Config may report missing credentials
or offer a masked presence indicator, but secret editing is outside this pass.

## 9. Command Palette and Help

The palette is generated from the same action registry used by bindings and
click handlers. It indexes:

- view navigation;
- result actions;
- queue actions;
- engine and language choices;
- merge and health actions;
- every supported policy toggle;
- save, help, and quit.

Entries that cannot currently run are disabled with a reason. Help renders the
same registry grouped by context, preventing documentation drift.

## 10. Error Handling

- Invalid or missing configuration opens a readable fatal screen with the
  exact path and parser error.
- An unconfigured engine is distinguishable from an offline engine.
- Search and download exceptions become item-level failures with retry.
- Zero results suggest changing query, language, or engine.
- Sync failure records the downloaded subtitle as successful with sync
  skipped, then offers retry without discarding the file.
- Quit during active work or with unsaved configuration requires confirmation.
- Expected lifecycle races catch specific Textual query/lifecycle exceptions;
  unexpected exceptions are logged rather than silently swallowed.

## 11. Code Quality

- Use built-in generics (`dict`, `list`, `tuple`) and `X | None`.
- Import callables from `collections.abc`.
- Remove phase comments, unused imports, unused values, and placeholder copy.
- Keep widgets focused on rendering and intent emission.
- Prefer small typed messages/result objects to unstructured callback tuples.
- Add a Ruff configuration that reflects the supported Python version and run
  it across the changed Python surface.
- Preserve unrelated user changes and the legacy CLI escape hatch.

## 12. Testing and Verification

Implementation follows test-first red/green/refactor cycles.

Automated coverage includes:

- lowercase and uppercase-compatible shortcuts;
- click handling for tabs and chips;
- engine and language rows rendered from real config structures;
- engine-specific and merge-mode language availability;
- merge toggle propagation;
- query submission;
- real view switching and dirty-config safeguards;
- complete configuration round-trip;
- active-item selection and multi-file queue advancement;
- download failure, retry, skip, and batch completion;
- preview, copy URL, help, and safe quit;
- palette/action-registry consistency;
- compact and wide layout composition.

Final verification runs:

- the full project test suite;
- Ruff on the changed Python surface;
- formatting checks;
- `git diff --check`;
- Textual screenshot capture for main view and every overlay at wide and
  compact terminal sizes;
- a manual no-network smoke run using deterministic fake services.

## 13. Non-Goals

- Rewriting `library/*` subtitle algorithms.
- Adding a new subtitle provider.
- Replacing the legacy `--no-tui` workflow.
- Editing or displaying credentials in full.
- Pixel-perfect bidirectional terminal shaping beyond correct UTF-8 content.
- A GUI or web application.

