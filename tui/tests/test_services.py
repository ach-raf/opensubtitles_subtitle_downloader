"""Unit tests for tui.services — library/* is mocked, no real network."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from tui import services
from tui.services import (
    ConfigIO,
    DownloadWorker,
    HealthProbe,
    SearchWorker,
    _config_sync_policy,
    _policy_to_config_value,
)
from tui.state import AppState, Backend, EngineHealth, RunPolicy


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #
def _os_row(rid: str, release: str, downloads: int = 0, hash_match: bool = False):
    """A standardized subtitle row in the OpenSubtitles shape."""
    return {
        "id": rid,
        "attributes": {
            "release": release,
            "language": "en",
            "download_count": downloads,
            "ai_translated": False,
            "machine_translated": False,
            "moviehash_match": hash_match,
            "url": f"http://example/{rid}",
            "files": [{"file_id": int(rid) if rid.isdigit() else 1}],
        },
    }


class FakeUtils:
    """Stand-in for SubtitleUtils: deterministic scoring + no side effects."""

    def __init__(self):
        self.cleaned = []
        self.synced = []

    def hashFile(self, media_path):  # noqa: N802 - mirror backend API
        return "deadbeef"

    def get_alternate_names(self, media_name):  # noqa: N802
        return None  # keep the test deterministic

    def score_subtitle(self, release, video_name, hash_match=False):  # noqa: N802
        # Simple deterministic scorer: +50 for hash, + exact-word overlap.
        score = 100 if hash_match else 0
        v = set((video_name or "").lower().replace(".", " ").split())
        r = set((release or "").lower().replace(".", " ").split())
        score += 10 * len(v & r)
        return float(score)

    def clean_subtitles(self, sub_path):
        self.cleaned.append(sub_path)

    def sync_subtitles(self, media_path, sub_path):
        self.synced.append((media_path, sub_path))


def _make_worker(rows_by_backend=None, policy=None):
    """Build a SearchWorker wired to fake clients per backend.

    Each fake exposes the method SearchWorker actually calls for that backend:
    OpenSubtitles -> .search(**kw), SubDL/SubSource -> ._gather_candidates(path, lang).
    """
    rows_by_backend = rows_by_backend or {}
    worker = SearchWorker(config={}, policy=policy or RunPolicy())
    # Inject fake utils so scoring is deterministic.
    worker._utils = FakeUtils()

    def make_fake(backend, rows):
        client = MagicMock()
        if backend is Backend.OPENSUBTITLES:
            client.search.side_effect = lambda **kw: list(rows)
        else:
            # SubDL + SubSource go through _gather_candidates(path, language).
            client._gather_candidates.side_effect = lambda path, language: list(rows)
        return client

    for be, rows in rows_by_backend.items():
        worker._clients[be] = make_fake(be, rows)
    return worker


# --------------------------------------------------------------------------- #
# sync policy translation (config <-> RunPolicy)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected_arg,expected_policy",
    [
        ("ask", "ask", "ask"),
        (True, True, "always"),
        (False, False, "never"),
        ("true", True, "always"),
        ("false", False, "never"),
        ("yes", True, "always"),
        (None, "ask", "ask"),
    ],
)
def test_config_sync_policy_mapping(raw, expected_arg, expected_policy):
    arg, policy = _config_sync_policy(raw)
    assert arg == expected_arg
    assert policy == expected_policy


@pytest.mark.parametrize(
    "policy,expected",
    [("always", True), ("never", False), ("ask", "ask")],
)
def test_policy_to_config_value(policy, expected):
    assert _policy_to_config_value(policy) == expected


# --------------------------------------------------------------------------- #
# SearchWorker: dedupe + score + sort
# --------------------------------------------------------------------------- #
def test_search_dedupes_by_id():
    """Duplicate ids across multiple search passes collapse to one row."""
    rows = [
        _os_row("1", "Movie.2010.1080p", downloads=10),
        _os_row("1", "Movie.2010.1080p", downloads=10),  # dup id
        _os_row("2", "Movie.2010.720p", downloads=5),
    ]
    worker = _make_worker({Backend.OPENSUBTITLES: rows})
    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    out = worker.search(state, "Movie.2010.mkv")
    assert len(out) == 2
    assert {r["id"] for r in out} == {"1", "2"}


def test_search_scores_and_sorts_desc():
    """Higher score first; hash-match rows beat non-hash rows."""
    rows = [
        _os_row("low", "Unrelated.Release", downloads=999),
        _os_row("hash", "Inception.2010.1080p", downloads=1, hash_match=True),
        _os_row("mid", "Inception.2010", downloads=5),
    ]
    worker = _make_worker({Backend.OPENSUBTITLES: rows})
    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    out = worker.search(state, "Inception.2010.1080p.mkv")
    ids = [r["id"] for r in out]
    assert ids[0] == "hash"  # hash_match adds 100
    assert "_score" in out[0]


def test_search_empty_when_backend_raises():
    """A backend exception is contained -> empty list, error on state."""
    worker = _make_worker({})  # no client injected for OS
    # Force _client to raise.
    worker._client = lambda be: (_ for _ in ()).throw(RuntimeError("boom"))
    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    out = worker.search(state, "x.mkv")
    assert out == []
    assert state.last_error is not None
    assert "boom" in state.last_error


def test_search_auto_picks_first_online_engine():
    """AUTO should route to the first engine the health map says is online."""
    rows_subdl = [_os_row("s1", "Movie")]
    worker = _make_worker({Backend.SUBDL: rows_subdl})
    state = AppState(
        backend=Backend.AUTO,
        language="en",
        engine_health={
            "opensubtitles": EngineHealth("opensubtitles", online=False),
            "subdl": EngineHealth("subdl", online=True),
        },
    )
    out = worker.search(state, "Movie.mkv")
    assert len(out) == 1
    assert out[0]["_source"] == "subdl"


def test_search_merge_mode_unions_all_sources_and_tags_them():
    rows_os = [_os_row("os1", "Movie")]
    rows_subdl = [_os_row("sd1", "Movie")]
    rows_subsource = [_os_row("ss1", "Movie")]
    worker = _make_worker(
        {
            Backend.OPENSUBTITLES: rows_os,
            Backend.SUBDL: rows_subdl,
            Backend.SUBSOURCE: rows_subsource,
        }
    )
    state = AppState(
        backend=Backend.OPENSUBTITLES,
        merge_mode=True,
        language="en",
        engine_health={be.value: EngineHealth(be.value, online=True) for be in
                       (Backend.OPENSUBTITLES, Backend.SUBDL, Backend.SUBSOURCE)},
    )
    out = worker.search(state, "Movie.mkv")
    assert {r["_source"] for r in out} == {"opensubtitles", "subdl", "subsource"}
    assert len(out) == 3


# --------------------------------------------------------------------------- #
# DownloadWorker: policy application + sync failure handling
# --------------------------------------------------------------------------- #
def _download_worker(policy=None, utils=None):
    worker = DownloadWorker(config={}, policy=policy or RunPolicy())
    if utils is not None:
        worker._utils = utils
    return worker


def test_download_and_postprocess_always_runs_clean_and_sync(tmp_path):
    """audio_sync='always' -> both clean + sync fire."""
    media = tmp_path / "m.mkv"
    media.write_text("x")
    utils = FakeUtils()

    # Patch the ffs lookup so _sync proceeds.
    worker = _download_worker(policy=RunPolicy(audio_sync="always", clean_ads=True), utils=utils)

    fake_client = MagicMock()
    fake_client.get_download_link.return_value = "http://link"
    fake_client.save_subtitle.return_value = True
    worker._clients[Backend.OPENSUBTITLES] = fake_client

    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    chosen = _os_row("1", "m")

    with patch("shutil.which", return_value="/usr/bin/ffs"):
        entry = worker.download_and_postprocess(state, str(media), chosen)

    assert entry.cleaned is True
    assert entry.synced is True
    assert entry.sync_skipped is False
    assert utils.cleaned and utils.synced


def test_sync_skipped_when_ffs_missing(tmp_path):
    """No ffs on PATH -> sync_skipped=True, amber tone (spec §12)."""
    media = tmp_path / "m.mkv"
    media.write_text("x")
    utils = FakeUtils()
    worker = _download_worker(
        policy=RunPolicy(audio_sync="always", clean_ads=True), utils=utils
    )
    fake_client = MagicMock()
    fake_client.get_download_link.return_value = "http://link"
    fake_client.save_subtitle.return_value = True
    worker._clients[Backend.OPENSUBTITLES] = fake_client

    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    chosen = _os_row("1", "m")

    with patch("shutil.which", return_value=None):
        entry = worker.download_and_postprocess(state, str(media), chosen)

    assert entry.synced is False
    assert entry.sync_skipped is True
    assert "ffs" in (entry.error or "")


def test_download_failure_returns_not_downloaded(tmp_path):
    media = tmp_path / "m.mkv"
    media.write_text("x")
    worker = _download_worker(policy=RunPolicy())
    fake_client = MagicMock()
    fake_client.get_download_link.return_value = None  # backend gave no link
    worker._clients[Backend.OPENSUBTITLES] = fake_client

    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    result = worker.download(state, str(media), _os_row("1", "m"))
    assert result.downloaded is False
    assert result.error is not None


def test_download_exception_is_contained(tmp_path):
    """A raised backend exception becomes a not-downloaded result, never propagates."""
    media = tmp_path / "m.mkv"
    media.write_text("x")
    worker = _download_worker(policy=RunPolicy())

    def boom(*a, **k):
        raise RuntimeError("network down")

    worker._client = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down"))
    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    result = worker.download(state, str(media), _os_row("1", "m"))
    assert result.downloaded is False
    assert "network down" in result.error


# --------------------------------------------------------------------------- #
# HealthProbe: caching + latency
# --------------------------------------------------------------------------- #
def _fake_response(status=200):
    resp = MagicMock()
    resp.status_code = status
    return resp


def test_health_probe_marks_online_with_latency():
    probe = HealthProbe(config={})
    with patch("tui.services.requests.get", return_value=_fake_response(200)) as mock_get:
        out = probe.probe(force=True)
    assert out["opensubtitles"].online is True
    assert out["opensubtitles"].latency_ms is not None
    assert out["opensubtitles"].latency_ms >= 0
    assert mock_get.called


def test_health_probe_marks_offline_on_network_error():
    probe = HealthProbe(config={})
    with patch(
        "tui.services.requests.get",
        side_effect=requests.exceptions.ConnectionError("no net"),
    ):
        out = probe.probe(force=True)
    assert out["opensubtitles"].online is False
    assert out["opensubtitles"].degraded is False


def test_health_probe_caches_within_ttl():
    probe = HealthProbe(config={})
    with patch("tui.services.requests.get", return_value=_fake_response(200)) as mock_get:
        probe.probe(force=True)
        probe.probe()  # should hit cache
        assert mock_get.call_count == 3  # one round only (3 backends)


def test_health_probe_force_bypasses_cache():
    probe = HealthProbe(config={})
    with patch("tui.services.requests.get", return_value=_fake_response(200)) as mock_get:
        probe.probe(force=True)
        probe.probe(force=True)
    assert mock_get.call_count == 6  # two rounds


def test_health_probe_degraded_on_5xx():
    probe = HealthProbe(config={})
    with patch("tui.services.requests.get", return_value=_fake_response(503)):
        out = probe.probe(force=True)
    # 5xx -> offline, not degraded (degraded is reserved for 4xx/auth issues)
    assert out["opensubtitles"].online is False


def test_health_probe_degraded_on_4xx():
    probe = HealthProbe(config={})
    with patch("tui.services.requests.get", return_value=_fake_response(401)):
        out = probe.probe(force=True)
    assert out["opensubtitles"].online is False
    assert out["opensubtitles"].degraded is True


# --------------------------------------------------------------------------- #
# ConfigIO: load + run_policy + save round-trip
# --------------------------------------------------------------------------- #
def test_run_policy_from_config_sample():
    config = {
        "general": {
            "opt_force_utf8": True,
            "sync_audio_to_subs": "ask",
            "auto_selection": False,
        },
        "cleaning_subtitles": {"ads": {"file_path": "/some/ads.txt"}},
    }
    p = ConfigIO.run_policy_from_config(config)
    assert p.force_utf8 is True
    assert p.audio_sync == "ask"
    assert p.auto_select is False
    assert p.ads_file_path == "/some/ads.txt"
    assert p.clean_ads is True  # an ads file is configured


def test_languages_from_config_unions_all_backends():
    config = {
        "opensubtitles": {"languages": {"English": "en", "Arabic": "ar"}},
        "subdl": {"languages": {"Japanese": "ja"}},
        "subsource": {"languages": {"French": "fr"}},
    }
    langs = ConfigIO.languages_from_config(config)
    assert langs["en"] == "English"
    assert langs["ar"] == "العربية"  # native name from the map
    assert langs["ja"] == "日本語"
    assert langs["fr"] == "Français"


def test_languages_from_config_empty_defaults_to_english():
    assert ConfigIO.languages_from_config({}) == {"en": "English"}


def test_backend_from_config_handles_override_and_invalid():
    assert ConfigIO.backend_from_config({}, override="subdl") is Backend.SUBDL
    assert ConfigIO.backend_from_config({"general": {"preferred_backend": "auto"}}) is Backend.AUTO
    # Invalid string falls back to OpenSubtitles (matches legacy warning behaviour).
    assert ConfigIO.backend_from_config({"general": {"preferred_backend": "garbage"}}) is Backend.OPENSUBTITLES


def test_config_save_round_trips_policy(tmp_path):
    """Save writes the policy back and preserves unrelated keys."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "general:\n"
        "  opt_force_utf8: true\n"
        "  sync_audio_to_subs: ask\n"
        "  auto_selection: false\n"
        "cleaning_subtitles:\n"
        "  ads:\n"
        "    file_path: ''\n"
        "opensubtitles:\n"
        "  api_key: keepme\n",
        encoding="utf-8",
    )
    state = AppState(backend=Backend.OPENSUBTITLES, language="en")
    state.run_policy = RunPolicy(
        force_utf8=False,
        audio_sync="always",
        auto_select=True,
        clean_ads=True,
        ads_file_path="/new/ads.txt",
    )

    summary = ConfigIO.save(state, str(cfg_path))

    reloaded = ConfigIO.load(str(cfg_path))
    assert reloaded["general"]["opt_force_utf8"] is False
    assert reloaded["general"]["sync_audio_to_subs"] is True  # always -> true
    assert reloaded["general"]["auto_selection"] is True
    assert reloaded["cleaning_subtitles"]["ads"]["file_path"] == "/new/ads.txt"
    # Unrelated key preserved.
    assert reloaded["opensubtitles"]["api_key"] == "keepme"
    assert "opt_force_utf8" in summary


def test_config_save_no_changes_summary(tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "general:\n  opt_force_utf8: true\n  sync_audio_to_subs: ask\n  auto_selection: false\n"
        "cleaning_subtitles:\n  ads:\n    file_path: ''\n",
        encoding="utf-8",
    )
    state = AppState()
    state.run_policy = RunPolicy(force_utf8=True, audio_sync="ask", auto_select=False, ads_file_path=None)
    summary = ConfigIO.save(state, str(cfg_path))
    assert "no changes" in summary
