"""Validated configuration loading with atomic, secret-safe persistence."""

from __future__ import annotations

import copy
import io
import os
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from tui.domain import EngineMode, Provider

SUPPORTED_GENERAL_FIELDS = {
    "preferred_backend",
    "default_language",
    "recursive_search",
    "subtitle_output_directory",
    "skip_interactive_menu",
    "sync_audio_to_subs",
    "auto_selection",
    "opt_force_utf8",
    "no_tui",
    "hearing_impaired",
    "show_ai_translated",
}
SECRET_FIELDS = {"username", "password", "api_key", "user_agent"}


@dataclass
class GeneralConfig:
    preferred_backend: EngineMode = EngineMode.ASK
    default_language: str = ""
    recursive_search: bool = False
    subtitle_output_directory: str = ""
    skip_interactive_menu: bool = False
    sync_audio_to_subs: str = "ask"
    auto_selection: bool = False
    opt_force_utf8: bool = True
    no_tui: bool = False
    hearing_impaired: str = "include"
    show_ai_translated: bool = True


@dataclass
class ProviderConfig:
    provider: Provider
    values: dict[str, Any] = field(default_factory=dict, repr=False)
    languages: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        required = {
            Provider.OPENSUBTITLES: (
                "username",
                "password",
                "api_key",
                "user_agent",
            ),
            Provider.SUBDL: ("api_key",),
            Provider.SUBSOURCE: ("api_key",),
        }[self.provider]
        return all(bool(self.values.get(key)) for key in required)


@dataclass
class CleaningConfig:
    enabled: bool = True
    ads_file_path: Path | None = None
    separator: str = ","
    supported_media: list[str] = field(default_factory=list)


@dataclass
class ApplicationConfig:
    general: GeneralConfig
    providers: dict[Provider, ProviderConfig]
    cleaning: CleaningConfig
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfigDiff:
    changed_fields: list[str]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_mode(value: object) -> EngineMode:
    try:
        return EngineMode(str(value))
    except ValueError:
        return EngineMode.ASK


def normalize_sync_policy(value: object) -> str:
    if value is True:
        return "always"
    if value is False:
        return "never"
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "always"}:
        return "always"
    if normalized in {"false", "0", "no", "never"}:
        return "never"
    return "ask"


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix: value}
    flattened: dict[str, Any] = {}
    for key, child in value.items():
        child_prefix = f"{prefix}.{key}" if prefix else str(key)
        flattened.update(_flatten(child, child_prefix))
    return flattened


class ConfigRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._loaded_raw: MutableMapping[str, Any] = CommentedMap()
        self._yaml = YAML(typ="rt")
        self._yaml.preserve_quotes = True
        self._yaml.width = 4096
        self._yaml.indent(mapping=2, sequence=4, offset=2)

    def load(self) -> ApplicationConfig:
        raw: MutableMapping[str, Any] = CommentedMap()
        if self.path.exists():
            loaded = self._yaml.load(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, MutableMapping):
                raw = loaded
        self._loaded_raw = copy.deepcopy(raw)

        general_raw = raw.get("general") or {}
        preferred_backend = _safe_mode(
            general_raw.get("preferred_backend", EngineMode.ASK.value)
        )
        general = GeneralConfig(
            preferred_backend=preferred_backend,
            default_language=str(
                general_raw.get("default_language", "") or ""
            ).strip().lower(),
            recursive_search=bool(general_raw.get("recursive_search", False)),
            subtitle_output_directory=str(
                general_raw.get("subtitle_output_directory", "")
            ).strip(),
            skip_interactive_menu=bool(general_raw.get("skip_interactive_menu", False)),
            sync_audio_to_subs=normalize_sync_policy(
                general_raw.get("sync_audio_to_subs", "ask")
            ),
            auto_selection=bool(general_raw.get("auto_selection", False)),
            opt_force_utf8=bool(general_raw.get("opt_force_utf8", True)),
            no_tui=bool(general_raw.get("no_tui", False)),
            hearing_impaired=str(
                general_raw.get("hearing_impaired", "include")
            ).lower(),
            show_ai_translated=bool(general_raw.get("show_ai_translated", True)),
        )
        providers: dict[Provider, ProviderConfig] = {}
        for provider in Provider:
            section = raw.get(provider.value) or {}
            languages = section.get("languages") or {}
            values = {
                key: value for key, value in section.items() if key != "languages"
            }
            providers[provider] = ProviderConfig(
                provider=provider,
                values=values,
                languages={str(name): str(code) for name, code in languages.items()},
            )

        cleaning_raw = raw.get("cleaning_subtitles") or {}
        ads_raw = cleaning_raw.get("ads") or {}
        ads_path = str(ads_raw.get("file_path") or "").strip()
        cleaning = CleaningConfig(
            enabled=bool(cleaning_raw.get("enabled", True)),
            ads_file_path=Path(ads_path) if ads_path else None,
            separator=str(ads_raw.get("separator", ",")),
            supported_media=list(cleaning_raw.get("supported_media") or []),
        )
        known = {"general", "cleaning_subtitles", *(p.value for p in Provider)}
        extra = {
            key: copy.deepcopy(value) for key, value in raw.items() if key not in known
        }
        return ApplicationConfig(general, providers, cleaning, extra)

    def save(self, config: ApplicationConfig) -> ConfigDiff:
        output, diff = self._prepare(config)
        stream = io.StringIO()
        self._yaml.dump(output, stream)
        _atomic_write(self.path, stream.getvalue())
        self._loaded_raw = copy.deepcopy(output)
        return diff

    def preview_diff(self, config: ApplicationConfig) -> ConfigDiff:
        """Return a field-name-only diff without writing or exposing values."""
        _, diff = self._prepare(config)
        return diff

    def _prepare(
        self,
        config: ApplicationConfig,
    ) -> tuple[MutableMapping[str, Any], ConfigDiff]:
        output = copy.deepcopy(self._loaded_raw)
        output.update(copy.deepcopy(config.extra))
        general_output = self._section(output, "general")
        general_output.pop("merge_results", None)
        for name in SUPPORTED_GENERAL_FIELDS:
            value = getattr(config.general, name)
            if isinstance(value, EngineMode):
                value = value.value
            elif name == "sync_audio_to_subs":
                value = {"always": True, "never": False}.get(value, "ask")
            general_output[name] = value
        for provider, provider_config in config.providers.items():
            provider_output = self._section(output, provider.value)
            provider_output.update(provider_config.values)
            languages_output = self._section(provider_output, "languages")
            for name in list(languages_output):
                if name not in provider_config.languages:
                    del languages_output[name]
            languages_output.update(provider_config.languages)
        cleaning_output = self._section(output, "cleaning_subtitles")
        cleaning_output["supported_media"] = list(config.cleaning.supported_media)
        ads_output = self._section(cleaning_output, "ads")
        ads_output.update(
            {
                "separator": config.cleaning.separator,
                "file_path": (
                    str(config.cleaning.ads_file_path)
                    if config.cleaning.ads_file_path
                    else ""
                ),
            }
        )
        if (
            "enabled" in (self._loaded_raw.get("cleaning_subtitles") or {})
            or not config.cleaning.enabled
        ):
            cleaning_output["enabled"] = config.cleaning.enabled
        before = _flatten(self._loaded_raw)
        after = _flatten(output)
        changed = sorted(
            key
            for key in before.keys() | after.keys()
            if before.get(key) != after.get(key)
        )
        return output, ConfigDiff(changed_fields=changed)

    @staticmethod
    def _section(
        parent: MutableMapping[str, Any],
        name: str,
    ) -> MutableMapping[str, Any]:
        section = parent.get(name)
        if not isinstance(section, MutableMapping):
            section = CommentedMap()
            parent[name] = section
        return section
