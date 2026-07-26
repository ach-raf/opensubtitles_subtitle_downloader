# SubDL v2 API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the SubDL backend from the v1 API to the v2 API, add the new `/files/search` filename source to enrich results, and leave cleaner code — without dropping any existing feature.

**Architecture:** Replace the single fat v1 `search()` with a thin v2 HTTP layer (`_request`/`_parse`) plus three focused methods (`search` → `/subtitles/search`, `filename_search` → `/files/search`, `movie_search` → `/movies/search`). All existing search passes are preserved and routed through `/subtitles/search`; a new `_gather_candidates` helper orchestrates them plus the new filename source and a precise season/episode pass. Downloads prefer v2 `unpack_files` single-file URLs, falling back to the existing zip + in-zip episode selection for season packs. Auth moves from `?api_key=` to a Bearer header.

**Tech Stack:** Python 3.10+ (uses `match`/`case` in `subtitle_utils.py`), `requests`, `rich`, `thefuzz`, `pyyaml`. No new dependencies.

## Global Constraints

- **Python 3.10+** required (`match`/`case` already used in `library/subtitle_utils.py`).
- **No new dependencies.** Use only what is in `requirements.txt` (`requests`, `rich`, `thefuzz`, `pyyaml`, etc.).
- **SubDL v2 free-tier only.** Do not call any `/ai/*` endpoint.
- **Auth:** every API call sends `Authorization: Bearer <config["subdl"]["api_key"]>`. The download `url`/`unpack_files[].url` fields returned by SubDL already contain an embedded `?api_key=` and are fetched as-is.
- **Hosts:** API = `https://api.subdl.com/api/v2`. Downloads = `https://dl.subdl.com` (GET; `api.subdl.com` returns 404 for downloads). Confirmed by live probe.
- **Verify against the live API** using the key in `config.yaml` (read-only searches + 1–2 real downloads). The Free plan allows 2000 searches/day and 50 downloads/day.
- **Tests:** keep `test*.py` gitignored; **update fixtures only**, do not add new tests for `library/SubDL.py` (user decision).
- **Commits:** per the user's global rule, commit only with explicit approval. Each task below shows its intended commit message; confirm with the user before running `git commit`.
- **Preserve the standardized subtitle shape** (`{"id": str, "attributes": {...}}`) so the OpenSubtitles backend and the fuzzy scorer in `subtitle_utils.py` stay untouched. New fields are additive only.
- **Do not modify** `library/OpenSubtitles.py` or any backend other than SubDL.

---

## File Structure

- `library/subtitle_utils.py` — update `extract_subdl_subtitle_id` (strip `?api_key=` query) and the `"subdl"` branch of `standardize_subtitle_object` (add `unpack_files`). Shared by both backends; changes are additive.
- `library/SubDL.py` — the main rewrite: v2 HTTP layer, three search methods, `_gather_candidates`, v2 download (single-file first). Single class `SubDL`, kept as one file (matches existing pattern).
- `download_subs.py` — `AUTO` health-check moves to quota-free `/api/v2/me` with a Bearer header.
- `test_subtitle_utils.py` — fixture updates for the two changed helpers.

---

## Task 1: subtitle_utils — v2 id extractor + standardization

**Files:**
- Modify: `library/subtitle_utils.py:27-34` (`extract_subdl_subtitle_id`) and `library/subtitle_utils.py:43-60` (the `"subdl"` branch of `standardize_subtitle_object`)
- Test: `test_subtitle_utils.py:16-26` and `test_subtitle_utils.py:40-65`

**Interfaces:**
- Consumes: nothing (leaf helper).
- Produces: `extract_subdl_subtitle_id(url)` now handles `/subtitle/3458138-8381001.zip?api_key=...` → `"3458138-8381001"`; `standardize_subtitle_object(sub, "subdl")` now includes `attributes["unpack_files"]` (list, default `[]`). Task 2 depends on both.

- [ ] **Step 1: Update the failing fixtures first**

