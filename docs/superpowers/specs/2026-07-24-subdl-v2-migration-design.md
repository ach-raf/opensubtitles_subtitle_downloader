# SubDL v2 API Migration — Design

**Date:** 2026-07-24
**Status:** Approved (pending implementation plan)
**Scope:** Core search + download only. No AI features (translation / transcription / AI filename search are Pro-only and out of scope).

## Goal

Migrate the SubDL backend ([library/SubDL.py](../../../library/SubDL.py)) from the legacy v1 API to the new v2 API, take advantage of v2's cleaner endpoints to enrich search results (notably the filename search), and end with cleaner code — **without dropping any existing features**. The user's directive: "clean means clean code, not less features." Approach chosen: **C — additive** (keep all current search strategies, add the new filename search, refactor for clarity).

Reference: https://subdl.com/developers

## Current state (v1)

- Single endpoint `GET https://api.subdl.com/api/v1/subtitles`, query-param auth `?api_key=`.
- `process_media_file` runs up to **4 search passes** per video and merges the results:
  1. by filename stem (`file_name=media_name`)
  2. by regex-extracted series name (`film_name=series_name`)
  3. by IMDb id scraped from pass results' metadata (`imdb_id=`)
  4. by alternate filename variants from `subtitle_utils.get_alternate_names` (`file_name=`)
- Season/episode is resolved **only after download**, by scanning inside the downloaded zip.
- Downloads assume a zip from `https://dl.subdl.com/subtitle/<id>` and pick the matching SxxExx file from inside.
- `search()` is one method taking ~13 params; `SubDL.py` is ~460 lines with most logic inline in `process_media_file`.
- `AUTO` backend selection in [download_subs.py](../../../download_subs.py) health-checks the v1 URL.
- Standardized subtitle object hardcodes `download_count=0`, `author="Unknown"`; no rich metadata for ranking — selection relies on filename fuzzy matching (`subtitle_utils.score_subtitle`).

## Verified v2 response shapes (probed read-only against the live API)

All subtitle search endpoints return subtitles with these fields (verified):

```json
{
  "release_name": "Dune.Part.Two.2024.1080p.BluRay.x264-ROEN",
  "name": "Dune Part Two.zip",
  "lang": "English",
  "author": "lumenscsc",
  "url": "/subtitle/3458138-8381001.zip?api_key=...",
  "subtitlePage": "/s/info/j9avlHZSIr",
  "season": 0, "episode": null,
  "language": "EN",
  "framerate": 2, "fps": "23.976",
  "hi": false,
  "full_season": false,
  "unpack_files": [
    {
      "file_n_id": "Ldzyzv9CpC",
      "name": "Dune Part Two.srt",
      "release_name": "Dune Part Two",
      "season": 0, "episode": 0,
      "language": "EN", "hi": false,
      "format": "srt", "size": 81589, "md5": "...",
      "url": "/subtitle/j9avlHZSIrI/Ldzyzv9CpC?api_key=..."
    }
  ]
}
```

Endpoint-specific wrappers:

- `GET /api/v2/movies/search` → `{"results":[{sd_id, type, name, original_name, year, imdb_id, tmdb_id, poster_url, subtitles_count, url}]}` — **no `status` field**. Note `sd_id` is a string like `"sd1300026"`.
- `GET /api/v2/files/search` → `{"status":true, "results":[{sd_id, type, name, imdb_id, tmdb_id, year, slug}], "subtitles":[...], "totalPages", "currentPage"}`. `sd_id` here is an **integer** (`1300026`). For `The.Flash.2014.S01E01...mkv` it correctly resolved the title to tt3107288 but returned season packs, not S01E01 → its real value is **title resolution**; episode-exact subs still come from `/subtitles/search` with `season`/`episode`.
- `GET /api/v2/subtitles/search` (with `unpack=1`) → `{"status":true, "results":[<title>], "subtitles":[...]}`. This endpoint accepts `sd_id | imdb_id | tmdb_id | film_name | file_name` as the identifier, so all current search passes map onto it.
- `GET /api/v2/me` → plan + usage counters; **does not count against search quota** — ideal health check.

