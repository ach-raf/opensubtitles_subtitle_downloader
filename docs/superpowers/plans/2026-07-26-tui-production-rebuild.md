# TUI Production Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generated TUI integration with a typed, source-aware, test-driven workflow that correctly searches, merges, downloads, post-processes, configures, and presents all three subtitle providers.

**Architecture:** Provider-specific adapters hide raw responses and secrets behind typed domain objects. A search coordinator implements concrete, AUTO, and concurrent merge behavior; a job coordinator owns queue progression and background post-processing; Textual views render and mutate one coherent session state through application actions.

**Tech Stack:** Python 3.12, Textual, dataclasses, `concurrent.futures`, Requests, PyYAML, pytest, Ruff, Black.

---

## File Structure

- Create `pyproject.toml` — Python target, Ruff, Black, and pytest configuration.
- Modify `requirements.txt` — compatible, bounded runtime dependencies.
- Create `tui/domain.py` — enums and typed request/result/session objects.
- Create `tui/media.py` — deterministic media-file and directory expansion.
- Create `tui/providers/__init__.py` — provider registry/factory exports.
- Create `tui/providers/base.py` — provider adapter protocol and redaction helpers.
- Create `tui/providers/opensubtitles.py` — OpenSubtitles adapter.
- Create `tui/providers/subdl.py` — SubDL adapter.
- Create `tui/providers/subsource.py` — SubSource adapter.
- Create `tui/search.py` — concrete, AUTO, and merge coordination.
- Create `tui/jobs.py` — source-aware download, post-processing, and queue jobs.
- Create `tui/config.py` — validated loading, diffing, and atomic persistence.
- Rewrite `tui/state.py` — session and queue transitions built on `tui.domain`.
- Rewrite `tui/app.py` — Textual orchestration only.
- Rewrite `tui/keymap.py` — one action registry shared by bindings, palette, and help.
- Rewrite `tui/style.tcss` — unclipped responsive command-deck layout.
- Create `tui/widgets/views.py` — Search, Queue, History, and Config views.
- Rewrite `tui/widgets/topbar.py`, `query_bar.py`, `results_table.py`,
  `detail_pane.py`, and `status_bar.py` — typed rendering and click events.
- Rewrite `tui/widgets/overlays/*.py` — engine/language setup, merge, palette,
  help, confirmations, and post-download actions.
- Rewrite `tui/tests/` around contracts and user-visible behavior.
- Modify `download_subs.py`, `config.yaml.sample`, and `Readme.md` — startup
  parity, documented settings, and dependency behavior.

## Task 1: Tooling and Typed Domain

**Files:**
- Create: `pyproject.toml`
- Create: `tui/domain.py`
- Test: `tui/tests/test_domain.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing domain tests**

```python
from tui.domain import Candidate, EngineMode, Provider, SearchRequest


def test_candidate_key_is_provider_scoped():
    left = Candidate(provider=Provider.OPENSUBTITLES, provider_id="42", release="A", language="en")
    right = Candidate(provider=Provider.SUBDL, provider_id="42", release="A", language="en")
    assert left.key == "opensubtitles:42"
    assert right.key == "subdl:42"
    assert left.key != right.key


def test_candidate_public_mapping_excludes_private_download_reference():
    candidate = Candidate(
        provider=Provider.SUBDL,
        provider_id="7",
        release="Movie",
        language="en",
        download_ref={"url": "https://example.test/file.zip?api_key=secret"},
    )
    assert "download_ref" not in candidate.as_public_dict()
    assert "secret" not in repr(candidate)


def test_search_request_keeps_effective_query():
    request = SearchRequest(
        media_path="Movie.mkv",
        query="Director Cut",
        language="en",
    )
    assert request.query == "Director Cut"
    assert EngineMode.ASK.value == "ask"
```

- [ ] **Step 2: Verify the tests fail**

Run: `python -m pytest tui/tests/test_domain.py -q`

Expected: collection fails because `tui.domain` does not exist.

- [ ] **Step 3: Implement the typed domain**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Provider(str, Enum):
    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    SUBSOURCE = "subsource"


class EngineMode(str, Enum):
    ASK = "ask"
    AUTO = "auto"
    OPENSUBTITLES = "opensubtitles"
    SUBDL = "subdl"
    SUBSOURCE = "subsource"

    @property
    def provider(self) -> Provider | None:
        try:
            return Provider(self.value)
        except ValueError:
            return None


@dataclass(frozen=True)
class SearchRequest:
    media_path: Path | str
    query: str
    language: str
    hearing_impaired: str = "include"
    show_ai_translated: bool = True


@dataclass
class Candidate:
    provider: Provider
    provider_id: str
    release: str
    language: str
    download_ref: Any = field(default=None, repr=False)
    public_url: str | None = None
    download_count: int = 0
    hash_match: bool = False
    hearing_impaired: bool = False
    ai_translated: bool = False
    author: str = "Unknown"
    score: float = 0.0
    raw_flags: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def key(self) -> str:
        return f"{self.provider.value}:{self.provider_id}"

    def as_public_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "provider": self.provider.value,
            "provider_id": self.provider_id,
            "release": self.release,
            "language": self.language,
            "public_url": self.public_url,
            "download_count": self.download_count,
            "hash_match": self.hash_match,
            "hearing_impaired": self.hearing_impaired,
            "ai_translated": self.ai_translated,
            "author": self.author,
            "score": self.score,
        }
```