In `test_subtitle_utils.py`, add a v2 (query-string) case to `test_extract_subdl_subtitle_id` and add `unpack_files` to the expected subdl dict.

Replace the body of `test_extract_subdl_subtitle_id` (lines 16-26) with:

```python
    def test_extract_subdl_subtitle_id(self):
        self.assertEqual(
            self.utils.extract_subdl_subtitle_id("/subtitle/12345-67890.zip"),
            "12345-67890",
        )
        # v2 urls carry an embedded ?api_key= query — must be stripped
        self.assertEqual(
            self.utils.extract_subdl_subtitle_id(
                "/subtitle/3458138-8381001.zip?api_key=ABCdef123"
            ),
            "3458138-8381001",
        )
        self.assertIsNone(self.utils.extract_subdl_subtitle_id("/subtitle/"))
        self.assertIsNone(self.utils.extract_subdl_subtitle_id(None))
        self.assertIsNone(self.utils.extract_subdl_subtitle_id(""))
        self.assertEqual(
            self.utils.extract_subdl_subtitle_id("/subtitle/12345.zip"), "12345"
        )
```

In `test_standardize_subtitle_object`, add `"unpack_files": []` to `expected_subdl["attributes"]` and add an input case that carries `unpack_files`. Replace the `expected_subdl = {...}` block (lines 45-61) with:

```python
        expected_subdl = {
            "id": "45678",
            "attributes": {
                "release": "Another Release",
                "language": "es",
                "download_count": 0,
                "ai_translated": False,
                "machine_translated": False,
                "moviehash_match": False,
                "url": "/subtitle/45678.zip",
                "hi": False,
                "full_season": False,
                "author": "Unknown",
                "season": None,
                "episode": None,
                "unpack_files": [],
            },
        }
```

And immediately after the existing `subdl_subtitle` dict assertion, add one more assertion that `unpack_files` passes through:

```python
        subdl_with_unpack = {
            "url": "/subtitle/45678.zip",
            "release_name": "Another Release",
            "language": "es",
            "unpack_files": [
                {"file_n_id": "abc", "url": "/subtitle/abc/def?api_key=x", "format": "srt"}
            ],
        }
        result = self.utils.standardize_subtitle_object(subdl_with_unpack, "subdl")
        self.assertEqual(
            result["attributes"]["unpack_files"],
            [{"file_n_id": "abc", "url": "/subtitle/abc/def?api_key=x", "format": "srt"}],
        )
```

- [ ] **Step 2: Run the two touched tests to verify they fail**

Run: `python -m unittest test_subtitle_utils.TestSubtitleUtils.test_extract_subdl_subtitle_id test_subtitle_utils.TestSubtitleUtils.test_standardize_subtitle_object -v`

Note: the on-disk test file (gitignored) has drifted ahead of the implementation, so these two tests **already fail on the unmodified code** — `extract_subdl_subtitle_id("/subtitle/")` returns `""` (not `None`) and `standardize_subtitle_object({"url": None}, "subdl")` returns a dict (not `None`). After your Step 1 fixture edits they will additionally fail on the new query-string and `unpack_files` assertions. Steps 3-4 fix the implementation so all assertions in both tests pass.

**Scope:** several *other* tests in this file are also failing on baseline (`test_extract_season_and_episode`, `test_get_alternate_names`, `test_score_subtitle`, `test_save_and_read_token`) — those are pre-existing drift unrelated to this migration. **Do not fix them.** Only `test_extract_subdl_subtitle_id` and `test_standardize_subtitle_object` must pass after this task.

- [ ] **Step 3: Fix `extract_subdl_subtitle_id`**

Replace `library/subtitle_utils.py:27-34` with:

```python
    def extract_subdl_subtitle_id(self, url):
        if not url:
            return None
        # v1: '/subtitle/3158195-3172856.zip'
        # v2: '/subtitle/3158195-3172856.zip?api_key=...'  (strip the query first)
        url = url.split("?")[0]
        parts = url.split("/")
        # 'and parts[2]' makes '/subtitle/' (empty id segment) return None, not ''
        if len(parts) >= 3 and parts[2]:
            return parts[2].replace(".zip", "")
        return None
```