Key facts:
- The unified **error** shape is `{"error":{"code","message","docs_url"}}`.
- Subtitle `url` fields carry an embedded `?api_key=`, so download links remain self-authenticating.
- v2 `/subtitles/search` does **not** expose `hi`, `comment`, `releases`, or `subs_per_page` query params (v1 did). It paginates via `totalPages`/`currentPage` instead. Hearing-impaired filtering must move client-side.

## Design

### 1. Auth & base URL
- All calls use `Authorization: Bearer <key>` header (key stays at `config["subdl"]["api_key"]`).
- Base URL → `https://api.subdl.com/api/v2`.
- Download `url` fields are fetched directly (they already carry `?api_key=`).

### 2. Search — three focused methods (replaces the one fat `search()`)

Nothing is dropped; the existing 4 passes all route through `/subtitles/search`, which accepts every identifier type.

- `search(identifiers, languages, season=None, episode=None, full_season=False, type=None, unpack=True)` → `/subtitles/search`
  - `identifiers` is a dict carrying one of `sd_id`/`imdb_id`/`tmdb_id`/`film_name`/`file_name`.
  - The 4 existing passes become 4 calls with different identifiers:
    1. `file_name=<video stem>`
    2. `film_name=<series name>`
    3. `imdb_id=<each id from prior metadata>`
    4. `file_name=<each alternate variant>`
- `filename_search(filename, languages, subs_per_page=30)` → `/files/search` — **the new 5th source**. Its `subtitles` merge into the candidate pool, and the resolved title id feeds the precise pass below.
- `movie_search(q, type=None, limit=10)` → `/movies/search` — last-resort name→id resolver.

### 3. Enrichment — real season/episode narrowing
For TV, in addition to gathering candidates from all sources as today, fire a precise `search(imdb_id=<resolved id>, season=<S>, episode=<E>)` using the title id resolved by `filename_search` (and/or `movie_search`). Season/episode are parsed from the video filename via the existing `subtitle_utils.extract_season_and_episode`. The post-download zip selection is **kept** as a safety net — not removed.

### 4. Candidate gathering & selection
A new `_gather_candidates(media_path, language)` helper:
- Runs the 5 source passes (+ the precise season/episode pass for TV).
- Standardizes each result via `subtitle_utils.standardize_subtitle_object(sub, "subdl")` (updated — see §5).
- Merges and dedupes by subtitle id.
`process_media_file` shrinks to: `_gather_candidates` → `auto_select_subtitle`/`manual_select_subtitle` → `download_single_subtitle` → clean → optional sync. Existing fuzzy scoring (`score_subtitle`) keeps working because the standardized shape is preserved.

### 5. Response parsing & field mapping
A single `_parse(json)` helper:
- If `error` key present → raise/return a structured error (surface `code`/`message`, special-case `quota_exceeded`/rate-limit).
- Else success: read `subtitles` (list) and `results` (title metadata, for imdb/sd/tmdb ids). Tolerate missing `status` (`/movies/search` omits it).

v2 subtitle → standardized object mapping (verified against live data):

| v2 field | standardized |
|---|---|
| `url` (zip) | `id` (via updated `extract_subdl_subtitle_id`) + `attributes.url` |
| `release_name` | `attributes.release` |
| `language` (`"EN"`) | `attributes.language` (lowercased → `"en"`) |
| `hi`, `full_season`, `author`, `season`, `episode` | same-named attributes |
| **NEW** `unpack_files` (list) | `attributes.unpack_files` (raw list, for download-time episode picking) |