Add these concrete result objects to the same module:

```python
@dataclass
class ProviderSearchResult:
    provider: Provider
    candidates: list[Candidate] = field(default_factory=list)
    error: str | None = None


@dataclass
class DownloadResult:
    provider: Provider
    media_path: Path
    subtitle_path: Path | None = None
    error: str | None = None
    conflict_path: Path | None = None

    @property
    def succeeded(self) -> bool:
        return self.subtitle_path is not None and self.error is None


@dataclass
class PostProcessResult:
    cleaned: bool = False
    synced: bool = False
    clean_error: str | None = None
    sync_error: str | None = None


@dataclass
class HealthResult:
    provider: Provider
    configured: bool
    reachable: bool
    authenticated: bool | None = None
    latency_ms: int | None = None
    reason: str | None = None


class QueueStatus(str, Enum):
    QUEUED = "queued"
    SEARCHING = "searching"
    AWAITING_PICK = "awaiting_pick"
    DOWNLOADING = "downloading"
    POST_PROCESSING = "post_processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class QueueItem:
    key: str
    path: Path
    language: str
    engine_mode: EngineMode
    status: QueueStatus = QueueStatus.QUEUED
    candidate_keys: list[str] = field(default_factory=list)
    selected_candidate_key: str | None = None
    error: str | None = None


@dataclass
class HistoryEntry:
    item_key: str
    media_path: Path
    candidate_key: str
    provider: Provider
    language: str
    subtitle_path: Path | None
    postprocess: PostProcessResult
    error: str | None = None
```

- [ ] **Step 4: Add project tooling**

```toml
[tool.black]
target-version = ["py312"]
line-length = 88

[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tui/tests"]
```

Constrain the Requests/chardet conflict in `requirements.txt` with
`chardet<6` and require a Textual version compatible with the tested API.

- [ ] **Step 5: Verify domain tests and lint pass**

Run: `python -m pytest tui/tests/test_domain.py -q`

Expected: all domain tests pass.

Run: `python -m ruff check tui/domain.py tui/tests/test_domain.py`

Expected: exit code 0.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt tui/domain.py tui/tests/test_domain.py
git commit -m "Build typed TUI domain model"
```

## Task 2: Media Expansion and Configuration Repository

**Files:**
- Create: `tui/media.py`
- Create: `tui/config.py`
- Test: `tui/tests/test_media.py`
- Rewrite: `tui/tests/test_config.py`
- Modify: `config.yaml.sample`

- [ ] **Step 1: Write failing path-expansion tests**

```python
def test_expand_media_paths_expands_directories_non_recursively(tmp_path):
    movie = tmp_path / "Movie.mkv"
    episode = tmp_path / "Episode.mp4"
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "Ignored.mkv").touch()
    movie.touch()
    episode.touch()
    result = expand_media_paths([tmp_path], {"mkv", "mp4"})
    assert result.paths == [movie.resolve(), episode.resolve()]
    assert nested / "Ignored.mkv" not in result.paths


def test_expand_media_paths_reports_unsupported_input(tmp_path):
    note = tmp_path / "notes.txt"
    note.touch()
    result = expand_media_paths([note], {"mkv"})
    assert result.paths == []
    assert result.issues[0].kind == "unsupported"
```

- [ ] **Step 2: Verify media tests fail**

Run: `python -m pytest tui/tests/test_media.py -q`

Expected: fails because `expand_media_paths` is missing.

- [ ] **Step 3: Implement deterministic expansion**

```python
def expand_media_paths(
    inputs: Iterable[str | Path], supported_extensions: set[str]
) -> MediaExpansion:
    accepted: list[Path] = []
    issues: list[MediaIssue] = []
    seen: set[Path] = set()
    for raw in inputs:
        path = Path(raw).resolve()
        candidates = sorted(path.iterdir()) if path.is_dir() else [path]
        found = False
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower().lstrip(".") in supported_extensions:
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    accepted.append(resolved)
                found = True
        if not found:
            issues.append(MediaIssue(path=path, kind="unsupported"))
    return MediaExpansion(paths=accepted, issues=issues)
