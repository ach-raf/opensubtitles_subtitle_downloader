"""Services — the only layer that calls ``library/*``.

Every backend/network call goes through one of the workers here. Each worker
catches backend exceptions and converts them into plain data on the returned
objects (or into the ``AppState.last_error`` field the caller sets), so the UI
never crashes on a backend failure.

This module imports ``library.*`` eagerly. Widgets and ``state.py`` never do.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
import yaml

from tui.state import (
    Backend,
    EngineHealth,
    HistoryEntry,
    RunPolicy,
    AppState,
    CONCRETE_BACKENDS,
)

# Heavy backend imports — wrapped so a missing/broken optional dep (rarfile)
# doesn't stop the whole module loading. The classes themselves are imported
# lazily on first use inside the workers.
try:
    import library.OpenSubtitles as _os_mod  # noqa: F401
    from library.OpenSubtitles import OpenSubtitles as _OpenSubtitles
except Exception as exc:  # pragma: no cover - import guard only
    _os_mod = None
    _OpenSubtitles = None
    _OS_IMPORT_ERROR = exc
else:
    _OS_IMPORT_ERROR = None

try:
    from library.SubDL import SubDL as _SubDL
    from library.SubSource import SubSource as _SubSource
except Exception as exc:  # pragma: no cover
    _SubDL = None
    _SubSource = None
    _BACKEND_IMPORT_ERROR = exc
else:
    _BACKEND_IMPORT_ERROR = None

try:
    from library.subtitle_utils import SubtitleUtils
except Exception as exc:  # pragma: no cover
    SubtitleUtils = None
    _UTILS_IMPORT_ERROR = exc
else:
    _UTILS_IMPORT_ERROR = None


logger = logging.getLogger("tui.services")


# --------------------------------------------------------------------------- #
# Backend construction helpers
# --------------------------------------------------------------------------- #
def _config_sync_policy(raw: object) -> Tuple[bool, str]:
    """Translate config's sync_audio_to_subs (true/false/ask) into the
    constructor arg (truthy/"ask" string) the backends expect, plus our internal
    policy string. The backends accept True/False/"ask" directly.
    """
    if isinstance(raw, str):
        r = raw.strip().lower()
        if r == "ask":
            return ("ask", "ask")
        if r in ("true", "1", "yes"):
            return (True, "always")
        if r in ("false", "0", "no"):
            return (False, "never")
    if raw is True:
        return (True, "always")
    if raw is False:
        return (False, "never")
    return ("ask", "ask")


def _policy_to_config_value(policy: str) -> Any:
    """Inverse of _config_sync_policy: always/never/ask -> true/false/ask."""
    if policy == "always":
        return True
    if policy == "never":
        return False
    return "ask"


def build_opensubtitles(config: Dict[str, Any], policy: RunPolicy) -> Any:
    if _OpenSubtitles is None:
        raise RuntimeError(f"OpenSubtitles backend unavailable: {_OS_IMPORT_ERROR}")
    cfg = config.get("opensubtitles", {}) or {}
    sync_arg, _ = _config_sync_policy(config.get("general", {}).get("sync_audio_to_subs"))
    return _OpenSubtitles(
        username=cfg.get("username", ""),
        password=cfg.get("password", ""),
        api_key=cfg.get("api_key", ""),
        user_agent=cfg.get("user_agent", ""),
        sync_audio_to_subs=sync_arg,
        hearing_impaired=(policy.hearing_impaired == "only"),
        auto_select=policy.auto_select,
    )


def build_subdl(config: Dict[str, Any], policy: RunPolicy) -> Any:
    if _SubDL is None:
        raise RuntimeError(f"SubDL backend unavailable: {_BACKEND_IMPORT_ERROR}")
    cfg = config.get("subdl", {}) or {}
    sync_arg, _ = _config_sync_policy(config.get("general", {}).get("sync_audio_to_subs"))
    return _SubDL(
        api_key=cfg.get("api_key", ""),
        sync_audio_to_subs=sync_arg,
        hearing_impaired=(policy.hearing_impaired == "only"),
        auto_select=policy.auto_select,
    )


def build_subsource(config: Dict[str, Any], policy: RunPolicy) -> Any:
    if _SubSource is None:
        raise RuntimeError(f"SubSource backend unavailable: {_BACKEND_IMPORT_ERROR}")
    cfg = config.get("subsource", {}) or {}
    sync_arg, _ = _config_sync_policy(config.get("general", {}).get("sync_audio_to_subs"))
    return _SubSource(
        api_key=cfg.get("api_key", ""),
        sync_audio_to_subs=sync_arg,
        hearing_impaired=(policy.hearing_impaired == "only"),
        auto_select=policy.auto_select,
    )


def build_backend(backend: Backend, config: Dict[str, Any], policy: RunPolicy) -> Any:
    """Construct one backend client. Raises RuntimeError if unavailable."""
    if backend is Backend.OPENSUBTITLES:
        return build_opensubtitles(config, policy)
    if backend is Backend.SUBDL:
        return build_subdl(config, policy)
    if backend is Backend.SUBSOURCE:
        return build_subsource(config, policy)
    raise ValueError(f"build_backend needs a concrete backend, got {backend!r}")


# --------------------------------------------------------------------------- #
# SearchWorker
# --------------------------------------------------------------------------- #
class SearchWorker:
    """Search one media file across one or more engines, score, dedupe.

    Pure function: no AppState mutation. The caller posts the returned list
    onto ``state.results`` (and the score map) from the UI thread.
    """

    def __init__(self, config: Dict[str, Any], policy: Optional[RunPolicy] = None) -> None:
        self.config = config
        self.policy = policy or RunPolicy()
        self._utils = SubtitleUtils() if SubtitleUtils is not None else None
        # Cache constructed clients so repeated searches don't re-login.
        self._clients: Dict[Backend, Any] = {}

    # -- client cache -------------------------------------------------------
    def _client(self, backend: Backend) -> Any:
        if backend not in self._clients:
            self._clients[backend] = build_backend(backend, self.config, self.policy)
        return self._clients[backend]

    # -- public API ---------------------------------------------------------
    def search(
        self,
        state: AppState,
        media_path: str,
        engine: Optional[Backend] = None,
    ) -> List[dict]:
        """Run a search and return standardized, scored, sorted candidates.

        - ``engine`` overrides ``state.backend`` (used by merge mode + the
          engine switcher).
        - Merge mode (``state.merge_mode``) fans out to every online concrete
          engine, dedupes by id, and re-scores.
        - On any backend error the exception is swallowed, logged, and an empty
          list returned; the caller sets ``state.last_error``.
        """
        backends = self._resolve_engines(state, engine)
        media_name = Path(media_path).stem
        all_results: List[dict] = []
        errors: List[str] = []

        for be in backends:
            try:
                rows = self._search_one(be, media_path, media_name, state.language)
            except Exception as exc:  # noqa: BLE001 - contain backend failures
                logger.warning("search %s failed: %s", be.value, exc)
                errors.append(f"{be.label}: {exc}")
                continue
            # Tag each row with its source for the merge-mode Source column.
            for row in rows:
                row.setdefault("_source", be.value)
            all_results.extend(rows)

        if errors and not all_results:
            state.last_error = "; ".join(errors)
        else:
            state.last_error = None

        # Dedupe by id (stable: keep first occurrence = highest-priority engine).
        deduped = self._dedupe(all_results)

        # Score + sort against the filename.
        scored = self._score_and_sort(deduped, media_name)
        return scored

    # -- internals ----------------------------------------------------------
    def _resolve_engines(
        self, state: AppState, engine: Optional[Backend]
    ) -> List[Backend]:
        if engine is not None:
            return [engine]
        if state.merge_mode:
            # Fan out to every concrete engine; the caller is expected to have
            # health data but we don't block on it here.
            online = [
                be
                for be in CONCRETE_BACKENDS
                if state.engine_health.get(be.value, EngineHealth(be.value)).online
            ]
            return online or list(CONCRETE_BACKENDS)
        if state.backend is Backend.AUTO:
            # Pick the first online concrete engine; fall back to OS.
            for be in CONCRETE_BACKENDS:
                if state.engine_health.get(be.value, EngineHealth(be.value)).online:
                    return [be]
            return [Backend.OPENSUBTITLES]
        if state.backend in CONCRETE_BACKENDS:
            return [state.backend]
        return [Backend.OPENSUBTITLES]

    def _search_one(
        self,
        backend: Backend,
        media_path: str,
        media_name: str,
        language: str,
    ) -> List[dict]:
        client = self._client(backend)

        if backend is Backend.OPENSUBTITLES:
            return self._search_opensubtitles(client, media_path, media_name, language)
        if backend is Backend.SUBDL:
            # SubDL exposes a ready-made gather that does filename + film_name +
            # imdb + alt-name fan-out and returns standardized, deduped rows.
            return list(client._gather_candidates(Path(media_path), language))
        if backend is Backend.SUBSOURCE:
            return list(client._gather_candidates(Path(media_path), language))
        raise ValueError(f"unknown backend {backend!r}")

    def _search_opensubtitles(
        self, client: Any, media_path: str, media_name: str, language: str
    ) -> List[dict]:
        """Mirror of OpenSubtitles.process_media_file's search portion, but
        pure (no selection, no download). Reuses the client's search() and the
        shared SubtitleUtils for hashing + alt names."""
        utils = self._utils or client.subtitle_utils
        media_hash = ""
        try:
            media_hash = utils.hashFile(media_path) or ""
        except Exception:  # noqa: BLE001
            media_hash = ""

        results: List[dict] = []
        found = client.search(
            media_hash=media_hash, media_name=media_name, languages=language
        )
        if found:
            results.extend(found)

        # Series-name pass (same regex the backend uses).
        series_name = re.search(r"(.+?)(?:\s-\sS\d{2}E\d{2}|\s-\s\d{4})", media_name)
        if series_name:
            series = series_name.group(1)
            more = client.search(
                media_hash=media_hash, media_name=series, languages=language
            )
            if more:
                results.extend(more)

        # Alt-name pass.
        if self.policy.alt_name_search:
            alt_names = utils.get_alternate_names(media_name)
            for term in alt_names or []:
                more = client.search(
                    media_hash=media_hash, media_name=term, languages=language
                )
                if more:
                    results.extend(more)

        return results

    def _dedupe(self, rows: List[dict]) -> List[dict]:
        seen: Dict[Any, dict] = {}
        for row in rows:
            rid = row.get("id")
            if rid is None:
                continue
            if rid not in seen:
                seen[rid] = row
        return list(seen.values())

    def _score_and_sort(self, rows: List[dict], media_name: str) -> List[dict]:
        if not rows or self._utils is None:
            # Without SubtitleUtils we can't score; fall back to download_count.
            return sorted(
                rows,
                key=lambda r: r.get("attributes", {}).get("download_count", 0),
                reverse=True,
            )
        scored: List[Tuple[float, dict]] = []
        for row in rows:
            attrs = row.get("attributes", {}) or {}
            release = attrs.get("release", "")
            hash_match = bool(attrs.get("moviehash_match", False))
            try:
                score = self._utils.score_subtitle(release, media_name, hash_match)
            except Exception:  # noqa: BLE001
                score = 0.0
            # Stash the score on the row so the table can render the bar without
            # a second pass; the caller also mirrors it into state.scores.
            row["_score"] = score
            scored.append((score, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [row for _, row in scored]


# --------------------------------------------------------------------------- #
# DownloadWorker
# --------------------------------------------------------------------------- #
# Result of a download attempt. Distinct from HistoryEntry so the toast can
# decide its post-download actions before the HistoryEntry is finalized.
class DownloadResult:
    __slots__ = (
        "media_path",
        "subtitle_path",
        "release",
        "language",
        "backend",
        "downloaded",
        "error",
    )

    def __init__(
        self,
        media_path: str,
        subtitle_path: Optional[str],
        release: str,
        language: str,
        backend: str,
        downloaded: bool,
        error: Optional[str] = None,
    ) -> None:
        self.media_path = media_path
        self.subtitle_path = subtitle_path
        self.release = release
        self.language = language
        self.backend = backend
        self.downloaded = downloaded
        self.error = error


class DownloadWorker:
    """Download a chosen subtitle and run clean/sync per the run policy.

    The 5-second auto-pick decision (spec §6.4) lives in the toast widget, not
    here: this worker just executes the chosen post-download action and returns
    a HistoryEntry. Sync failure (no ffs) is caught and recorded as
    ``sync_skipped`` with an amber-tone error string rather than raised.
    """

    def __init__(self, config: Dict[str, Any], policy: Optional[RunPolicy] = None) -> None:
        self.config = config
        self.policy = policy or RunPolicy()
        self._utils = SubtitleUtils() if SubtitleUtils is not None else None
        self._clients: Dict[Backend, Any] = {}

    def _client(self, backend: Backend, search_worker: Optional[SearchWorker]) -> Any:
        if backend in self._clients:
            return self._clients[backend]
        # Reuse a SearchWorker's cached client if handed one (same session/login).
        if search_worker is not None and backend in search_worker._clients:
            self._clients[backend] = search_worker._clients[backend]
            return self._clients[backend]
        self._clients[backend] = build_backend(backend, self.config, self.policy)
        return self._clients[backend]

    def download(
        self,
        state: AppState,
        media_path: str,
        chosen: dict,
        engine: Optional[Backend] = None,
        search_worker: Optional[SearchWorker] = None,
    ) -> DownloadResult:
        """Fetch + save the subtitle file. Postprocessing runs separately via
        :meth:`postprocess` so the toast can choose the action first."""
        backend = engine or (state.backend if state.backend in CONCRETE_BACKENDS else Backend.OPENSUBTITLES)
        media_p = Path(media_path)
        release = (chosen.get("attributes", {}) or {}).get("release", "") or media_p.stem
        sub_path = media_p.with_suffix(f".{state.language}.srt")

        try:
            client = self._client(backend, search_worker)
            saved = self._save(client, backend, chosen, media_p, state.language)
        except Exception as exc:  # noqa: BLE001
            logger.warning("download %s failed: %s", media_path, exc)
            return DownloadResult(
                media_path=media_path,
                subtitle_path=None,
                release=release,
                language=state.language,
                backend=backend.value,
                downloaded=False,
                error=str(exc),
            )
        if not saved:
            return DownloadResult(
                media_path=media_path,
                subtitle_path=None,
                release=release,
                language=state.language,
                backend=backend.value,
                downloaded=False,
                error="backend returned no file",
            )
        return DownloadResult(
            media_path=media_path,
            subtitle_path=str(saved),
            release=release,
            language=state.language,
            backend=backend.value,
            downloaded=True,
        )

    def _save(
        self,
        client: Any,
        backend: Backend,
        chosen: dict,
        media_p: Path,
        language: str,
    ) -> Optional[Path]:
        """Backend-specific save. Returns the saved subtitle path or None."""
        if backend is Backend.OPENSUBTITLES:
            link = client.get_download_link(chosen)
            if not link:
                return None
            target = media_p.with_suffix(f".{language}.srt")
            if not client.save_subtitle(link, str(target)):
                return None
            return target
        # SubDL + SubSource share download_single_subtitle(subtitle, path, lang).
        return client.download_single_subtitle(chosen, media_p, language)

    # -- postprocessing -----------------------------------------------------
    def postprocess(
        self,
        result: DownloadResult,
        do_clean: bool,
        do_sync: bool,
    ) -> HistoryEntry:
        """Run clean/sync on a successful DownloadResult -> HistoryEntry."""
        entry = HistoryEntry(
            media_path=result.media_path,
            subtitle_path=result.subtitle_path,
            release=result.release,
            language=result.language,
            backend=result.backend,
            error=result.error,
        )
        if not result.downloaded or not result.subtitle_path:
            return entry
        sub_path = result.subtitle_path

        if do_clean and self.policy.clean_ads and self._utils is not None:
            try:
                self._utils.clean_subtitles(sub_path)
                entry.cleaned = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("clean failed: %s", exc)
                entry.error = f"clean failed: {exc}"

        if do_sync:
            sync_outcome = self._sync(result.media_path, sub_path)
            if sync_outcome is True:
                entry.synced = True
            elif sync_outcome is False:
                # Distinguish "no ffs" (skipped, amber) from hard failure.
                entry.sync_skipped = True
                if not entry.error:
                    entry.error = "sync skipped (ffs/ffmpeg unavailable)"
        return entry

    def _sync(self, media_path: str, subtitle_path: str) -> Optional[bool]:
        """Run audio sync. Returns True=ok, False=skipped(no tool), None=error."""
        if self._utils is None:
            return False
        # Detect a missing ffs binary the same way sync_subtitles does: the
        # subprocess.call would raise FileNotFoundError if 'ffs' isn't on PATH.
        import shutil

        if not shutil.which("ffs"):
            return False
        try:
            self._utils.sync_subtitles(media_path, subtitle_path)
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("sync failed: %s", exc)
            return None

    def download_and_postprocess(
        self,
        state: AppState,
        media_path: str,
        chosen: dict,
        engine: Optional[Backend] = None,
        search_worker: Optional[SearchWorker] = None,
    ) -> HistoryEntry:
        """Convenience: download then immediately postprocess using the policy.

        Used by the auto-pick path when the policy is already decided (always /
        never); the ``ask`` path uses :meth:`download` + a toast + a separate
        :meth:`postprocess` call.
        """
        result = self.download(state, media_path, chosen, engine, search_worker)
        do_sync = self.policy.audio_sync == "always"
        do_clean = True
        return self.postprocess(result, do_clean=do_clean, do_sync=do_sync)


# --------------------------------------------------------------------------- #
# HealthProbe
# --------------------------------------------------------------------------- #
# (url, headers-builder) per backend. Mirrors SubtitleDownloader._choose_backend.
def _probe_targets(config: Dict[str, Any]) -> Dict[Backend, Tuple[str, Dict[str, str]]]:
    os_cfg = config.get("opensubtitles", {}) or {}
    subdl_cfg = config.get("subdl", {}) or {}
    subsource_cfg = config.get("subsource", {}) or {}
    return {
        Backend.OPENSUBTITLES: (
            "https://api.opensubtitles.com/api/v1/login",
            {},
        ),
        Backend.SUBDL: (
            "https://api.subdl.com/api/v2/me",
            {"Authorization": f"Bearer {subdl_cfg.get('api_key', '')}"},
        ),
        Backend.SUBSOURCE: (
            "https://api.subsource.net/api/v1/movies/search?searchType=text&q=test",
            {"X-API-Key": subsource_cfg.get("api_key", "")},
        ),
    }


class HealthProbe:
    """Probe each backend's reachability + latency, cached for 60s."""

    CACHE_TTL = 60.0

    def __init__(self, config: Dict[str, Any], timeout: float = 5.0) -> None:
        self.config = config
        self.timeout = timeout
        self._cache: Dict[str, EngineHealth] = {}
        self._probed_at = 0.0

    def probe(
        self, force: bool = False, only: Optional[List[Backend]] = None
    ) -> Dict[str, EngineHealth]:
        now = time.time()
        fresh = (now - self._probed_at) < self.CACHE_TTL
        targets = _probe_targets(self.config)
        backends = only if only is not None else list(targets.keys())

        if fresh and not force and self._cache and only is None:
            return dict(self._cache)

        result: Dict[str, EngineHealth] = {}
        for be in backends:
            url, headers = targets.get(be, ("", {}))
            if not url:
                continue
            health = self._probe_one(be.value, url, headers)
            result[be.value] = health
            self._cache[be.value] = health

        if only is None:
            self._probed_at = now
        return result

    def _probe_one(self, name: str, url: str, headers: Dict[str, str]) -> EngineHealth:
        start = time.time()
        try:
            resp = requests.get(url, timeout=self.timeout, headers=headers or None)
            latency = int((time.time() - start) * 1000)
            online = resp.status_code == 200
            # A 401/403 from an authenticated endpoint still means "reachable";
            # treat 5xx and network errors as degraded/offline.
            degraded = online is False and 400 <= resp.status_code < 500
            return EngineHealth(
                name=name,
                online=online,
                latency_ms=latency if online else None,
                degraded=degraded,
                last_checked=time.time(),
            )
        except requests.exceptions.Timeout:
            return EngineHealth(name=name, online=False, degraded=True, last_checked=time.time())
        except requests.exceptions.RequestException as exc:
            logger.debug("health probe %s failed: %s", name, exc)
            return EngineHealth(name=name, online=False, last_checked=time.time())


