# TUI Redesign — Command Deck

> **Status:** design (awaiting user review)
> **Date:** 2026-07-26
> **Scope:** Replace the numbered-prompt CLI in `download_subs.py` with a full-screen, mutable, keyboard-first Textual TUI — without touching the backend logic in `library/`.
> **Visual reference:** `docs/tui-redesign/02-command-deck-live.html` (6 interactive states)

---

## 1. Why

The current interface is a sequence of `rich.print()` tables and `console.input()` number prompts (`_ask_backend`, `_show_language_menu`, `manual_select_subtitle`). It is functional but not a TUI: no full-screen layout, no keyboard navigation, no live mutation, no progress surface. Every setting change requires editing `config.yaml` and restarting.

The redesign turns the tool into a **cockpit**: one screen, dense, keyboard-driven, where the chrome itself is the control surface. Language, engine, and post-download actions all change **while the run is in flight**, without quitting.

The backend (`library/OpenSubtitles.py`, `library/SubDL.py`, `library/SubSource.py`, `library/subtitle_utils.py`, `library/clean_subtitles.py`, `library/sync_subtitles.py`) stays untouched — the TUI is a new presentation + orchestration layer over the existing search/score/download/clean/sync functions.

---

## 2. Goals & non-goals

### Goals
- **Full-screen TUI** on Textual, dark theme, monospace, box-drawing only (maps 1:1 to mockups).
- **Live mutation**: change language, switch engine (OpenSubtitles ↔ SubDL ↔ SubSource), flip post-download policy — all mid-run.
- **Multilingual rendering**: UTF-8 end-to-end. Arabic / Chinese / etc. movie and release names render readably, RTL right-aligned where it matters. (Display-correct, not pixel-perfect RTL shaping — see §11.)
- **Keyboard-first**: every action has a one-key binding; a ⌘K palette is the discoverable fallback.
- **Surfaces every existing feature**: backend selection, language selection, hash-match, score-sorted results, clean, sync, UTF-8, hearing-impaired filter, auto-select, ads-file path — none are lost.
- **Persists config changes back to `config.yaml`** so the TUI is an editor, not a parallel source of truth.

### Non-goals
- No new subtitle backend, no change to scoring/cleaning/sync logic.
- No pixel-perfect Arabic letter-joining / bidi cursor movement (would push toward a GUI; out of scope).
- No remote/cloud features, no accounts, no telemetry.
- No removal of the existing non-TUI entry path (a `--no-tui` flag keeps the old behavior usable; see §8).

---

## 3. Framework & dependencies

