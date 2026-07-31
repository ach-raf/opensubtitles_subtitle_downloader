from tui.domain import Candidate, DownloadResult, Provider
from tui.jobs import JobCoordinator


def candidate_for(provider, provider_id="77"):
    return Candidate(
        provider=provider,
        provider_id=provider_id,
        release="Movie",
        language="en",
    )


def encoded_download(tmp_path, text, encoding):
    subtitle = tmp_path / "Movie.en.srt"
    subtitle.write_bytes(text.encode(encoding))
    return subtitle, DownloadResult(
        provider=Provider.SUBDL,
        media_path=tmp_path / "Movie.mkv",
        subtitle_path=subtitle,
    )


class RecordingAdapter:
    def __init__(self, provider):
        self.provider = provider
        self.downloads = []
        self.media_paths = []

    def download(self, candidate, media_path):
        self.downloads.append(candidate.key)
        self.media_paths.append(media_path)
        target = media_path.with_name(f"{media_path.stem}.en.srt")
        target.write_text("new", encoding="utf-8")
        return DownloadResult(
            provider=self.provider,
            media_path=media_path,
            subtitle_path=target,
        )


class FailingCleaner:
    def __init__(self, message):
        self.message = message

    def clean(self, subtitle_path, ads_path=None):
        raise RuntimeError(self.message)


class RecordingCleaner:
    def __init__(self):
        self.ads_paths = []

    def clean(self, subtitle_path, ads_path=None):
        self.ads_paths.append(ads_path)
        return True


class StreamingSynchronizer:
    def sync(self, media_path, subtitle_path, on_output=None):
        on_output("extracting speech segments...")
        on_output("...done")
        return True


def test_download_dispatches_to_candidate_provider(tmp_path):
    adapters = {
        Provider.OPENSUBTITLES: RecordingAdapter(Provider.OPENSUBTITLES),
        Provider.SUBDL: RecordingAdapter(Provider.SUBDL),
    }
    candidate = candidate_for(Provider.SUBDL)

    result = JobCoordinator(adapters).download(candidate, tmp_path / "Movie.mkv")

    assert result.provider is Provider.SUBDL
    assert result.subtitle_path == tmp_path / "Movie.en.srt"
    assert adapters[Provider.SUBDL].downloads == [candidate.key]
    assert adapters[Provider.OPENSUBTITLES].downloads == []


def test_existing_target_requires_explicit_replace(tmp_path):
    adapters = {Provider.SUBDL: RecordingAdapter(Provider.SUBDL)}
    target = tmp_path / "Movie.en.srt"
    target.write_text("old", encoding="utf-8")

    result = JobCoordinator(adapters).download(
        candidate_for(Provider.SUBDL),
        tmp_path / "Movie.mkv",
    )

    assert result.conflict_path == target
    assert target.read_text(encoding="utf-8") == "old"
    assert adapters[Provider.SUBDL].downloads == []


def test_explicit_replace_is_atomic_from_staging(tmp_path):
    adapters = {Provider.SUBDL: RecordingAdapter(Provider.SUBDL)}
    target = tmp_path / "Movie.en.srt"
    target.write_text("old", encoding="utf-8")

    result = JobCoordinator(adapters).download(
        candidate_for(Provider.SUBDL),
        tmp_path / "Movie.mkv",
        overwrite=True,
    )

    assert result.succeeded
    assert target.read_text(encoding="utf-8") == "new"


def test_download_stages_and_saves_in_external_output_directory(tmp_path):
    adapter = RecordingAdapter(Provider.SUBDL)
    output_directory = tmp_path / "writable-subs"
    media = tmp_path / "read-only-library" / "Movie.mkv"

    result = JobCoordinator(
        {Provider.SUBDL: adapter},
        output_directory=output_directory,
    ).download(candidate_for(Provider.SUBDL), media)

    assert result.succeeded
    assert result.media_path == media
    assert result.subtitle_path == output_directory / "Movie.en.srt"
    assert adapter.media_paths[0].parent.parent == output_directory


