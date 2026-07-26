# TUI Production UX Pass Design

**Status:** Approved direction  
**Date:** 2026-07-26  
**Reference:** `docs/tui-redesign/02-command-deck-live.html`

## 1. Goal

Turn the current Textual command deck and every execution path introduced with
it into a complete, production-quality subtitle workflow. The result must
expose the choices users already have, support both keyboard and mouse
interaction, process multi-file queues correctly, merge provider results
without corruption, dispatch downloads to the correct provider, persist every
editable setting it presents, and pass modern Python linting without deprecated
`typing` aliases.

The established `library/*` provider implementations and scoring algorithms
remain available behind new typed adapters. `tui/services.py`, `tui/app.py`,
and the widget layer are replaced or substantially rewritten wherever their
current contracts are untrustworthy. Passing tests written around the current
implementation are not treated as proof of correct provider integration.

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
- `preferred_backend: ask` cannot survive configuration loading because the TUI
  `Backend` enum has no `ASK` state. It silently becomes OpenSubtitles.
- With interaction enabled, the TUI silently takes the first merged language
  instead of presenting the engine and language choices the legacy workflow
  presents.
- Directory arguments are queued as one fake media item instead of being
  expanded into supported media files.
- The search and download workers are constructed before configuration is
  translated into a `RunPolicy`. They retain default policy objects, so the
  policy visible in the UI is not the policy used by provider clients.
- Editing a run policy does not invalidate or update cached provider clients.
- The merge implementation is sequential despite being specified as parallel.
- Merge deduplicates on raw provider IDs. The same numeric/string ID from two
  providers causes valid candidates to be discarded.
- A merged result is tagged with `_source`, but download dispatch ignores that
  source and uses the globally selected backend. A SubDL or SubSource row can
  therefore be sent to OpenSubtitles for download.
- Health state is used as a hard merge gate even though the probe can produce
  false negatives. A live configured OpenSubtitles search succeeded while the
  current probe labelled OpenSubtitles degraded.
- AUTO routing differs from the legacy provider priority and falls back to
  OpenSubtitles without attempting another provider after an empty or failed
  search.
- Provider errors are frequently converted to empty lists inside `library/*`,
  so the TUI cannot distinguish “zero matches” from “request failed.”
- Search results are untyped dictionaries containing provider-private payloads.
  A live SubDL candidate contained an API key in its download URL. Such values
  must never reach preview, clipboard, logs, history, or exported state.
- The visible query is ignored by the search service, which always derives its
  term from `Path(media_path).stem`.
- `show_ai_translated`, hearing-impaired mode, alternate-name behavior, and
  other displayed policies are inconsistent across providers or unused.
- Auto-selection is displayed and loaded but does not drive the TUI workflow.
- Search and download use separate provider client caches; OpenSubtitles may
  authenticate twice in one session.
- Post-processing runs from a UI callback and can block Textual while syncing.
- `SubtitleUtils.clean_subtitles` and `sync_subtitles` swallow exceptions, but
  the TUI marks the operation successful whenever those helpers return.
- The configured ads file path is displayed and saved but is not passed to the
  cleaner.
- Configuration writes are non-atomic PyYAML rewrites that drop comments,
  despite comments claiming preservation support.
- Installing the unpinned requirements currently produces an incompatible
  Requests/chardet warning.

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

`SubsApp` owns one coherent typed session state:

- active view;
- active queue item;
- queue and history;
- engine mode (`ask`, concrete provider, or `auto`) and merge mode;
- selected language and per-item language overrides;
- per-engine configured languages;
- typed search candidates and selected candidate key;
- run policy;
- engine health;
- transient notice or error.

Textual reactives may mirror fields needed for rendering, but state mutation is
centralized in named application methods. Widgets emit intent and do not call
backend libraries.

### 4.2 Service boundary

The monolithic worker classes in `tui/services.py` are replaced with four
explicit boundaries:

1. **Provider adapters** — one adapter each for OpenSubtitles, SubDL, and
   SubSource. They convert provider responses into typed candidates, retain
   secret download payloads privately, expose truthful success/error results,
   and dispatch downloads through the provider that created the candidate.
