"""Normalize CLI media inputs into a deterministic, de-duplicated queue."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MEDIA_EXTENSIONS = frozenset(
    {
        "3g2",
        "3gp",
        "asf",
        "avi",
        "av1",
        "divx",
        "f4v",
        "flv",
        "h264",
        "h265",
        "hevc",
        "m2ts",
        "m2v",
        "m4v",
        "mkv",
        "mov",
        "mp4",
        "mpeg",
        "mpg",
        "mts",
        "mxf",
        "ogm",
        "ogv",
        "rm",
        "rmvb",
        "ts",
        "vob",
        "webm",
        "wmv",
    }
)

def resolve_media_extensions(
    include: Iterable[str] = (),
    exclude: Iterable[str] = (),
) -> set[str]:
    def normalize(value: object) -> str:
        return str(value).strip().lower().lstrip(".")

    additions = {
        normalized
        for value in include
        if (normalized := normalize(value))
    }
    removals = {
        normalized
        for value in exclude
        if (normalized := normalize(value))
    }
    return (set(DEFAULT_MEDIA_EXTENSIONS) | additions) - removals


@dataclass(frozen=True)
class MediaIssue:
    path: Path
    kind: str


@dataclass
class MediaExpansion:
    paths: list[Path] = field(default_factory=list)
    issues: list[MediaIssue] = field(default_factory=list)


def expand_media_paths(
    inputs: Iterable[str | Path],
    supported_extensions: set[str],
    *,
    recursive: bool = False,
) -> MediaExpansion:
    extensions = {extension.lower().lstrip(".") for extension in supported_extensions}
    accepted: list[Path] = []
    issues: list[MediaIssue] = []
    seen: set[Path] = set()

    for raw in inputs:
        path = Path(raw).resolve()
        if not path.exists():
            issues.append(MediaIssue(path=path, kind="missing"))
            continue

        if path.is_dir() and recursive:
            candidates = []

            def record_error(error: OSError, root_path: Path = path) -> None:
                issue_path = Path(error.filename or root_path)
                issues.append(MediaIssue(path=issue_path, kind="unreadable"))

            for root, directories, filenames in os.walk(
                path,
                topdown=True,
                onerror=record_error,
                followlinks=False,
            ):
                directories.sort(key=str.casefold)
                filenames.sort(key=str.casefold)
                candidates.extend(Path(root) / filename for filename in filenames)
        elif path.is_dir():
            try:
                candidates = sorted(
                    path.iterdir(),
                    key=lambda item: item.name.casefold(),
                )
            except OSError:
                issues.append(MediaIssue(path=path, kind="unreadable"))
                continue
        else:
            candidates = [path]
        matched = False
        for candidate in candidates:
            if (
                candidate.is_file()
                and candidate.suffix.lower().lstrip(".") in extensions
            ):
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    accepted.append(resolved)
                matched = True
        if not matched:
            issues.append(MediaIssue(path=path, kind="unsupported"))

    return MediaExpansion(paths=accepted, issues=issues)