def test_download_reports_unwritable_output_directory(tmp_path, monkeypatch):
    def deny_staging(*_args, **_kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr("tui.jobs.TemporaryDirectory", deny_staging)
    result = JobCoordinator(
        {Provider.SUBDL: RecordingAdapter(Provider.SUBDL)},
        output_directory=tmp_path / "subtitles",
    ).download(
        candidate_for(Provider.SUBDL),
        tmp_path / "library" / "Movie.mkv",
    )


    assert result.succeeded is False
    assert "access denied" in result.error


def test_clean_failure_is_not_recorded_as_success(tmp_path):
    cleaner = FailingCleaner("bad ads pattern")
    download = DownloadResult(
        provider=Provider.SUBDL,
        media_path=tmp_path / "Movie.mkv",
        subtitle_path=tmp_path / "Movie.en.srt",
    )

    result = JobCoordinator({}, cleaner=cleaner).postprocess(
        download,
        clean=True,
        sync=False,
        ads_path=tmp_path / "ads.txt",
    )

    assert result.cleaned is False
    assert result.clean_error == "bad ads pattern"


def test_cleaner_receives_configured_ads_path(tmp_path):
    cleaner = RecordingCleaner()
    ads = tmp_path / "custom-ads.txt"
    download = DownloadResult(
        provider=Provider.SUBDL,
        media_path=tmp_path / "Movie.mkv",
        subtitle_path=tmp_path / "Movie.en.srt",
    )

    result = JobCoordinator({}, cleaner=cleaner).postprocess(
        download,
        clean=True,
        sync=False,
        ads_path=ads,
    )

    assert result.cleaned
    assert cleaner.ads_paths == [ads]


def test_force_utf8_normalizes_legacy_encoded_subtitle(tmp_path):
    subtitle = tmp_path / "Movie.en.srt"
    subtitle.write_bytes("café".encode("cp1252"))
    download = DownloadResult(
        provider=Provider.SUBDL,
        media_path=tmp_path / "Movie.mkv",
        subtitle_path=subtitle,
    )

    result = JobCoordinator({}).postprocess(
        download,
        force_utf8=True,
        clean=False,
        sync=False,
    )

    assert result.utf8_normalized
    assert subtitle.read_text(encoding="utf-8") == "café"


def test_force_utf8_normalizes_utf16_subtitle(tmp_path):
    subtitle, download = encoded_download(tmp_path, "hello", "utf-16")

    result = JobCoordinator({}).postprocess(
        download,
        force_utf8=True,
        clean=False,
        sync=False,
    )

    assert result.utf8_normalized
    assert subtitle.read_bytes() == b"hello"


def test_force_utf8_detects_windows_1256_subtitle(tmp_path):
    text = (
        "1\n00:00:01,000 --> 00:00:04,000\n"
        "مرحبا بكم في هذا الفيلم الرائع، نأمل أن تستمتعوا بالمشاهدة.\n\n"
        "2\n00:00:05,000 --> 00:00:09,000\n"
        "هذه جملة عربية طويلة لاختبار ترميز النصوص القديمة.\n"
    )
    subtitle, download = encoded_download(tmp_path, text, "windows-1256")

    result = JobCoordinator({}).postprocess(
        download,
        force_utf8=True,
        clean=False,
        sync=False,
    )

    assert result.utf8_normalized
    assert subtitle.read_text(encoding="utf-8") == text


def test_disabled_force_utf8_preserves_original_bytes(tmp_path):
    original = "café".encode("cp1252")
    subtitle, download = encoded_download(tmp_path, "café", "cp1252")

    result = JobCoordinator({}).postprocess(
        download,
        force_utf8=False,
        clean=False,
        sync=False,
    )

    assert result.utf8_normalized is False
    assert subtitle.read_bytes() == original


def test_postprocess_forwards_live_sync_output(tmp_path):
    subtitle = tmp_path / "Movie.en.srt"
    subtitle.write_text("subtitle", encoding="utf-8")
    download = DownloadResult(
        provider=Provider.SUBDL,
        media_path=tmp_path / "Movie.mkv",
        subtitle_path=subtitle,
    )
    output = []

    result = JobCoordinator(
        {},
        synchronizer=StreamingSynchronizer(),
    ).postprocess(
        download,
        clean=False,
        sync=True,
        sync_output=output.append,
    )

    assert result.synced is True
    assert output == ["extracting speech segments...", "...done"]