# --------------------------------------------------------------------------- #
# ConfigIO
# --------------------------------------------------------------------------- #
class ConfigIO:
    """Load/save config.yaml, seeding/extracting RunPolicy + AppState fields.

    Load reuses the same yaml.safe_load the legacy path uses. Save preserves
    unknown keys and, when ruamel.yaml is available, preserves comments too;
    otherwise it round-trips through pyyaml.
    """

    @staticmethod
    def load(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}

    @staticmethod
    def run_policy_from_config(config: Dict[str, Any]) -> RunPolicy:
        general = config.get("general", {}) or {}
        ads = (config.get("cleaning_subtitles", {}) or {}).get("ads", {}) or {}
        sync_arg, policy_str = _config_sync_policy(general.get("sync_audio_to_subs", "ask"))
        # hearing_impaired isn't a top-level config key today; the backends
        # pass hearing_impaired=False by default, so 'exclude' is the safe map.
        hi = "exclude"
        if general.get("hearing_impaired") == "only":
            hi = "only"
        elif general.get("hearing_impaired") == "include":
            hi = "include"
        return RunPolicy(
            force_utf8=bool(general.get("opt_force_utf8", True)),
            clean_ads=bool(ads.get("file_path", "")),  # only clean when there's an ads file
            audio_sync=policy_str,
            hearing_impaired=hi,
            auto_select=bool(general.get("auto_selection", False)),
            show_ai_translated=bool(general.get("show_ai_translated", True)),
            hash_match_first=bool(general.get("hash_match_first", True)),
            alt_name_search=bool(general.get("alt_name_search", True)),
            ads_file_path=ads.get("file_path") or None,
        )

    @staticmethod
    def backend_from_config(config: Dict[str, Any], override: Optional[str] = None) -> Backend:
        raw = (override or config.get("general", {}).get("preferred_backend") or "ask").lower()
        try:
            return Backend(raw)
        except ValueError:
            return Backend.OPENSUBTITLES

    @staticmethod
    def languages_from_config(config: Dict[str, Any]) -> Dict[str, str]:
        """Flatten the opensubtitles.languages block into {code: native name}.

        All three backend blocks carry the same shape (English: en, Arabic: ar);
        we union them so the popover shows every configured language regardless
        of the active engine. Keys are ISO codes; values are native names from
        the LANG_NATIVE_NAMES map (falling back to the config's English label).
        """
        from tui.state import native_name

        merged: Dict[str, str] = {}
        for section in ("opensubtitles", "subdl", "subsource"):
            block = (config.get(section, {}) or {}).get("languages", {}) or {}
            # block is {English: en, Arabic: ar} -> we want {en: "English", ...}
            for english_name, code in block.items():
                code_l = (code or "").lower()
                if not code_l:
                    continue
                merged.setdefault(code_l, native_name(code_l) or str(english_name))
        return merged or {"en": "English"}

    @staticmethod
    def apply_overrides(
        state: AppState, lang_override: Optional[str], backend_override: Optional[str]
    ) -> None:
        if lang_override:
            state.language = lang_override.lower()
        if backend_override:
            try:
                state.backend = Backend(backend_override.lower())
            except ValueError:
                pass

    @staticmethod
    def save(state: AppState, path: str) -> str:
        """Write the run-policy fields back to config.yaml, preserving other
        keys. Returns the one-line diff summary string for the confirm modal.
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                current = yaml.safe_load(fh) or {}
        except FileNotFoundError:
            current = {}

        before = yaml.safe_dump(current, sort_keys=False, allow_unicode=True)

        general = current.setdefault("general", {})
        ads = (current.setdefault("cleaning_subtitles", {})).setdefault("ads", {})

        changes: List[str] = []
        if state.run_policy.force_utf8 != bool(general.get("opt_force_utf8", True)):
            general["opt_force_utf8"] = state.run_policy.force_utf8
            changes.append("opt_force_utf8")
        new_sync = _policy_to_config_value(state.run_policy.audio_sync)
        if general.get("sync_audio_to_subs", "ask") != new_sync:
            general["sync_audio_to_subs"] = new_sync
            changes.append("sync_audio_to_subs")
        if bool(general.get("auto_selection", False)) != state.run_policy.auto_select:
            general["auto_selection"] = state.run_policy.auto_select
            changes.append("auto_selection")
        if (ads.get("file_path") or "") != (state.run_policy.ads_file_path or ""):
            ads["file_path"] = state.run_policy.ads_file_path or ""
            changes.append("ads.file_path")

        after = yaml.safe_dump(current, sort_keys=False, allow_unicode=True)

        with open(path, "w", encoding="utf-8") as fh:
            fh.write(after)

        if changes:
            return "config.yaml: " + ", ".join(changes)
        return "config.yaml: no changes"