2. **Search coordinator** — plans concrete-provider, AUTO, and merge searches;
   applies shared filters and ranking; combines warnings and candidates.
3. **Job coordinator** — owns queue progression, download jobs, post-processing
   jobs, retry, skip, and history creation.
4. **Configuration repository** — validates, diffs, and atomically saves the
   complete supported configuration without exposing secrets.

Widgets and application state never receive raw provider response objects,
authenticated URLs, credentials, or backend client instances.

The adapters may call existing public provider methods or introduce narrow
public methods in `library/*` when the only available implementation is a
private `_gather_candidates` method. Provider algorithms are not duplicated
inside the TUI.

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

### 4.4 Typed integration objects

The service boundary uses explicit data objects:

- `SearchRequest`: media path, effective query, language, policy;
- `Candidate`: stable key, provider, provider ID, normalized display metadata,
  shared score, and an opaque private download reference;
- `ProviderSearchResult`: candidates plus provider warning/error state;
- `DownloadResult`: provider, exact saved path, overwrite decision, and error;
- `PostProcessResult`: clean and sync outcomes represented independently;
- `HealthResult`: configured, reachable, authenticated, latency, and reason.

A candidate key is namespaced as `<provider>:<provider-id>`. Candidates without
a trustworthy provider ID receive a deterministic provider-scoped fingerprint
instead of being silently discarded.

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

The selected table row is keyed by `Candidate.key`. Keyboard movement,
DataTable cursor movement, and mouse row selection all update the same selected
key, so downloads cannot target a different row from the one highlighted.

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

`ask` remains a real startup state. When `preferred_backend: ask` is configured
and no CLI override is supplied, the engine picker opens before the first
search. It is never silently coerced to OpenSubtitles.

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

When interactive startup is enabled and no `--lang` override is supplied, the
language picker opens after engine selection. `skip_interactive_menu: true`
uses the configured provider and its first configured language, matching the
legacy escape-hatch behavior.

## 7. Cross-Provider Search and Merge

### 7.1 Concrete-provider search

A concrete provider receives one `SearchRequest` and returns either candidates,
a truthful zero-result response, or an error. Shared AI/HI filters and ranking
run after normalization so their semantics do not vary by provider.

### 7.2 AUTO

AUTO starts with the legacy provider priority—SubSource, OpenSubtitles, then
SubDL—adjusted only to skip unconfigured providers and prefer a provider with
positive recent health. Health is advisory rather than a hard gate. AUTO tries
providers until one returns usable candidates; an empty or failed first
provider does not force an empty screen when another configured provider can
answer.

The UI reports which providers were attempted and why AUTO selected the final
one.

### 7.3 Merge

Merge launches one isolated provider search per configured provider
concurrently, with a maximum of three provider jobs. One provider failure does
not cancel successful providers. The result surface reports partial failure
instead of presenting an incomplete union as complete.

Deduplication is provider-scoped:

- repeated search passes from one provider collapse on namespaced candidate
  key;
- candidates from different providers remain independently downloadable even
  if their raw IDs or release names match.

Results share one normalized ranking algorithm and deterministic tie-breakers.
Provider download counts are displayed but are not treated as directly
comparable across services.

Selecting a merged candidate always dispatches through
`candidate.provider`. The globally selected engine is not consulted during
download dispatch.

### 7.4 Secret handling

Authenticated provider URLs and opaque download references are adapter-private.
Copy URL copies a public subtitle page only when a provider supplies one
without credentials. Otherwise the action is disabled with an explanation.
Logs and errors redact known credential values and sensitive query parameters.

## 8. Queue and Batch Processing

Every `QueueItem` stores the effective engine and language used for that item.
The app derives the active item from the first non-terminal queue entry, never
from `media_paths[0]`.

Before the app mounts, path expansion:

- accepts individual supported media files;
- expands a supplied directory using the same non-recursive semantics as the
  legacy workflow;
- filters unsupported paths;
- removes duplicate resolved paths while preserving deterministic order;
- reports empty directories and unsupported inputs instead of searching their
  names as media titles.

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

