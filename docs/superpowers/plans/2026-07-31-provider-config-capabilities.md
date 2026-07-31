# Provider Configuration Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make UTF-8 normalization robust, make provider metadata filtering truthful, and centralize configurable video-media discovery.

**Architecture:** Keep search policy enforcement centralized in `SearchCoordinator`, while ensuring provider clients return the broadest result set needed for local filtering. Keep encoding conversion in `JobCoordinator` as a provider-independent post-download operation. Resolve one canonical media-extension set in `tui.media` and pass it to both TUI and headless path expansion.

**Tech Stack:** Python 3.10+, pytest, requests, chardet, Textual TUI domain/provider layers.

## Global Constraints

- Preserve deterministic UTF-8/UTF-16 handling and atomic file replacement.
- Do not infer AI translation or hearing-impaired status from subtitle text.
- Do not add translation features or alter result ranking.
- Preserve unrelated working-tree changes, especially the existing `Readme.md` edits.
- Use application-side filtering as the final policy boundary.
- Normalize media extensions to lowercase without a leading dot; exclusions win over inclusions.

---

### Task 1: Return inclusive OpenSubtitles candidates

**Files:**
- Modify: `tui/providers/factory.py:36-48`
- Test: `tui/tests/test_providers.py`

**Interfaces:**
- Consumes: `OpenSubtitles(..., hearing_impaired: bool)` and `OpenSubtitles.search(...)`.
- Produces: TUI-created OpenSubtitles clients whose searches send `hearing_impaired=include`; `SearchCoordinator._is_visible()` remains the final `include`/`exclude`/`only` filter.

- [ ] **Step 1: Write failing tests for inclusive construction and request parameters**

Add a factory test that patches `OpenSubtitles.login`, builds a configured `ApplicationConfig`, creates adapters, and asserts the lazy OpenSubtitles client has `hearing_impaired is True`. Add a request test with a recording `requests.get` response and assert `params["hearing_impaired"] == "include"`.

```python
def test_factory_requests_inclusive_opensubtitles_results(monkeypatch):
    monkeypatch.setattr(OpenSubtitles, "login", lambda _self: "token")
    providers = {
        provider: ProviderConfig(provider)
        for provider in Provider
    }
    providers[Provider.OPENSUBTITLES].values.update(
        username="user",
        password="pass",
        api_key="key",
        user_agent="app",
    )
    config = ApplicationConfig(
        general=GeneralConfig(),
        providers=providers,
        cleaning=CleaningConfig(),
    )
    adapter = create_adapters(config)[Provider.OPENSUBTITLES]

    assert adapter.client.hearing_impaired is True


def test_opensubtitles_search_requests_inclusive_hi_results(monkeypatch):
    captured = {}
    client = object.__new__(OpenSubtitles)
    client.hearing_impaired = True
    client.api_key = "key"
    client.token = "token"
    client.user_agent = "app"
    client.console = QuietConsole()

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": []}

    def fake_get(_url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("library.OpenSubtitles.requests.get", fake_get)
    client.search(media_name="Movie", languages="en")

    assert captured["params"]["hearing_impaired"] == "include"
```

- [ ] **Step 2: Run the focused tests and verify the factory test fails**

Run: `python -m pytest tui/tests/test_providers.py -k "inclusive_opensubtitles or inclusive_hi" -v`

Expected: the request-parameter test passes against existing mapping, while the factory test fails because the client is constructed with `False`.

- [ ] **Step 3: Make TUI-created OpenSubtitles clients inclusive**

In `create_adapters()`, change only the OpenSubtitles constructor argument:

```python
hearing_impaired=True,
```

Leave SubDL and SubSource at `False` so their clients return broad, unfiltered results for coordinator-side filtering.

- [ ] **Step 4: Run provider and search tests**

Run: `python -m pytest tui/tests/test_providers.py tui/tests/test_search.py -v`

Expected: PASS.

- [ ] **Step 5: Commit the provider behavior**

```bash
git add tui/providers/factory.py tui/tests/test_providers.py
git commit -m "Fix hearing-impaired provider filtering"
```

### Task 2: Detect legacy subtitle encodings before UTF-8 rewrite

**Files:**
- Modify: `tui/jobs.py:173-189`
- Test: `tui/tests/test_jobs.py`

**Interfaces:**
- Consumes: `JobCoordinator.postprocess(..., force_utf8: bool, ...)` and raw subtitle bytes.
- Produces: `_normalize_utf8(subtitle_path: Path) -> None`, writing valid UTF-8 atomically while preserving the existing `PostProcessResult.utf8_error` behavior.

- [ ] **Step 1: Write failing tests for UTF-16, Windows-1256, and disabled conversion**

Use a small helper that constructs a successful `DownloadResult`, then add:

```python
def test_force_utf8_normalizes_utf16_subtitle(tmp_path):
    subtitle, download = encoded_download(tmp_path, "hello", "utf-16")
    result = JobCoordinator({}).postprocess(
        download, force_utf8=True, clean=False, sync=False
    )
    assert result.utf8_normalized
    assert subtitle.read_bytes() == b"hello"


def test_force_utf8_detects_windows_1256_subtitle(tmp_path):
    text = "مرحبا بكم في هذا الفيلم"
    subtitle, download = encoded_download(tmp_path, text, "windows-1256")
    result = JobCoordinator({}).postprocess(
        download, force_utf8=True, clean=False, sync=False
    )
    assert result.utf8_normalized
    assert subtitle.read_text(encoding="utf-8") == text


def test_disabled_force_utf8_preserves_original_bytes(tmp_path):
    original = "café".encode("cp1252")
    subtitle, download = encoded_download(tmp_path, "café", "cp1252")
    JobCoordinator({}).postprocess(
        download, force_utf8=False, clean=False, sync=False
    )
    assert subtitle.read_bytes() == original
```

- [ ] **Step 2: Run the focused tests and verify Windows-1256 fails correctly**

Run: `python -m pytest tui/tests/test_jobs.py -k "force_utf8" -v`

Expected: UTF-16 and disabled-conversion cases pass; Windows-1256 fails because the current CP1252 fallback produces different text.

- [ ] **Step 3: Add chardet-backed legacy decoding**

Import `chardet` and replace the unconditional CP1252 fallback with detected decoding, retaining CP1252 when detection supplies no usable encoding:

```python
detected = chardet.detect(data)
encoding = detected.get("encoding") or "cp1252"
try:
    text = data.decode(encoding)
except (LookupError, UnicodeDecodeError):
    text = data.decode("cp1252")
```

Keep the UTF-16 BOM and UTF-8-SIG branches before detection, and keep the temporary-file cleanup and `os.replace()` behavior unchanged.

- [ ] **Step 4: Run post-processing tests**

Run: `python -m pytest tui/tests/test_jobs.py tui/tests/test_post_download.py tui/tests/test_headless.py -v`

Expected: PASS.

- [ ] **Step 5: Commit encoding support**

```bash
git add tui/jobs.py tui/tests/test_jobs.py
git commit -m "Improve subtitle encoding normalization"
```

### Task 3: Document provider capability boundaries and verify regression coverage

**Files:**
- Modify: `Readme.md` in the existing general-settings section
- Test: `tui/tests/test_search.py`
- Test: `test_subtitle_utils.py`

**Interfaces:**
- Consumes: normalized `Candidate.hearing_impaired` and `Candidate.ai_translated` flags.
- Produces: documented best-effort semantics for provider metadata; no new runtime interface.

- [ ] **Step 1: Add focused assertions for provider metadata classification**

Extend existing standardization/search tests to assert that OpenSubtitles treats either translation marker as AI-translated, SubSource machine production is classified as AI-translated, and a SubDL row without a documented marker remains false.

```python
def test_translation_and_hi_flags_are_normalized():
    opensubtitles = candidate_from_standardized(
        Provider.OPENSUBTITLES,
        {"id": "1", "attributes": {
            "hearing_impaired": True,
            "machine_translated": True,
        }},
    )
    assert opensubtitles.hearing_impaired is True
    assert opensubtitles.ai_translated is True
```

- [ ] **Step 2: Run metadata and visibility tests before documentation edits**

Run: `python -m pytest tui/tests/test_search.py tui/tests/test_providers.py test_subtitle_utils.py -v`

Expected: PASS, demonstrating that the runtime classification/filtering already matches the agreed design apart from the OpenSubtitles query bug fixed in Task 1.

- [ ] **Step 3: Clarify setting semantics without replacing existing README edits**

Directly after the general settings table, add one paragraph:

```markdown
`hearing_impaired` and `show_ai_translated` use metadata supplied by each
provider. OpenSubtitles supplies both markers, SubSource supplies HI and machine
production markers, and SubDL currently supplies HI but no dependable AI
translation marker. AI filtering is therefore best-effort for SubDL.
```

- [ ] **Step 4: Run formatting and complete affected tests**

Run: `python -m ruff check tui library download_subs.py`

Run: `python -m pytest tui/tests test_subtitle_utils.py -v`

Expected: both commands PASS with no new warnings.

- [ ] **Step 5: Commit documentation and regression coverage**

```bash
git add Readme.md tui/tests/test_providers.py test_subtitle_utils.py
git commit -m "Document subtitle provider filter capabilities"
```

### Task 4: Centralize configurable media extensions