- [ ] **Step 4: Update the subdl standardization branch (guard falsy url + add `unpack_files`)**

Replace the entire `"subdl"` case body in `standardize_subtitle_object` (`library/subtitle_utils.py:43-60`) with:

```python
                case "subdl":
                    url = subtitle.get("url")
                    if not url:
                        return None
                    return {
                        "id": self.extract_subdl_subtitle_id(url),
                        "attributes": {
                            "release": subtitle.get("release_name", ""),
                            "language": subtitle.get("language", "").lower(),
                            "download_count": 0,  # SubDL doesn't provide this
                            "ai_translated": False,  # SubDL doesn't provide this
                            "machine_translated": False,
                            "moviehash_match": False,
                            "url": url,
                            "hi": subtitle.get("hi", False),
                            "full_season": subtitle.get("full_season", False),
                            "author": subtitle.get("author", "Unknown"),
                            "season": subtitle.get("season"),
                            "episode": subtitle.get("episode"),
                            "unpack_files": subtitle.get("unpack_files", []),
                        },
                    }
```

- [ ] **Step 5: Run the two touched tests to verify they pass**

Run: `python -m unittest test_subtitle_utils.TestSubtitleUtils.test_extract_subdl_subtitle_id test_subtitle_utils.TestSubtitleUtils.test_standardize_subtitle_object -v`
Expected: both PASS. (The rest of the file has pre-existing failures that are out of scope — see Step 2.)

- [ ] **Step 6: Commit (with user approval)**

```bash
git add library/subtitle_utils.py test_subtitle_utils.py
git commit -m "Update subtitle_utils for SubDL v2 (query-safe id extractor, unpack_files)"
```

---

## Task 2: SubDL v2 search + download migration (behavior preserved)

Migrate the existing behavior to v2. After this task the tool runs end-to-end on v2 (search via `/subtitles/search`, download via the v2 single-file/zip URLs), but with no new enrichment yet.

**Files:**
- Modify: `library/SubDL.py:21-139` (constructor + `search`) and `library/SubDL.py:141-289` (`download_single_subtitle`) and `library/SubDL.py:387-389` (the caller in `process_media_file`)

**Interfaces:**
- Consumes: Task 1's `standardize_subtitle_object` (with `unpack_files`) and `extract_subdl_subtitle_id` (query-safe).
- Produces:
  - `SubDL.__init__`: sets `self.api_base_url = "https://api.subdl.com/api/v2"` and `self.download_base_url = "https://dl.subdl.com"`.
  - `_request(self, path, params) -> dict` — GET with Bearer header, returns parsed JSON.
  - `_parse(self, data) -> (subtitles_list, metadata_list)` — handles `{"error": ...}` and `{"status", "subtitles", "results"}`.
  - `search(self, file_name="", film_name="", imdb_id="", tmdb_id="", sd_id="", languages="en", season=None, episode=None, full_season=False, type="", unpack=True) -> SearchResult` — same call sites as today (kwargs preserved), routed to `/subtitles/search`.
  - `download_single_subtitle(self, subtitle, video_input_path, language_choice="")` — now takes the whole subtitle dict; prefers `unpack_files`, falls back to zip.
  - Helpers: `_select_unpack_file`, `_download_single_file`, `_download_zip`, `_decode_bytes`.

- [ ] **Step 1: Update the constructor (base URLs)**

Replace `library/SubDL.py:34-35` (the two URL assignments) with:

```python
        self.api_base_url = "https://api.subdl.com/api/v2"
        self.download_base_url = "https://dl.subdl.com"
```

- [ ] **Step 2: Replace `search()` and add `_request`/`_parse`**

Replace the entire `search` method (`library/SubDL.py:40-139`) with the HTTP layer plus the new `search`:

```python
    def _request(self, path, params):
        """GET a v2 endpoint with Bearer auth and return parsed JSON."""
        response = requests.get(
            self.api_base_url + path,
            params=params,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def _parse(self, data):
        """Return (subtitles, metadata). Handles v2 error and success shapes."""
        if not isinstance(data, dict):
            return [], []
        if "error" in data:
            err = data["error"]
            self.console.print(
                f"[bold red]SubDL API error: {err.get('message', err)}[/]"
            )
            return [], []
        subtitles = data.get("subtitles", []) or []
        metadata = data.get("results", []) or []
        return subtitles, metadata

    def _standardize(self, subtitles):
        standardized = [
            self.subtitle_utils.standardize_subtitle_object(sub, "subdl")
            for sub in subtitles
        ]
        return [s for s in standardized if s]

    def search(
        self,
        file_name="",
        film_name="",
        imdb_id="",
        tmdb_id="",
        sd_id="",
        languages="en",
        season=None,
        episode=None,
        full_season=False,
        type="",
        unpack=True,
    ) -> SearchResult:
        """Search subtitles via /subtitles/search. Accepts any one identifier."""
        params = {"languages": languages}
        if file_name:
            params["file_name"] = file_name
        if film_name:
            params["film_name"] = film_name
        if imdb_id:
            params["imdb_id"] = imdb_id
        if tmdb_id:
            params["tmdb_id"] = tmdb_id
        if sd_id:
            params["sd_id"] = sd_id
        if type:
            params["type"] = type
        if season is not None:
            params["season"] = season
        if episode is not None:
            params["episode"] = episode
        if full_season:
            params["full_season"] = 1
        if unpack:
            params["unpack"] = 1

        try:
            data = self._request("/subtitles/search", params)
            subtitles, metadata = self._parse(data)
            standardized = self._standardize(subtitles)
            if standardized:
                self.console.print(f"[green]Found {len(standardized)} subtitles[/green]")
            self.standardize_subtitle_objects = standardized
            return SearchResult(subtitles=standardized, metadata_results=metadata)
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubDL API request: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])
        except (KeyError, ValueError) as e:
            self.console.print(f"[bold red]Error decoding SubDL API response: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])
```

- [ ] **Step 3: Rewrite `download_single_subtitle` (single-file first, zip fallback)**

Replace the entire `download_single_subtitle` method (`library/SubDL.py:141-289`) with:

```python
    def _select_unpack_file(self, attrs, video_season, video_episode, is_movie):
        """Pick the best single-file URL from unpack_files. Returns (url, format) or (None, None)."""
        unpack_files = attrs.get("unpack_files") or []
        if not unpack_files:
            return None, None
        if is_movie:
            chosen = unpack_files[0]
        else:
            chosen = next(
                (f for f in unpack_files
                 if f.get("season") == video_season and f.get("episode") == video_episode),
                None,
            )
            if chosen is None:
                chosen = next(
                    (f for f in unpack_files if f.get("episode") == video_episode), None
                )
            if chosen is None:
                chosen = unpack_files[0]
        return chosen.get("url"), chosen.get("format", "srt")

    def _decode_bytes(self, content):
        for encoding in ("utf-8", "utf-16", "cp1252", "iso-8859-1", "latin1"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="replace")

    def _target_subtitle_name(self, video_input_path, language_choice, ext):
        if language_choice:
            return f"{video_input_path.stem}.{language_choice}{ext}"
        return f"{video_input_path.stem}{ext}"

    def _download_single_file(self, rel_url, fmt, video_input_path, language_choice):
        abs_url = self.download_base_url + rel_url
        response = requests.get(abs_url, timeout=10)
        response.raise_for_status()
        ext = f".{fmt}" if fmt in ("srt", "ass", "vtt") else ".srt"
        target_filename = self._target_subtitle_name(video_input_path, language_choice, ext)
        target_path = video_input_path.parent / target_filename
        decoded = self._decode_bytes(response.content)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(decoded)
        self.console.print(
            f"[green]Subtitle downloaded and saved as: {target_filename}[/green]"
        )
        return target_path

    def _download_zip(
        self, rel_url, video_input_path, language_choice, video_season, video_episode, is_movie
    ):
        abs_url = self.download_base_url + rel_url
        response = requests.get(abs_url, stream=True, timeout=10)
        response.raise_for_status()
        zip_path = video_input_path.with_suffix(".zip")
        with open(zip_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        if language_choice:
            subtitle_filename = f"{video_input_path.stem}.{language_choice}.ass"
            fallback_filename = f"{video_input_path.stem}.{language_choice}.srt"
        else:
            subtitle_filename = f"{video_input_path.stem}.ass"
            fallback_filename = f"{video_input_path.stem}.srt"

        if not is_movie and (video_season is None or video_episode is None):
            self.console.print(
                "[bold red]Error: Could not extract season/episode from video filename[/]"
            )
            zip_path.unlink(missing_ok=True)
            return None

        selected_subtitle_path = None
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                extracted_files = zip_ref.namelist()
                ass_files = [f for f in extracted_files if f.endswith(".ass")]
                srt_files = [f for f in extracted_files if f.endswith(".srt")]

                if not ass_files and not srt_files:
                    self.console.print(
                        "[bold red]Error: No .ass or .srt subtitle files found in the archive.[/]"
                    )
                    return None

                if is_movie:
                    matching_subtitle = (ass_files + srt_files)[0]
                else:
                    matching_subtitle = None
                    for subtitle_file in ass_files + srt_files:
                        sub_season, sub_episode = (
                            self.subtitle_utils.extract_season_and_episode(subtitle_file)
                        )
                        if sub_season == video_season and sub_episode == video_episode:
                            matching_subtitle = subtitle_file
                            break

                for subtitle_file in ass_files + srt_files:
                    try:
                        with zip_ref.open(subtitle_file) as source:
                            decoded_content = self._decode_bytes(source.read())

                        if subtitle_file == matching_subtitle:
                            target_filename = (
                                subtitle_filename if subtitle_file.endswith(".ass") else fallback_filename
                            )
                            selected_subtitle_path = video_input_path.parent / target_filename
                        else:
                            original_name = Path(subtitle_file).stem
                            extension = Path(subtitle_file).suffix
                            target_filename = f"{original_name}.{language_choice}{extension}"

                        target_path = video_input_path.parent / target_filename
                        with open(target_path, "w", encoding="utf-8") as target:
                            target.write(decoded_content)
                        self.console.print(
                            f"[green]Subtitle extracted and saved as: {target_filename}[/green]"
                        )
                    except Exception as e:
                        self.console.print(
                            f"[bold red]Error processing subtitle file {subtitle_file}: {e}[/]"
                        )
        finally:
            zip_path.unlink(missing_ok=True)

        if selected_subtitle_path is None:
            self.console.print(
                f"[bold yellow]Warning: Could not find matching episode "
                f"(S{video_season:02d}E{video_episode:02d}) in the subtitle pack[/]"
            )
        return selected_subtitle_path

    def download_single_subtitle(self, subtitle, video_input_path, language_choice=""):
        """Download one subtitle. Prefers an unpacked single file; falls back to the zip archive."""
        attrs = subtitle.get("attributes", {}) if isinstance(subtitle, dict) else {}
        try:
            video_season, video_episode = self.subtitle_utils.extract_season_and_episode(
                str(video_input_path)
            )
            is_movie = video_season is None and video_episode is None

            single_url, single_format = self._select_unpack_file(
                attrs, video_season, video_episode, is_movie
            )
            if single_url:
                return self._download_single_file(
                    single_url, single_format, video_input_path, language_choice
                )

            zip_url = attrs.get("url", "")
            if not zip_url:
                self.console.print("[bold red]Error: subtitle has no download url.[/]")
                return None
            return self._download_zip(
                zip_url, video_input_path, language_choice,
                video_season, video_episode, is_movie,
            )
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error downloading subtitle: {e}[/]")
            return None
        except zipfile.BadZipFile:
            self.console.print(
                "[bold red]Error: Downloaded file is not a valid ZIP.[/]"
            )
            return None
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error: {e}[/]")
            return None
```