Auto-selection uses the same ranked candidates shown in Search. When enabled,
the top candidate is chosen and the decision is recorded in History. It does
not use a separate provider-specific selector with different ranking.

Download, clean, and sync run off the Textual event loop. Post-processing
outcomes are recorded only from helpers that return success explicitly or
raise on failure. A configured ads file path is passed to the cleaner.

## 9. Configuration

Config is a full view, not a modal. It groups:

- general behavior: preferred backend, skip interaction, auto-selection;
- post-processing: force UTF-8, clean ads, audio sync policy, ads path;
- search filters: hearing-impaired policy and AI-translated visibility;
- engine setup: configured status and language mappings for each backend.

Existing keys retain their legacy meaning. Search behaviors not supported by
the coordinated implementation are not exposed as pretend settings.
Session-only filters are labelled session-only. Any newly persisted supported
keys are documented in `config.yaml.sample` with backward-compatible defaults.

Edits update a local draft. `Ctrl+S` presents a compact field-level diff,
writes atomically after confirmation, refreshes the app's live policy, and
clears the dirty marker. Escape or switching views with unsaved edits asks
whether to discard them.

Saving a provider or policy change invalidates only the affected adapter/client
state. The visible session state and the policy used by active jobs cannot
diverge silently.

Credentials are never printed in full. Config may report missing credentials
or offer a masked presence indicator, but secret editing is outside this pass.

## 10. Command Palette and Help

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

## 11. Error Handling

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
- Partial merge failures name the failed providers while retaining successful
  results.
- Provider error and zero-result states remain distinct through every service
  boundary.
- Existing subtitle target conflicts require an explicit replace or cancel
  decision; downloads are not silently overwritten.

## 12. Code Quality

- Use built-in generics (`dict`, `list`, `tuple`) and `X | None`.
- Import callables from `collections.abc`.
- Remove phase comments, unused imports, unused values, and placeholder copy.
- Keep widgets focused on rendering and intent emission.
- Prefer small typed messages/result objects to unstructured callback tuples.
- Add a Ruff configuration that reflects the supported Python version and run
  it across the changed Python surface.
- Pin or constrain dependencies so a clean requirements installation does not
  produce the current Requests/chardet compatibility warning.
- Preserve unrelated user changes and the legacy CLI escape hatch.

## 13. Testing and Verification

Implementation follows test-first red/green/refactor cycles.

Automated coverage includes:

- lowercase and uppercase-compatible shortcuts;
- click handling for tabs and chips;
- engine and language rows rendered from real config structures;
- engine-specific and merge-mode language availability;
- merge toggle propagation;
- raw provider-ID collision across two or more engines;
- source-aware download dispatch for every provider in merged results;
- provider-private download references never appearing in display/log objects;
- successful provider search despite a failed advisory health probe;
- partial merge failure with successful results retained;
- AUTO fallback after provider error and after truthful zero results;
- configured run policy reaching adapters and cached-client invalidation;
- query submission;
- real view switching and dirty-config safeguards;
- complete configuration round-trip;
- directory expansion and unsupported-path reporting;
- active-item selection and multi-file queue advancement;
- download failure, retry, skip, and batch completion;
- truthful clean/sync failure reporting and ads-path propagation;
- preview, copy URL, help, and safe quit;
- palette/action-registry consistency;
- compact and wide layout composition.

Final verification runs:

- the full project test suite;
- Ruff on the changed Python surface;
- formatting checks;
- `git diff --check`;
- adapter contract tests using captured, sanitized provider response fixtures;
- a live opt-in smoke check for each configured provider that reports counts and
  statuses without downloading subtitles or printing credentials;
- Textual screenshot capture for main view and every overlay at wide and
  compact terminal sizes;
- a manual no-network smoke run using deterministic fake services.

## 14. Non-Goals

- Rewriting subtitle matching, archive selection, or synchronization algorithms
  that predate the TUI, except where a narrow public/result contract is needed
  to prevent the TUI from misreporting their outcome.
- Adding a new subtitle provider.
- Replacing the legacy `--no-tui` workflow.
- Editing or displaying credentials in full.
- Pixel-perfect bidirectional terminal shaping beyond correct UTF-8 content.
- A GUI or web application.