Defaults that remain (v2 doesn't expose them either): `download_count=0`, `ai_translated=False`, `machine_translated=False`, `moviehash_match=False`.

`standardize_subtitle_object` stays a pure, context-free field mapper: it stores the raw `unpack_files` list on the attribute dict. Picking the right file from that list requires the target season/episode, which only the download step has — so episode selection happens at download time, not during standardization. Selection-time scoring continues to use the subtitle-level `release`/`fps` fields it already uses.

`extract_subdl_subtitle_id` must strip the `?api_key=` query before splitting on `/` and removing `.zip`, since v2 urls look like `/subtitle/3458138-8381001.zip?api_key=...` (today's `parts[2].replace(".zip","")` would leave the query attached).

The downstream OpenSubtitles code and fuzzy scorer are untouched (standardized shape preserved; extra keys are additive).

### 6. Download — single-file first, zip for packs
- If the chosen subtitle has `attributes.single_file_url` (from `unpack_files`):
  - For TV, pick the `unpack_files` entry whose `season`/`episode` matches the target.
  - Download that url directly → **no zip, no in-zip episode scan**. Save as `.<lang>.<format>` (`.srt`/`.ass`).
- Else (season-pack zip, `full_season=true` with no usable unpack file): keep the **existing** zip download + in-zip SxxExx selection (feature preserved).

### 7. Clean-code refactor
Extract from the 460-line monolith:
- `_request(method, path, params)` — centralizes base URL, Bearer header, timeout (10s), and error parsing. Every endpoint call goes through it.
- `_gather_candidates(media_path, language)` — runs/merges/dedupes the passes (see §4).
- `search` / `filename_search` / `movie_search` — thin wrappers over `_request` + `_parse`.
No behavior is removed; `process_media_file` becomes a short, readable pipeline.

### 8. Health check, config, errors
- `download_subs.py` `AUTO` availability ping moves from the v1 URL to quota-free `GET /api/v2/me`.
- Config unchanged: `subdl.api_key` (now sent as Bearer), `hearing_impaired`.
- `hearing_impaired` filtering moves client-side. v1 sent `hi=1` only when the flag was True (and nothing when False, so both HI and non-HI came back); v2 has no `hi` query param but exposes `hi` per subtitle. Preserved behavior: when `hearing_impaired=True`, prefer candidates with `hi=True` during selection; when `False`, no filtering.
- Centralized error handling surfaces quota/rate-limit codes clearly to the user.

### 9. Tests
- Update `test_subtitle_utils.py` fixtures for the new field mapping (the v2 url-with-query in `extract_subdl_subtitle_id`, and any standardized-field changes). These fixtures are the only tests that touch the SubDL path today.
- Do **not** add new tests for `SubDL.py` and do **not** un-gitignore `test*.py` (per user choice).

## Files changed

- [library/SubDL.py](../../../library/SubDL.py) — main rewrite (auth, endpoints, search methods, parsing, download, refactor).
- [library/subtitle_utils.py](../../../library/subtitle_utils.py) — update `extract_subdl_subtitle_id` (query stripping) and the subdl branch of `standardize_subtitle_object` (new single-file fields).
- [download_subs.py](../../../download_subs.py) — `AUTO` health-check URL → `/api/v2/me`.
- [test_subtitle_utils.py](../../../test_subtitle_utils.py) — fixture updates.

## Open items to confirm at implementation start

1. **Download base host.** The `url` fields are relative paths (`/subtitle/...`). Confirm whether to prepend `https://api.subdl.com` or `https://dl.subdl.com` with a single HEAD request (the current code uses `dl.subdl.com`). Single connectivity check; will not consume the download quota meaningfully.
2. **`unpack_files` TV coverage.** Confirm that for a real TV episode the precise `/subtitles/search?imdb_id=…&season=&episode=&unpack=1` returns `unpack_files` with episode-matching single-file entries (one live check against a known show).
3. **Pagination.** v2 uses `totalPages`/`currentPage`. Decide whether to fetch beyond page 1 when the first page lacks a strong match — default to page 1 only for v1 parity, revisit if selection quality drops.

## Out of scope

- AI translation / transcription / AI filename search (Pro-only).
- `format=file` download endpoint (`/api/v2/subtitles/{nId}/download?format=file`) — we use the `unpack_files` urls returned inline by `unpack=1` instead, which is simpler and avoids a second round trip.
- Changes to the OpenSubtitles backend.
- New CLI flags (no `--lang`/`--imdb`/`--backend` flags today; not adding).