**Files:**
- Modify: `tui/media.py`
- Modify: `tui/config.py`
- Modify: `tui/app.py`
- Modify: `download_subs.py`
- Modify: `config.yaml.sample`
- Modify: `Readme.md`
- Test: `tui/tests/test_media.py`
- Test: `tui/tests/test_config.py`
- Test: `tui/tests/test_headless.py`

**Interfaces:**
- Produces: `DEFAULT_MEDIA_EXTENSIONS: frozenset[str]` and `resolve_media_extensions(include: Iterable[str] = (), exclude: Iterable[str] = ()) -> set[str]`.
- Consumes: `GeneralConfig.media_extensions_include: list[str]` and `GeneralConfig.media_extensions_exclude: list[str]`, loaded from `general.media_extensions.include` and `.exclude`.

- [ ] **Step 1: Write failing resolution and configuration tests**

Add tests proving representative defaults (`mkv`, `mp4`, `avi`, `av1`), normalization, custom additions, and exclusion precedence:

```python
def test_resolve_media_extensions_extends_and_excludes_defaults():
    extensions = resolve_media_extensions(
        include=[".CUSTOM", "ts"],
        exclude=[".TS", "AVI"],
    )
    assert "custom" in extensions
    assert "mkv" in extensions
    assert "ts" not in extensions
    assert "avi" not in extensions
```

Extend config tests with:

```yaml
general:
  media_extensions:
    include: [custom]
    exclude: [wmv]
```

and assert the two normalized lists load and save under the nested mapping.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest tui/tests/test_media.py tui/tests/test_config.py -v`

Expected: FAIL because the resolver and config fields do not exist.

- [ ] **Step 3: Implement the canonical resolver and config mapping**

In `tui/media.py`, replace the narrow mutable constant with:

```python
DEFAULT_MEDIA_EXTENSIONS = frozenset({
    "3g2", "3gp", "asf", "avi", "av1", "divx", "f4v", "flv",
    "h264", "h265", "hevc", "m2ts", "m2v", "m4v", "mkv", "mov",
    "mp4", "mpeg", "mpg", "mts", "mxf", "ogm", "ogv", "rm",
    "rmvb", "ts", "vob", "webm", "wmv",
})


def resolve_media_extensions(include=(), exclude=()):
    normalize = lambda value: str(value).strip().lower().lstrip(".")
    additions = {normalized for value in include if (normalized := normalize(value))}
    removals = {normalized for value in exclude if (normalized := normalize(value))}
    return (set(DEFAULT_MEDIA_EXTENSIONS) | additions) - removals
```

Add typed include/exclude lists to `GeneralConfig`, load them from the nested
mapping, and save the nested mapping without flattening it into unrelated keys.

- [ ] **Step 4: Route both execution modes through the resolver**

In `SubsApp`, resolve from `self.application_config.general` before calling
`expand_media_paths`. In `run_legacy`, load the validated `ApplicationConfig`
already used for all-provider mode or resolve the raw `general.media_extensions`
mapping, then pass the resulting set to `expand_media_paths`. Remove imports and
uses of the old `MEDIA_EXTENSIONS` name.

- [ ] **Step 5: Run discovery, config, startup, and headless tests**

Run: `python -m pytest tui/tests/test_media.py tui/tests/test_config.py tui/tests/test_startup.py tui/tests/test_headless.py -v`

Expected: PASS.

- [ ] **Step 6: Document defaults and overrides**

Add `general.media_extensions.include` and `.exclude` to `config.yaml.sample`
and the README configuration example. State that exclusions win, recursive mode
still filters files through the effective list, and
`cleaning_subtitles.supported_media` refers to subtitle formats.

- [ ] **Step 7: Commit media discovery behavior**

```bash
git add tui/media.py tui/config.py tui/app.py download_subs.py config.yaml.sample Readme.md tui/tests/test_media.py tui/tests/test_config.py tui/tests/test_headless.py
git commit -m "Centralize configurable media discovery"
```

### Task 5: Final integration verification

**Files:**
- Verify only; no planned production modifications.

**Interfaces:**
- Consumes: all behavior produced by Tasks 1-3.
- Produces: evidence that configuration loading, TUI search, headless search, provider normalization, and post-processing remain compatible.

- [ ] **Step 1: Run the repository's configured test suite**

Run: `python -m pytest -v`

Expected: PASS.

- [ ] **Step 2: Run static checks**

Run: `python -m ruff check tui library download_subs.py`

Run: `git diff --check HEAD~4..HEAD`

Expected: PASS with no whitespace errors.

- [ ] **Step 3: Review the final diff and working tree**

Run: `git status --short`

Run: `git diff HEAD~4 -- tui library tui/tests test_subtitle_utils.py Readme.md config.yaml.sample download_subs.py`

Expected: only task-scoped changes plus the user's pre-existing README work are present; no credentials or generated files are included.
