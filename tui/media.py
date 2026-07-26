"""Normalize CLI media inputs into a deterministic, de-duplicated queue."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MediaIssue:
    path: Path
    kind: str


@dataclass
class MediaExpansion:
    paths: list[Path] = field(default_factory=list)
    issues: list[MediaIssue] = field(default_factory=list)


def expand_media_paths(
    inputs: Iterable[str | Path], supported_extensions: set[str]
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

        candidates = (
            sorted(path.iterdir(), key=lambda item: item.name.casefold())
            if path.is_dir()
            else [path]
        )
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