```

- [ ] **Step 4: Write failing complete-config round-trip tests**

```python
def test_config_repository_round_trips_supported_fields_atomically(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    repo = ConfigRepository(path)
    config = repo.load()
    config.general.preferred_backend = EngineMode.SUBDL
    config.providers[Provider.SUBDL].languages["Japanese"] = "ja"
    diff = repo.save(config)
    reloaded = repo.load()
    assert reloaded.general.preferred_backend is EngineMode.SUBDL
    assert reloaded.providers[Provider.SUBDL].languages["Japanese"] == "ja"
    assert "subdl.languages.Japanese" in diff.changed_fields
    assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 5: Verify config tests fail**

Run: `python -m pytest tui/tests/test_config.py -q`

Expected: fails because `ConfigRepository` is missing.

- [ ] **Step 6: Implement validated, atomic configuration**

Use the following configuration objects and atomic save boundary:

```python
@dataclass
class GeneralConfig:
    preferred_backend: EngineMode = EngineMode.ASK
    skip_interactive_menu: bool = False
    sync_audio_to_subs: str = "ask"
    auto_selection: bool = False
    opt_force_utf8: bool = True
    no_tui: bool = False
    hearing_impaired: str = "include"
    show_ai_translated: bool = True


@dataclass
class ProviderConfig:
    values: dict[str, Any]
    languages: dict[str, str]

    @property
    def configured(self) -> bool:
        secret_keys = {
            Provider.OPENSUBTITLES: ("username", "password", "api_key", "user_agent"),
            Provider.SUBDL: ("api_key",),
            Provider.SUBSOURCE: ("api_key",),
        }
        provider = Provider(self.values["provider"])
        return all(bool(self.values.get(key)) for key in secret_keys[provider])


@dataclass
class CleaningConfig:
    enabled: bool = True
    ads_file_path: Path | None = None
    separator: str = ","


@dataclass
class ApplicationConfig:
    general: GeneralConfig
    providers: dict[Provider, ProviderConfig]
    cleaning: CleaningConfig
    extra: dict[str, Any] = field(default_factory=dict)


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
```

The supported persisted keys are:

```python
SUPPORTED_GENERAL_FIELDS = {
    "preferred_backend",
    "skip_interactive_menu",
    "sync_audio_to_subs",
    "auto_selection",
    "opt_force_utf8",
    "no_tui",
    "hearing_impaired",
    "show_ai_translated",
}
```

Provider credentials remain opaque strings and never appear in diff values.

- [ ] **Step 7: Verify configuration and media tests pass**

Run: `python -m pytest tui/tests/test_media.py tui/tests/test_config.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add tui/media.py tui/config.py tui/tests/test_media.py tui/tests/test_config.py config.yaml.sample
git commit -m "Add safe media and config repositories"
```

## Task 3: Provider Adapter Contracts

**Files:**
- Create: `tui/providers/__init__.py`
- Create: `tui/providers/base.py`
- Create: `tui/providers/opensubtitles.py`
- Create: `tui/providers/subdl.py`
- Create: `tui/providers/subsource.py`
- Test: `tui/tests/test_providers.py`
- Modify: `library/OpenSubtitles.py`
- Modify: `library/SubDL.py`
- Modify: `library/SubSource.py`

- [ ] **Step 1: Write failing normalization and redaction tests**

```python
def test_subdl_adapter_keeps_authenticated_url_private():
    adapter = SubDLAdapter(client=FakeSubDL([SUBDL_RESPONSE]))
    result = adapter.search(REQUEST)
    candidate = result.candidates[0]
    assert candidate.provider is Provider.SUBDL
    assert candidate.key.startswith("subdl:")
    assert "api_key" not in str(candidate.as_public_dict())
    assert candidate.public_url is None
    assert candidate.download_ref["attributes"]["url"].endswith("api_key=secret")


def test_subsource_adapter_normalizes_language_to_code():
    adapter = SubSourceAdapter(client=FakeSubSource([SUBSOURCE_RESPONSE]))
    result = adapter.search(REQUEST)
    assert result.candidates[0].language == "en"


def test_provider_error_is_distinct_from_zero_results():
    failed = OpenSubtitlesAdapter(client=FailingClient()).search(REQUEST)
    empty = OpenSubtitlesAdapter(client=EmptyClient()).search(REQUEST)
    assert failed.error is not None
    assert empty.error is None
    assert empty.candidates == []
```

- [ ] **Step 2: Verify provider tests fail**

Run: `python -m pytest tui/tests/test_providers.py -q`

Expected: fails because provider adapters do not exist.

- [ ] **Step 3: Define the adapter protocol and sanitizer**

```python
class ProviderAdapter(Protocol):
    provider: Provider

    def search(self, request: SearchRequest) -> ProviderSearchResult: ...
    def download(self, candidate: Candidate, media_path: Path) -> DownloadResult: ...
    def health(self) -> HealthResult: ...


SENSITIVE_QUERY_KEYS = {"api_key", "token", "key", "authorization"}


def public_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
    return None if keys & SENSITIVE_QUERY_KEYS else url
```

- [ ] **Step 4: Add the three provider adapters**

All three adapters use this normalization helper:

```python
def candidate_from_standardized(
    provider: Provider,
    row: dict[str, Any],
    *,
    language_aliases: Mapping[str, str],
) -> Candidate:
    attributes = row.get("attributes") or {}
    provider_id = str(row.get("id") or "")
    if not provider_id:
        fingerprint = sha256(
            f"{attributes.get('release', '')}|{attributes.get('language', '')}".encode()
        ).hexdigest()[:16]
        provider_id = f"fingerprint-{fingerprint}"
    language = normalize_language(
        str(attributes.get("language") or ""), language_aliases
    )
    return Candidate(
        provider=provider,
        provider_id=provider_id,
        release=str(attributes.get("release") or ""),
        language=language,
        download_ref=copy.deepcopy(row),
        public_url=public_url(attributes.get("url")),
        download_count=int(attributes.get("download_count") or 0),
        hash_match=bool(attributes.get("moviehash_match")),
        hearing_impaired=bool(attributes.get("hi")),
        ai_translated=bool(
            attributes.get("ai_translated")
            or attributes.get("machine_translated")
        ),
        author=str(attributes.get("author") or "Unknown"),
    )
```

The provider `search` methods have the following complete control flow:

```python
def search(self, request: SearchRequest) -> ProviderSearchResult:
    try:
        rows = self.client.search_candidates(
            Path(request.media_path), request.language, request.query
        )
    except ProviderRequestError as exc:
        return ProviderSearchResult(provider=self.provider, error=str(exc))
    candidates = [
        candidate_from_standardized(
            self.provider,
            row,
            language_aliases=self.language_aliases,
        )
        for row in rows
    ]
    return ProviderSearchResult(provider=self.provider, candidates=candidates)
```

Their `download` methods pass only `candidate.download_ref` to the matching
client and return the exact `Path` returned by that client. OpenSubtitles uses
`get_download_link` plus `save_subtitle`; SubDL and SubSource use
`download_single_subtitle`.

Add narrow public `search_candidates(path, language)` methods to the three
library clients. These methods delegate to existing provider logic and raise a
typed provider exception when a request failed instead of printing and
returning an indistinguishable empty list.

- [ ] **Step 5: Verify provider contract tests pass**

Run: `python -m pytest tui/tests/test_providers.py -q`

Expected: all tests pass.

Run: `python -m ruff check tui/providers library/OpenSubtitles.py library/SubDL.py library/SubSource.py`

Expected: no new violations in changed lines; existing unrelated library
violations are recorded for Task 10.

- [ ] **Step 6: Commit**

```bash
git add tui/providers tui/tests/test_providers.py library/OpenSubtitles.py library/SubDL.py library/SubSource.py
git commit -m "Add source-aware subtitle provider adapters"
```

## Task 4: Search Coordinator

**Files:**
- Create: `tui/search.py`
- Test: `tui/tests/test_search.py`
- Delete after migration: `tui/tests/test_services.py`

- [ ] **Step 1: Write failing merge identity and concurrency tests**

```python
def test_merge_retains_same_raw_id_from_all_providers():
    adapters = {
        provider: FakeAdapter(provider, [candidate(provider, "42")])
        for provider in Provider
    }
    result = SearchCoordinator(adapters).merge(REQUEST)
    assert {item.key for item in result.candidates} == {
        "opensubtitles:42",
        "subdl:42",
        "subsource:42",
    }


def test_merge_retains_successes_and_reports_partial_failure():
    adapters = {
        Provider.OPENSUBTITLES: FakeAdapter.with_error("network down"),
        Provider.SUBDL: FakeAdapter(Provider.SUBDL, [candidate(Provider.SUBDL, "1")]),
    }
    result = SearchCoordinator(adapters).merge(REQUEST)
    assert [item.key for item in result.candidates] == ["subdl:1"]
    assert result.errors[Provider.OPENSUBTITLES] == "network down"


def test_merge_runs_provider_calls_concurrently():
    gate = threading.Barrier(3)
    adapters = {provider: BarrierAdapter(provider, gate) for provider in Provider}
    result = SearchCoordinator(adapters).merge(REQUEST)
    assert len(result.candidates) == 3
```

- [ ] **Step 2: Verify merge tests fail**

Run: `python -m pytest tui/tests/test_search.py -q`

Expected: fails because `SearchCoordinator` does not exist.

- [ ] **Step 3: Implement concrete and concurrent merge search**

Use `ThreadPoolExecutor(max_workers=len(adapters))`. Dedupe by
`Candidate.key`, apply shared AI and hearing-impaired filters, score each
candidate through `SubtitleUtils.score_subtitle`, and sort by:

```python
key=lambda item: (
    item.score,
    item.hash_match,
    item.download_count,
    -provider_priority[item.provider],
)
```

- [ ] **Step 4: Write failing AUTO fallback tests**

```python
def test_auto_falls_back_after_error():
    coordinator = coordinator_for(
        subsource=error("down"),
        opensubtitles=success([]),
        subdl=success([candidate(Provider.SUBDL, "8")]),
    )
    result = coordinator.auto(REQUEST)
    assert result.selected_provider is Provider.SUBDL
    assert result.attempted == [
        Provider.SUBSOURCE,
        Provider.OPENSUBTITLES,
        Provider.SUBDL,
    ]


def test_health_does_not_exclude_a_working_provider():
    coordinator = coordinator_for(
        opensubtitles=success([candidate(Provider.OPENSUBTITLES, "1")])
    )
    result = coordinator.merge(
        REQUEST,
        health={
            Provider.OPENSUBTITLES: HealthResult(
                provider=Provider.OPENSUBTITLES,
                configured=True,
                reachable=False,
                reason="probe failed",
            )
        },
    )
    assert result.candidates[0].provider is Provider.OPENSUBTITLES
```

- [ ] **Step 5: Implement AUTO with advisory health**

Start from `[SUBSOURCE, OPENSUBTITLES, SUBDL]`, skip only unconfigured
adapters, move positively healthy providers ahead without removing others, and
stop on the first non-empty successful result.

- [ ] **Step 6: Verify search tests pass**

Run: `python -m pytest tui/tests/test_search.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add tui/search.py tui/tests/test_search.py
git commit -m "Implement safe multi-provider subtitle search"
```

## Task 5: Source-Aware Download and Truthful Post-Processing

**Files:**
- Create: `tui/jobs.py`
- Test: `tui/tests/test_jobs.py`
- Modify: `library/clean_subtitles.py`
- Modify: `library/subtitle_utils.py`
- Modify: `library/sync_subtitles.py`

- [ ] **Step 1: Write failing provider-dispatch tests**

```python
def test_download_dispatches_to_candidate_provider(tmp_path):
    adapters = {
        Provider.OPENSUBTITLES: RecordingAdapter(Provider.OPENSUBTITLES),
        Provider.SUBDL: RecordingAdapter(Provider.SUBDL),
    }
    candidate = candidate_for(Provider.SUBDL, "77")
    result = JobCoordinator(adapters).download(candidate, tmp_path / "Movie.mkv")
    assert result.provider is Provider.SUBDL
    assert adapters[Provider.SUBDL].downloads == [candidate.key]
    assert adapters[Provider.OPENSUBTITLES].downloads == []


def test_existing_target_requires_explicit_replace(tmp_path):
    target = tmp_path / "Movie.en.srt"
    target.write_text("old", encoding="utf-8")
    result = JobCoordinator(adapters).download(candidate, tmp_path / "Movie.mkv")
    assert result.conflict_path == target
    assert target.read_text(encoding="utf-8") == "old"
```

- [ ] **Step 2: Verify download tests fail**

Run: `python -m pytest tui/tests/test_jobs.py -q`

Expected: fails because `JobCoordinator` does not exist.

- [ ] **Step 3: Implement source-aware downloads**

Dispatch exclusively through `self.adapters[candidate.provider]`. The adapter
must write to a temporary sibling path and atomically replace the final path
only after success and explicit overwrite authorization.

- [ ] **Step 4: Write failing post-processing outcome tests**

```python
def test_clean_failure_is_not_recorded_as_success(tmp_path):
    cleaner = FailingCleaner("bad ads pattern")
    result = JobCoordinator(adapters, cleaner=cleaner).postprocess(
        DOWNLOAD, clean=True, sync=False, ads_path=tmp_path / "ads.txt"
    )
    assert result.cleaned is False
    assert result.clean_error == "bad ads pattern"


def test_cleaner_receives_configured_ads_path(tmp_path):
    cleaner = RecordingCleaner()
    ads = tmp_path / "custom-ads.txt"
    JobCoordinator(adapters, cleaner=cleaner).postprocess(
        DOWNLOAD, clean=True, sync=False, ads_path=ads
    )
    assert cleaner.ads_paths == [ads]
```

- [ ] **Step 5: Make clean and sync contracts truthful**

Change the library helpers used by the TUI to either return `True` or raise a
specific exception. Keep legacy wrappers that print and return `False` for the
numbered CLI. The TUI job coordinator records clean and sync independently and
never infers success from a swallowed exception.

- [ ] **Step 6: Verify job tests pass**

Run: `python -m pytest tui/tests/test_jobs.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add tui/jobs.py tui/tests/test_jobs.py library/clean_subtitles.py library/subtitle_utils.py library/sync_subtitles.py
git commit -m "Make downloads and post-processing truthful"
```

## Task 6: Session State and Queue Progression

**Files:**
- Rewrite: `tui/state.py`
- Test: `tui/tests/test_state.py`

- [ ] **Step 1: Write failing startup and queue tests**

```python
def test_ask_backend_remains_ask_until_user_selects():
    state = SessionState.from_config(config(preferred_backend="ask"))
    assert state.engine_mode is EngineMode.ASK
    assert state.needs_engine_setup


def test_interactive_startup_requests_language_after_engine():
    state = SessionState.from_config(config(skip_interactive_menu=False))
    state.choose_engine(EngineMode.SUBDL)
    assert state.needs_language_setup


def test_completed_item_advances_to_next_non_terminal_item():
    state = SessionState(queue=[queue_item("a.mkv"), queue_item("b.mkv")])
    state.mark_complete(state.active_item.key, HISTORY)
    assert state.active_item.path.name == "b.mkv"


def test_language_scope_updates_only_requested_items():
    state = state_with_three_items()
    state.set_language("ar", scope="current")
    assert [item.language for item in state.queue] == ["ar", "en", "en"]
    state.set_language("fr", scope="remaining")
    assert [item.language for item in state.queue] == ["fr", "fr", "fr"]
```

- [ ] **Step 2: Verify state tests fail**

Run: `python -m pytest tui/tests/test_state.py -q`

Expected: failures show the existing state cannot represent ASK or per-item
language/provider choices.

- [ ] **Step 3: Implement explicit session transitions**

`SessionState` owns queue order and exposes transition methods:

```python
def active_item(self) -> QueueItem | None: ...
def choose_engine(self, mode: EngineMode, scope: str = "remaining") -> None: ...
def set_language(self, code: str, scope: str = "remaining") -> None: ...
def begin_search(self, item_key: str) -> None: ...
def set_candidates(self, item_key: str, candidates: list[Candidate]) -> None: ...
def begin_download(self, item_key: str, candidate_key: str) -> None: ...
def mark_complete(self, item_key: str, history: HistoryEntry) -> None: ...
def mark_failed(self, item_key: str, error: str) -> None: ...
def retry(self, item_key: str) -> None: ...
def skip(self, item_key: str) -> None: ...
```

Every method validates the current status and raises `InvalidTransition` for
impossible changes.

- [ ] **Step 4: Verify state tests pass**

Run: `python -m pytest tui/tests/test_state.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tui/state.py tui/tests/test_state.py
git commit -m "Model reliable TUI queue progression"
```

## Task 7: Rebuild the Textual Application Shell and Views

**Files:**
- Rewrite: `tui/app.py`
- Rewrite: `tui/style.tcss`
- Create: `tui/widgets/views.py`
- Rewrite: `tui/widgets/topbar.py`
- Rewrite: `tui/widgets/query_bar.py`
- Rewrite: `tui/widgets/results_table.py`
- Rewrite: `tui/widgets/detail_pane.py`
- Rewrite: `tui/widgets/status_bar.py`
- Test: `tui/tests/test_app.py`

- [ ] **Step 1: Write failing visible-navigation tests**

```python
async def test_all_four_tabs_are_real_views(app, pilot):
    for key, view_id in [("1", "search-view"), ("2", "queue-view"), ("3", "history-view"), ("4", "config-view")]:
        await pilot.press(key)
        assert app.state.active_view == view_id.removesuffix("-view")
        assert app.query_one(f"#{view_id}").display


async def test_lowercase_engine_and_language_shortcuts_open_choices(app, pilot):
    await pilot.press("b")
    assert isinstance(app.screen, EngineSwitcher)
    await pilot.press("escape")
    await pilot.press("l")
    assert isinstance(app.screen, LanguagePopover)


async def test_query_submit_uses_edited_value(app, pilot):
    await pilot.press("/")
    query = app.query_one("#query-input", Input)
    query.value = "Director Cut"
    await pilot.press("enter")
    assert app.last_search_request.query == "Director Cut"
```

- [ ] **Step 2: Verify application tests fail**

Run: `python -m pytest tui/tests/test_app.py -q`

Expected: failures reproduce decorative tabs, uppercase-only shortcuts, and the
ignored query.

- [ ] **Step 3: Implement the application shell**

Compose `TopBar`, one `ContentSwitcher` with four views, and `StatusBar`.
Bindings use lowercase keys and retain uppercase compatibility aliases. Startup
expands media paths, loads state, opens engine/language setup when required,
then launches a background search for the active item.

- [ ] **Step 4: Compose responsive views**

Use this fixed application hierarchy:

```python
def compose(self) -> ComposeResult:
    yield TopBar()
    with ContentSwitcher(initial="search-view", id="workspace"):
        yield SearchView(id="search-view")
        yield QueueView(id="queue-view")
        yield HistoryView(id="history-view")
        yield ConfigView(id="config-view")
    yield StatusBar()


class SearchView(Container):
    def compose(self) -> ComposeResult:
        yield QueryBar()
        yield Static(id="state-banner")
        with Horizontal(id="search-split"):
            yield ResultsTable()
            yield DetailPane()
```

Queue and History each compose one keyed `DataTable`. Config composes one
`VerticalScroll` containing general, post-processing, search-filter, and
provider-language groups. Use `height: auto` for the top and status bars,
`height: 1fr` for `#workspace`, and:

```css
@media (max-width: 90) {
    #detail-pane {
        display: none;
    }
    #search-split {
        layout: vertical;
    }
}
```

- [ ] **Step 5: Write and pass row-selection tests**

```python
async def test_mouse_or_table_cursor_selects_download_candidate(app, pilot):
    table = app.query_one(ResultsTable)
    table.move_cursor(row=1)
    await pilot.pause()
    assert app.state.selected_candidate_key == app.state.candidates[1].key
    app.action_download_selected()
    assert app.last_download_candidate_key == app.state.candidates[1].key
```

Run: `python -m pytest tui/tests/test_app.py -q`

Expected: all app tests pass.

- [ ] **Step 6: Commit**

```bash
git add tui/app.py tui/style.tcss tui/widgets/views.py tui/widgets/topbar.py tui/widgets/query_bar.py tui/widgets/results_table.py tui/widgets/detail_pane.py tui/widgets/status_bar.py tui/tests/test_app.py
git commit -m "Rebuild the Textual command deck shell"
```

## Task 8: Rebuild Overlays, Actions, and Configuration UX

**Files:**
- Rewrite: `tui/keymap.py`
- Rewrite: `tui/widgets/overlays/engine_switcher.py`
- Rewrite: `tui/widgets/overlays/lang_popover.py`
- Rewrite: `tui/widgets/overlays/palette.py`
- Rewrite: `tui/widgets/overlays/post_download_toast.py`
- Create: `tui/widgets/overlays/help.py`
- Test: `tui/tests/test_overlays.py`
- Test: `tui/tests/test_config_view.py`

- [ ] **Step 1: Write failing engine/language behavior tests**

```python
async def test_engine_picker_returns_merge_state():
    result = await run_screen(
        EngineSwitcher(engines=ENGINES, current=EngineMode.SUBDL, merge=False),
        keys=["m", "enter"],
    )
    assert result.engine is EngineMode.SUBDL
    assert result.merge is True


async def test_language_picker_shows_active_engine_languages():
    screen = LanguagePopover(
        languages_by_provider={
            Provider.OPENSUBTITLES: {"English": "en"},
            Provider.SUBDL: {"Arabic": "ar"},
        },
        providers=[Provider.SUBDL],
        current="ar",
    )
    async with screen_app(screen) as pilot:
        assert "العربية" in screen.query_one("#lang-list").renderable.plain
        assert "English" not in screen.query_one("#lang-list").renderable.plain
```

- [ ] **Step 2: Verify overlay tests fail**

Run: `python -m pytest tui/tests/test_overlays.py -q`

Expected: failures reproduce discarded merge state and flattened languages.

- [ ] **Step 3: Add typed overlay results**

```python
@dataclass(frozen=True)
class EngineChoice:
    engine: EngineMode
    merge: bool


@dataclass(frozen=True)
class LanguageChoice:
    code: str
    scope: Literal["current", "remaining"]
    providers_to_update: frozenset[Provider] = frozenset()


@dataclass(frozen=True)
class PostProcessChoice:
    clean: bool
    sync: bool
    pin_default: bool = False
```

`EngineSwitcher.action_select` dismisses with
`EngineChoice(self.selected_engine, self.merge)`.
`LanguagePopover.action_select` dismisses with its selected code, selected
scope, and checked providers. `PostDownloadPanel` subclasses `Container`,
docks to the bottom, and posts a `ChoiceMade` message instead of pushing a
modal screen.

- [ ] **Step 4: Build one action registry**

```python
@dataclass(frozen=True)
class AppAction:
    id: str
    label: str
    category: str
    shortcut: str | None
    handler_name: str
    enabled_when: Callable[[SessionState], tuple[bool, str | None]]
```

Bindings, command palette, clickable controls, and Help derive from this
registry. Tests assert every displayed shortcut maps to one callable action.

- [ ] **Step 5: Write failing complete-config UX tests**

```python
async def test_config_save_persists_every_dirty_supported_field(app, pilot):
    await pilot.press("4")
    app.config_draft.general.preferred_backend = EngineMode.SUBDL
    app.config_draft.providers[Provider.SUBDL].languages["Japanese"] = "ja"
    await pilot.press("ctrl+s", "enter")
    saved = ConfigRepository(app.config_path).load()
    assert saved.general.preferred_backend is EngineMode.SUBDL
    assert saved.providers[Provider.SUBDL].languages["Japanese"] == "ja"
    assert app.config_dirty is False
```

- [ ] **Step 6: Implement Config view save/discard flow**

`Ctrl+S` computes a field-level redacted diff, confirms, saves atomically, and
rebuilds only affected adapters. Leaving with a dirty draft prompts Save,
Discard, or Stay. Secret values show only configured/missing.

- [ ] **Step 7: Verify overlay and config tests pass**

Run: `python -m pytest tui/tests/test_overlays.py tui/tests/test_config_view.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add tui/keymap.py tui/widgets/overlays tui/tests/test_overlays.py tui/tests/test_config_view.py
git commit -m "Finish command deck controls and configuration"
```

## Task 9: End-to-End Queue, Download, and Error Flows

**Files:**
- Test: `tui/tests/test_workflow.py`
- Modify: `tui/app.py`
- Modify: `tui/jobs.py`
- Modify: `tui/widgets/views.py`

- [ ] **Step 1: Write failing multi-file workflow tests**

```python
async def test_successful_download_advances_to_next_item(app, pilot):
    assert app.state.active_item.path.name == "a.mkv"
    app.complete_download_for_test(history_for("a.mkv"))
    await pilot.pause()
    assert app.state.active_item.path.name == "b.mkv"
    assert app.last_search_request.media_path.name == "b.mkv"


async def test_failed_item_can_retry_without_losing_remaining_queue(app, pilot):
    app.fail_active_item_for_test("network down")
    await pilot.press("2")
    app.action_retry_item(app.state.active_item.key)
    assert app.state.active_item.status is QueueStatus.QUEUED
    assert len(app.state.queue) == 2


async def test_partial_merge_error_is_visible_with_results(app, pilot):
    await app.run_merge_for_test(PARTIAL_RESULT)
    assert app.query_one(ResultsTable).row_count == 1
    assert "OpenSubtitles: network down" in app.query_one("#state-banner").renderable.plain
```

- [ ] **Step 2: Verify workflow tests fail**

Run: `python -m pytest tui/tests/test_workflow.py -q`

Expected: fails because the rebuilt application has not yet connected all job
completion transitions.

- [ ] **Step 3: Connect background jobs to state transitions**

Use generation-checked completions:

```python
@work(thread=True, group="search", exclusive=True)
def run_search(self, item_key: str, generation: int, request: SearchRequest) -> None:
    result = self.search_coordinator.run(self.state.engine_mode, request)
    self.call_from_thread(
        self.apply_search_result, item_key, generation, request, result
    )


def apply_search_result(
    self,
    item_key: str,
    generation: int,
    request: SearchRequest,
    result: CoordinatedSearchResult,
) -> None:
    if generation != self.search_generation or self.state.active_item.key != item_key:
        return
    self.last_search_request = request
    if result.error and not result.candidates:
        self.state.mark_failed(item_key, result.error)
        return
    self.state.set_candidates(item_key, result.candidates)
    if self.state.auto_selection and result.candidates:
        self.start_download(item_key, result.candidates[0].key)
```

Download and post-processing workers follow the same pattern using item and
candidate keys. A failed item remains `FAILED`; `retry` returns it to `QUEUED`;
`mark_complete` selects the next non-terminal item and calls
`start_active_search`.

- [ ] **Step 4: Connect preview, public URL copy, help, and safe quit**

```python
def action_preview(self) -> None:
    candidate = self.state.selected_candidate
    if candidate is not None:
        self.push_screen(CandidatePreview(candidate))


def action_copy_url(self) -> None:
    candidate = self.state.selected_candidate
    if candidate is None or candidate.public_url is None:
        self.notify("This provider has no public, credential-free URL.", severity="warning")
        return
    self.copy_to_clipboard(candidate.public_url)


def action_quit(self) -> None:
    needs_confirm = (
        self.config_dirty
        or self.workers.count > 0
        or any(item.status not in TERMINAL_STATUSES for item in self.state.queue)
    )
    if needs_confirm:
        self.push_screen(QuitConfirm(), self._finish_quit)
    else:
        self.exit()
```

- [ ] **Step 5: Verify workflow tests pass**

Run: `python -m pytest tui/tests/test_workflow.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tui/app.py tui/jobs.py tui/widgets/views.py tui/tests/test_workflow.py
git commit -m "Complete reliable TUI batch workflows"
```

## Task 10: Migration Cleanup, Documentation, and Full Verification

**Files:**
- Modify: `download_subs.py`
- Modify: `Readme.md`
- Modify: `config.yaml.sample`
- Delete: obsolete TUI test modules and phase-only helpers
- Modify: all changed Python files for Ruff/Black cleanup

- [ ] **Step 1: Write launcher parity tests**

```python
def test_tui_launcher_preserves_ask_and_expands_paths(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr("tui.app.run_tui", lambda **kwargs: captured.update(kwargs))
    invoke_main([str(tmp_path)], config=CONFIG_WITH_ASK)
    assert captured["config"]["general"]["preferred_backend"] == "ask"


def test_no_tui_still_dispatches_legacy(monkeypatch):
    called = []
    monkeypatch.setattr("download_subs.run_legacy", lambda *args: called.append(args))
    invoke_main(["--no-tui", "Movie.mkv"])
    assert len(called) == 1
```

- [ ] **Step 2: Verify launcher tests fail if parity is broken**

Run: `python -m pytest tui/tests/test_launcher.py -q`

Expected: the ASK assertion fails against the old TUI translation path.

- [ ] **Step 3: Simplify launcher and remove obsolete implementation**

Keep lazy Textual import and `--no-tui`. Pass parsed overrides and raw config to
the new bootstrap without converting ASK or selecting a language in
`download_subs.py`. Delete obsolete `tui/services.py`,
`tui/widgets/config_tab.py`, phase comments, and tests that only assert the
removed implementation.

- [ ] **Step 4: Update user documentation**

Document:

- startup engine/language setup;
- keys and mouse controls;
- concrete, AUTO, and merge semantics;
- provider-specific language configuration;
- queue retry/skip;
- safe config saves;
- secret-safe Copy URL behavior;
- `--no-tui` compatibility.

- [ ] **Step 5: Run formatting and lint**

Run: `python -m black --check download_subs.py tui library/OpenSubtitles.py library/SubDL.py library/SubSource.py library/clean_subtitles.py library/subtitle_utils.py library/sync_subtitles.py`

Expected: exit code 0.

Run: `python -m ruff check download_subs.py tui library/OpenSubtitles.py library/SubDL.py library/SubSource.py library/clean_subtitles.py library/subtitle_utils.py library/sync_subtitles.py`

Expected: exit code 0.

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest -q`

Expected: all collected tests pass with no Requests/chardet warning.

- [ ] **Step 7: Verify rendered layouts**

Capture Textual screenshots at:

- 120×40: Search, Queue, History, Config, language, engine, palette, help;
- 80×24: Search, Queue, Config, language, engine.

Inspect each PNG for clipped controls, hidden choices, overflow, unreadable
focus state, or blank dead regions. Re-run the focused UI test after each style
correction.

- [ ] **Step 8: Run secret scan and Git checks**

Run:

```bash
rg -n "api_key=[^<[:space:]]+|Authorization: Bearer [^<[:space:]]+" tui docs Readme.md
git diff --check
git status --short
```

Expected: no credential values in tracked output, no whitespace errors, and
only intended source changes.

- [ ] **Step 9: Run opt-in live provider smoke checks**

Using the local configured credentials without printing them:

- OpenSubtitles search returns a typed count/status;
- SubDL filename search returns typed candidates with no public authenticated URL;
- SubSource title/subtitle search returns normalized language codes;
- health results distinguish configured, reachable, and authenticated.

Do not download a subtitle during this smoke test.

- [ ] **Step 10: Commit**

```bash
git add download_subs.py Readme.md config.yaml.sample requirements.txt pyproject.toml tui library
git commit -m "Complete production TUI rebuild"
```