- [ ] **Step 4: Update the caller in `process_media_file`**

The call at `library/SubDL.py:387-389` passes `selected_sub["id"]`. Change it to pass the whole subtitle dict:

```python
            subtitle_path = self.download_single_subtitle(
                selected_sub, path, language_choice
            )
```

- [ ] **Step 5: Live-verify search on v2**

Run:

```bash
python - <<'PY'
import yaml
from library.SubDL import SubDL
c = yaml.safe_load(open('config.yaml'))
s = SubDL(c['subdl']['api_key'])
r = s.search(imdb_id='tt15239678', languages='en')
print('subtitles:', len(r.subtitles), 'metadata:', len(r.metadata_results))
print('keys:', sorted(r.subtitles[0]['attributes'].keys()) if r.subtitles else None)
print('has unpack_files:', any(r.subtitles[0]['attributes'].get('unpack_files')) if r.subtitles else None)
PY
```

Expected: `subtitles:` a positive number, `metadata:` ≥ 1, `keys` includes `unpack_files`, and `has unpack_files: True` for at least some results.

- [ ] **Step 6: Live-verify a single-file download**

Run:

```bash
python - <<'PY'
import yaml, tempfile
from pathlib import Path
from library.SubDL import SubDL
c = yaml.safe_load(open('config.yaml'))
s = SubDL(c['subdl']['api_key'])
res = s.search(imdb_id='tt15239678', languages='en')
assert res.subtitles, 'no subtitles returned'
sub = next((x for x in res.subtitles if x['attributes'].get('unpack_files')), res.subtitles[0])
with tempfile.TemporaryDirectory() as d:
    vp = Path(d) / 'Dune.Part.Two.2024.mkv'
    vp.write_bytes(b'')
    out = s.download_single_subtitle(sub, vp, 'en')
    print('downloaded:', out.name if out else None,
          'size:', out.stat().st_size if out and out.exists() else 0)
PY
```

Expected: prints a filename like `Dune.Part.Two.2024.en.srt` with a non-zero size (this consumes 1 of the 50 daily downloads).

- [ ] **Step 7: Commit (with user approval)**

```bash
git add library/SubDL.py
git commit -m "Migrate SubDL search and download to v2 API (Bearer auth, single-file downloads)"
```

---

## Task 3: Enrich search — filename search, season/episode precision, candidate gathering

Add the new `/files/search` source, wire `season`/`episode` into the TV search, move hearing-impaired filtering client-side, and extract a `_gather_candidates` helper so `process_media_file` shrinks.

**Files:**
- Modify: `library/SubDL.py` — add `filename_search` and `movie_search` methods (after `search`); add `_gather_candidates`; rewrite the candidate-gathering section of `process_media_file` (`library/SubDL.py:291-372`).

**Interfaces:**
- Consumes: Task 2's `_request`, `_parse`, `_standardize`, `search`, `download_single_subtitle`.
- Produces:
  - `filename_search(self, filename, languages="en", subs_per_page=30) -> SearchResult`
  - `movie_search(self, q, type="", limit=10) -> list[dict]`
  - `_gather_candidates(self, path, language) -> list[dict]` (deduped standardized subtitles)

- [ ] **Step 1: Add `filename_search` and `movie_search`**

Insert these two methods immediately after the `search` method in `library/SubDL.py`:

```python
    def filename_search(self, filename, languages="en", subs_per_page=30) -> SearchResult:
        """Search by release filename via /files/search. Returns matched title + its subtitles."""
        params = {
            "filename": filename,
            "languages": languages,
            "subs_per_page": subs_per_page,
        }
        try:
            data = self._request("/files/search", params)
            subtitles, metadata = self._parse(data)
            standardized = self._standardize(subtitles)
            return SearchResult(subtitles=standardized, metadata_results=metadata)
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubDL filename search: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])
        except (KeyError, ValueError) as e:
            self.console.print(f"[bold red]Error decoding SubDL filename search response: {e}[/]")
            return SearchResult(subtitles=[], metadata_results=[])

    def movie_search(self, q, type="", limit=10):
        """Resolve a title/name to sd_id/imdb_id/tmdb_id via /movies/search. Returns the results list."""
        params = {"q": q, "limit": limit}
        if type:
            params["type"] = type
        try:
            data = self._request("/movies/search", params)
            _, metadata = self._parse(data)
            return metadata
        except requests.exceptions.RequestException as e:
            self.console.print(f"[bold red]Error during SubDL movie search: {e}[/]")
            return []
        except (KeyError, ValueError) as e:
            self.console.print(f"[bold red]Error decoding SubDL movie search response: {e}[/]")
            return []
```

- [ ] **Step 2: Add `_gather_candidates`**

Insert this method after `movie_search`:

```python
    def _gather_candidates(self, path, language):
        """Run all search sources, merge, filter, and dedupe into one candidate list."""
        media_name = path.stem
        subs = []
        metadata = []

        def add(result):
            subs.extend(result.subtitles)
            metadata.extend(result.metadata_results)

        # 1) NEW: purpose-built filename search (also resolves the title id)
        add(self.filename_search(filename=media_name, languages=language))

        # 2) by filename (legacy)
        add(self.search(file_name=media_name, languages=language))

        # 3) by series name
        series_match = re.search(r"(.+?)(?:\s-\sS\d{2}E\d{2}|\s-\s\d{4})", media_name)
        if series_match:
            add(self.search(film_name=series_match.group(1), languages=language))

        # resolve season/episode once for the precise TV pass
        video_season, video_episode = self.subtitle_utils.extract_season_and_episode(media_name)

        # 4) by IMDb ids resolved from any metadata, narrowed by season/episode for TV
        imdb_ids = {m["imdb_id"] for m in metadata if m.get("imdb_id")}
        for imdb_id in imdb_ids:
            add(self.search(
                imdb_id=imdb_id, languages=language,
                season=video_season, episode=video_episode,
            ))

        # 5) by alternate filename variants
        for term in (self.subtitle_utils.get_alternate_names(media_name) or []):
            add(self.search(file_name=term, languages=language))

        # 6) last-resort title resolution if nothing matched a title id
        if not imdb_ids:
            for title in self.movie_search(media_name):
                if title.get("imdb_id"):
                    add(self.search(
                        imdb_id=title["imdb_id"], languages=language,
                        season=video_season, episode=video_episode,
                    ))

        # hearing-impaired preference (v2 has no hi param; filter client-side)
        if self.hearing_impaired:
            subs = [s for s in subs if s.get("attributes", {}).get("hi")]

        # dedupe by subtitle id
        return list({s["id"]: s for s in subs if s.get("id")}.values())
```

- [ ] **Step 3: Replace the candidate-gathering block in `process_media_file`**

In `process_media_file`, the lines before the search block (293-299) already set `path`, `media_name`, and print "Searching for subtitles for …" — leave those untouched. Replace lines `library/SubDL.py:300-372` — from the `subtitle_path = Path(path.parent, ...)` assignment through the "Total unique results" rprint (i.e. the whole inline 4-pass search + dedupe) — with:

```python
            subtitles_list = self._gather_candidates(path, language_choice)
            if not subtitles_list:
                rprint(f"[red]No subtitles found for {media_name}[/red]")
                return False
            rprint(
                f"[green]Total unique results after all searches: {len(subtitles_list)}[/green]"
            )
```

Leave the rest of `process_media_file` (auto/manual select, download, clean, sync) unchanged — it already calls `download_single_subtitle(selected_sub, path, language_choice)` from Task 2. The early `subtitle_path = Path(path.parent, ...)` assignment being removed is safe: it was only ever overwritten by the `subtitle_path =` result of `download_single_subtitle` further down, which is what the later `clean_subtitles`/`sync_subtitles` calls use.