**Framework:** [Textual](https://textual.textualize.io/) — built by the Rich author, CSS-style theming, async, mouse + keyboard, real widgets (`DataTable`, `TabbedContent`, `Input`, `ProgressBar`, `Toast`, custom widgets). This is the deliberate "matured TUI world" choice.

**New dependency:** `textual` (added to `requirements.txt`). Textual already depends on `rich`, which is already a dependency, so the install footprint is one new package.

**No new backend dependencies.** All search/score/download/clean/sync calls go through the existing `library/*` modules unchanged.

---

## 4. Architecture

```
download_subs.py  (entry point — parses argv, launches App)
       │
       ├── ArgvParser           → media paths + initial overrides (--lang, --backend, --no-tui)
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  SubsApp (Textual App)                                  │
│                                                          │
│  ┌─ AppState ──────────────────────────────────────┐    │
│  │  backend, language, run_policy, query, queue,   │    │
│  │  results, cursor, history, engine_health        │    │
│  │  (single reactive source of truth)              │    │
│  └──────────────────────────────────────────────────┘    │
│                          │                                │
│  ┌─ Widgets ─────────────┴──────────────────────────┐   │
│  │  TopBar        tabs + engine/lang/⌘K chips       │   │
│  │  QueryBar      search input + live status        │   │
│  │  ResultsTable  DataTable of candidates           │   │
│  │  DetailPane    preview of cursor row             │   │
│  │  StatusBar     mirrored settings + key hints     │   │
│  │  overlays: Palette, LangPopover, EngineSwitcher, │   │
│  │            PostDownloadToast, ConfigTab          │   │
│  └───────────────────────────────────────────────────┘   │
│                          │                                │
│  ┌─ Services (async workers) ──────────────────────┐    │
│  │  SearchWorker      calls backend.search() off-   │    │
│  │                    thread, posts results back    │    │
│  │  DownloadWorker    save_subtitle + clean + sync  │    │
│  │  HealthProbe       _check_api_availability,      │    │
│  │                    cached + latencies             │    │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
              library/OpenSubtitles.py
              library/SubDL.py
              library/SubSource.py
              library/subtitle_utils.py   (unchanged)
```

**Key boundary:** `library/*` is never imported by widgets directly. Widgets talk to `AppState`; `Services` are the only layer that calls `library/*`. This keeps the existing code testable and unchanged, and makes the TUI the single new surface.

---

## 5. AppState — the single source of truth

A reactive dataclass (Textual `reactive`/`var`) holding every setting the run depends on. Mutating a field triggers UI re-render automatically.

```python
@dataclass
class RunPolicy:
    force_utf8: bool
    clean_ads: bool
    audio_sync: Literal["always", "never", "ask"]
    hearing_impaired: Literal["include", "exclude", "only"]
    auto_select: bool
    show_ai_translated: bool
    ads_file_path: str | None

@dataclass
class EngineHealth:
    name: str
    online: bool
    latency_ms: int | None
    degraded: bool

@dataclass
class QueueItem:
    path: str
    name: str                # display name (may be Arabic/CJK)
    status: Literal["queued","searching","awaiting_pick","downloading","post","done","failed","skipped"]
    candidates: list[dict]
    chosen: dict | None
    error: str | None
    progress: float          # 0..1

class AppState:
    backend: SubtitleBackend             # OPENSUBTITLES | SUBDL | SUBSOURCE | AUTO
    language: str                        # ISO code, e.g. "en", "ar", "zh"
    merge_mode: bool                     # fan-out to all engines
    run_policy: RunPolicy
    query: str
    queue: list[QueueItem]
    cursor_index: int                    # in results table
    history: list[HistoryEntry]
    engine_health: dict[str, EngineHealth]
```

**Initial values** come from `config.yaml` via the existing config-read path (reusing `SubtitleDownloader._read_config_file`). **Edits in the TUI** mutate `AppState` live; `⌘S` in Config writes back to `config.yaml`.

---

## 6. Screens & widgets

All states are shown in `docs/tui-redesign/02-command-deck-live.html`. Each § below maps to a section of that mockup.

### 6.1 Main screen (§01)
Layout: `TopBar` on top, `QueryBar`, then a horizontal split (`ResultsTable` 1.25fr | `DetailPane` 1fr), then `StatusBar`.

- **TopBar**: brand `▸ subs.` · `TabbedContent` (Search / Queue / History / Config) · live chips: `engine` (click/`B`), `lang` (click/`L`), `⌘K`, online badge.
- **QueryBar**: search `Input` with the filename prefilled; right-side shows result count + `hash match found` badge when applicable.
- **ResultsTable**: `DataTable` with columns `# | Release | L | Flags | D/L | Match`. Sorted by `score_subtitle` desc. Cursor row highlighted with accent bar. `Flags` shows `⤓hash`, quality (`1080p BD`), `⚙AI` (machine-translated).
- **DetailPane**: rich preview of cursor row — title, movie name, uploader, source, hash-match, machine-tr. + action buttons (`Download ↵`, `Preview p`, `Copy URL y`).
- **StatusBar**: live mirror of every setting (`engine OpenSubtitles │ lang EN │ utf-8 ✓ │ clean ✓ │ sync ask │ HI off`) + key hints.

### 6.2 Language popover (§02) — `L` or click lang chip
- Vertical list of configured languages, **rendered in native script** (`العربية`, `中文`, `日本語`, `Français`…) with their ISO code and a `PRIMARY` tag on the current one.
- `/` filters, `↑↓` navigates, `↵` selects, `esc` cancels.
- **Scope rule** (the key QoL/safety decision): if `queue` has >1 non-done item, selecting a language opens a scope picker — `a` apply to all remaining, `c` current file only, `esc` cancel. For a single-file run, applies instantly with no prompt. *Rationale: prevents the silent-wrong-file class of bug fixed in commit `8bab15e`.*
- `+ Add language by code…` lets you type an ISO code not in config; adds to `AppState` for the current session and writes to `config.yaml` on the next `⌘S` (so it survives restart). Native name comes from the `LANG_NATIVE_NAMES` map if present, else the code itself.

### 6.3 Engine switcher (§03) — `B` or click engine chip
- List of OpenSubtitles / SubDL / SubSource / Auto, each with description + **health badge + latency** (reuses `SubtitleDownloader._check_api_availability` against the same endpoints — `api.opensubtitles.com/.../login`, `api.subdl.com/api/v2/me`, `api.subsource.net/...`).
- `r` re-probes now. `m` toggles **merge mode**: next query fans out to all online engines in parallel via `SearchWorker`, results are deduped by id and re-scored; ResultsTable gains a `Source` column. Off by default.

### 6.4 Post-download toast (§04)
- Slides in when a download completes: `✓ <file>.srt → /path/` + four actions: `Clean + Sync ↵` / `Clean c` / `Sync s` / `Done d`.
- **5-second auto-pick** using `run_policy.audio_sync` default: `always` → `Clean + Sync`; `never` → `Clean`; `ask` → **no auto-pick, waits for a keypress** (the toast stays open). The auto-pick only short-circuits when the policy is already decided; `ask` genuinely asks. Auto-pick is logged to History with the action taken.
- `A` pins the chosen action as the new default (writes `sync_audio_to_subs` to config).
- Non-blocking: in a bulk run, the next file's search starts immediately; the toast times out and the action runs in `DownloadWorker` without stealing focus.
- Sync failure (no `ffs`/ffmpeg) → toast turns amber, offers `retry without sync`.

### 6.5 Command palette (§05) — `⌘K`
- Fuzzy-searchable list of **every action** in the app (target ~42 indexed: all keybindings + all config toggles + all backend/language options). Built once at startup from a registry.
- `↑↓` navigate, `↵` run, `⌘↵` run + keep open, `esc` close.
- Indexed categories: `action` / `setting` / `batch` / `engine`.
- This is the discoverability escape hatch — keeps the app usable as features grow.

### 6.6 Config tab (§06)
- All existing YAML keys as live toggles, grouped: **post-download** (`opt_force_utf8`, `clean_ads`, `sync_audio_to_subs`, hearing-impaired), **search behaviour** (`auto_selection`, hash-match-first, alt-name search, show-AI-translated), **ads file** (`cleaning_subtitles.ads.file_path` with `Browse…`).
- `⌘S` writes back to `config.yaml` with a one-line diff preview before commit. Hand-editors keep working — the file stays the source of truth.

---

## 7. Keybindings

| Key | Action | Context |
|---|---|---|
| `⌘K` | Open command palette | global |
| `/` | Focus filter / search input | Search tab |
| `j` `k` / `↑` `↓` | Move cursor in table | Search tab |
| `↵` | Download cursor row (or run palette item) | Search / palette |
| `p` | Preview subtitle (first N lines) | Search tab |
| `y` | Copy download URL | Search tab |
| `L` | Open language popover | global |
| `B` | Open engine switcher | global |
| `m` | Toggle merge mode | global |
| `r` | Re-probe engine health | global |
| `1`–`4` | Switch tabs (Search/Queue/History/Config) | global |
| `Tab` / `⇧Tab` | Cycle focus between panes | Search tab |
| `⌘S` | Save config to `config.yaml` | Config tab |
| `?` | Help (full keymap overlay) | global |
| `q` | Quit (with confirm if a run is in flight) | global |

Post-download toast keys (`↵` `c` `s` `d` `A` `esc`) are local to the toast.

---

## 8. Entry point & backward compatibility

`download_subs.py` becomes a thin launcher:

```python
def main():
    config = read_config(...)
    args = parse_args(sys.argv[1:])   # paths + --lang, --backend, --no-tui, --auto
    if args.no_tui or config.get("general", {}).get("no_tui"):
        run_legacy_cli(config, args)  # the current numbered-prompt flow, preserved
    else:
        app = SubsApp(config=config, media_paths=args.paths, overrides=args)
        app.run()
```

- **`--no-tui`** flag + `general.no_tui` config key preserve the old behavior for scripts, `Send To` batch files (see Readme), and headless use. No existing user breaks.
- CLI overrides (`--lang eng`, `--backend subdl`) seed `AppState` so the TUI opens pre-configured; the user can still mutate live.
- The legacy `SubtitleDownloader` class and its numbered menus are **kept** (not deleted) and used by `run_legacy_cli`. This honors the brainstorming principle: don't bulldoze working code; add the new surface alongside.

---

## 9. File plan

| File | Change | Why |
|---|---|---|
| `tui/__init__.py` | **new** | package marker |
| `tui/app.py` | **new** | `SubsApp`, mount widgets, bind keys, orchestrate |
| `tui/state.py` | **new** | `AppState`, `RunPolicy`, `EngineHealth`, `QueueItem`, `HistoryEntry` dataclasses |
| `tui/services.py` | **new** | `SearchWorker`, `DownloadWorker`, `HealthProbe` — the only callers of `library/*` |
| `tui/widgets/topbar.py` | **new** | `TopBar` (tabs + live chips) |
| `tui/widgets/results.py` | **new** | `ResultsTable` (DataTable + score bars) |
| `tui/widgets/detail.py` | **new** | `DetailPane` |
| `tui/widgets/overlays.py` | **new** | `Palette`, `LangPopover`, `EngineSwitcher`, `PostDownloadToast` |
| `tui/widgets/config_tab.py` | **new** | Config toggles + save-back |
| `tui/style.tcss` | **new** | Textual CSS (dark theme, phosphor-green + amber, from mockup tokens) |
| `tui/keymap.py` | **new** | keybinding registry + palette action index |
| `download_subs.py` | **refactor** | extract `SubtitleDownloader` (unchanged) into a legacy path; `main()` becomes the thin launcher in §8. Old numbered menus preserved behind `--no-tui`. |
| `requirements.txt` | **edit** | add `textual` |
| `config.yaml.sample` | **edit** | add `general.no_tui: false` key |
| `library/*` | **unchanged** | explicit non-goal |
| `Readme.md` | **edit** | document TUI mode + `--no-tui` |

Estimated ~1,200–1,600 lines of new code in `tui/`, none of it touching backend logic.

---

## 10. Mapping to existing code

| Mockup feature | Existing function it calls |
|---|---|
| ResultsTable rows | `OpenSubtitles.search` / `SubDL.search` / `SubSource.search` → standardized via `SubtitleUtils.standardize_subtitle_object` |
| Match score column | `SubtitleUtils.score_subtitle(release, video_name, hash_match)` → `normalize_score` |
| `⤓hash` flag | `attributes.moviehash_match` |
| `⚙AI` flag | `attributes.ai_translated` / `machine_translated` |
| Engine health badge | `SubtitleDownloader._check_api_availability` (same URLs) |
| Download | `backend.get_download_link` (OS) / backend download path → `save_subtitle` |
| Clean | `SubtitleUtils.clean_subtitles` → `clean_subtitles.clean_ads` |
| Sync | `SubtitleUtils.sync_subtitles` → `sync_subtitles.sync_subs_audio` |
| Language list | `config[backend].languages` dict |
| Config toggles | direct map to `general.*` and `cleaning_subtitles.*` YAML keys |

---

## 11. Multilingual handling

- **Encoding**: all strings UTF-8; subtitle files already forced via `opt_force_utf8`. The TUI sets `App` encoding to UTF-8 and relies on the terminal's font (Windows Terminal / WezTerm / Kitty / iTerm2 all ship CJK + Arabic glyphs).
- **Display**: Arabic movie/release names render right-aligned in the Queue and Results; CJK renders inline. The `name.ar` / `name.zh` styling in the mockup maps to a `Textualize` helper that sets `direction: rtl` on the cell — a display hint, not full bidi reordering.
- **Scope of correctness**: "display correctly, no mojibake." Pixel-perfect Arabic letter-joining and bidi cursor movement are explicitly out of scope (§2). If a user hits a terminal that can't shape Arabic, the fallback is the same UTF-8 bytes — readable but not joined.
- **Language picker** shows native names (`العربية`, `中文`) sourced from a small built-in `LANG_NATIVE_NAMES` map keyed by ISO code, falling back to the configured English name.

---

## 12. Error handling

| Failure | TUI behavior |
|---|---|
| All engines offline | `EngineSwitcher` shows all red; status bar shows `no engine available`; palette/search disabled with a message |
| One engine degraded | Its row in `EngineSwitcher` shows `degraded`; AUTO routes around it (existing logic) |
| Search returns 0 results | Empty state in ResultsTable: "No subtitles for `<name>` — try `/` to re-query, `L` to change language, `B` to switch engine" |
| Download fails (network) | Toast turns red, offers `retry`; file stays `failed` in Queue |
| Sync fails (no ffs/ffmpeg) | Toast turns amber, offers `retry without sync`; file marked done with `sync: skipped` |
| Config file missing/invalid YAML | Existing `_read_config_file` error path; TUI shows a modal with the error and offers `open config.yaml` / `restore sample` |
| Quit during in-flight run | Confirm modal: "2 files still queued — quit anyway?" |

All backend exceptions are caught in `Services` and converted to `AppState` status/error fields; the UI never crashes on a backend failure.

---

## 13. Testing

- **Backend unchanged** → existing `test_subtitle_utils.py` (and others) keep passing unmodified.
- **New unit tests** (`tui/tests/`):
  - `state.py`: reactive transitions (lang change mid-run updates queue scope correctly; engine switch resets health).
  - `services.py`: mock `library/*` calls, assert `SearchWorker` posts correct results, `DownloadWorker` runs clean/sync per policy, `HealthProbe` caches.
  - `keymap.py`: every indexed action resolves to a callable.
- **TUI smoke test**: Textual's `App.run_test()` async harness — drive the palette, switch engine, change language, assert widget states. No real network (services mocked).
- **Manual**: screenshot parity check against the HTML mockups.

---

## 14. Open questions for review

These are the spots where I picked a default — flag any you'd reverse:

1. **5-second auto-pick** on the post-download toast (so bulk runs don't block). OK, or should it always wait for a keypress?
2. **Merge mode** (`m` — fan out to all 3 engines, dedupe, re-score). Default **off**. OK?
3. **`--no-tui` escape hatch** preserves the old numbered CLI. Keep it, or fully retire the old flow?
4. **Scope-confirm** on language change only fires when a batch is in flight (>1 non-done file). Single-file changes are instant. OK?
5. **Language native names** from a built-in map (not auto-detected). OK, or pull from a library?

---

## 15. Out of scope (explicit)

- Pixel-perfect Arabic bidi/letter-joining.
- New subtitle backends.
- Changes to scoring, cleaning, or sync algorithms.
- Remote/cloud features, accounts, telemetry.
- GUI / web version (the abandoned `gui_test_pyqt.py` path stays abandoned).