- [ ] **Step 4: Live-verify candidate gathering for a TV episode**

Run:

```bash
python - <<'PY'
import yaml
from pathlib import Path
from library.SubDL import SubDL
c = yaml.safe_load(open('config.yaml'))
s = SubDL(c['subdl']['api_key'])
cands = s._gather_candidates(Path('The.Flash.2014.S01E01.1080p.BluRay.x264.mkv'), 'en')
print('candidates:', len(cands))
print('top release:', cands[0]['attributes']['release'] if cands else None)
print('any with unpack_files:', any(c['attributes'].get('unpack_files') for c in cands))
PY
```

Expected: `candidates:` a positive number; `top release:` a string; `any with unpack_files:` True or False (either is acceptable — the precise season/episode pass may return episode-specific single files).

- [ ] **Step 5: Live-verify an end-to-end TV run (optional, if a sample video exists)**

If there is a real `.mkv`/`.mp4` TV episode on disk, run the tool against it and confirm it finds, selects, and downloads a subtitle:

```bash
python download_subs.py <path-to-a-tv-episode.mkv>
```

Expected: prints search progress, selects a subtitle (auto or manual), and writes a `.en.srt`/`.ass` next to the video.

- [ ] **Step 6: Commit (with user approval)**

```bash
git add library/SubDL.py
git commit -m "Enrich SubDL search with /files/search, season/episode precision, and candidate gathering"
```

---

## Task 4: Health-check → quota-free /api/v2/me with Bearer

**Files:**
- Modify: `download_subs.py:85-87` (the subdl availability check inside `_choose_backend`) and `download_subs.py:105-110` (`_check_api_availability`)

**Interfaces:**
- Consumes: `self.config["subdl"]["api_key"]`.
- Produces: `_check_api_availability(self, url, headers=None) -> bool`; the `AUTO` branch pings `https://api.subdl.com/api/v2/me` with a Bearer header.

- [ ] **Step 1: Allow headers in `_check_api_availability`**

Replace `download_subs.py:105-110` with:

```python
    def _check_api_availability(self, url, headers=None) -> bool:
        try:
            response = requests.get(url, timeout=5, headers=headers)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
```

- [ ] **Step 2: Point the SubDL health-check at `/api/v2/me` with Bearer**

Replace `download_subs.py:85-87` with:

```python
            subdl_available = self._check_api_availability(
                "https://api.subdl.com/api/v2/me",
                headers={"Authorization": f"Bearer {self.config['subdl']['api_key']}"},
            )
```

- [ ] **Step 3: Live-verify the health-check**

Run:

```bash
python - <<'PY'
import yaml
from download_subs import SubtitleDownloader, SubtitleBackend
d = SubtitleDownloader('config.yaml')
ok = d._check_api_availability(
    'https://api.subdl.com/api/v2/me',
    headers={'Authorization': f"Bearer {d.config['subdl']['api_key']}"},
)
print('subdl available:', ok)
chosen = d._choose_backend([], SubtitleBackend.AUTO)
print('AUTO chosen backend:', chosen)
PY
```

Expected: `subdl available: True`, and `AUTO chosen backend:` one of the `SubtitleBackend` members (it returns `OPENSUBTITLES` when both are up, which is the existing behavior — the point is that SubDL is now correctly detected as available).

- [ ] **Step 4: Commit (with user approval)**

```bash
git add download_subs.py
git commit -m "Point SubDL AUTO health-check at quota-free v2 /me endpoint"
```

---

## Verification (whole-plan)

After all four tasks:

- [ ] `python -m unittest test_subtitle_utils -v` — all tests pass.
- [ ] `python download_subs.py <a-movie-file>` — searches (v2), selects, downloads a single-file `.srt`.
- [ ] `python download_subs.py <a-tv-episode-file>` — searches with season/episode precision, downloads the correct episode.
- [ ] With `general.preferred_backend: auto` in `config.yaml`, the tool picks a working backend without error.
