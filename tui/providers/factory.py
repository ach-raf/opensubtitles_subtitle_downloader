"""Lazy provider construction from the validated application configuration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tui.config import ApplicationConfig
from tui.domain import Provider
from tui.providers.base import ProviderAdapter
from tui.providers.opensubtitles import OpenSubtitlesAdapter
from tui.providers.subdl import SubDLAdapter
from tui.providers.subsource import SubSourceAdapter


class LazyClient:
    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._client: Any | None = None

    def __getattr__(self, name: str) -> Any:
        if self._client is None:
            self._client = self._factory()
        return getattr(self._client, name)


def _sync_value(value: str) -> bool | str:
    return {"always": True, "never": False}.get(value, "ask")


def create_adapters(
    config: ApplicationConfig,
) -> dict[Provider, ProviderAdapter]:
    sync = _sync_value(config.general.sync_audio_to_subs)

    def opensubtitles_client():
        from library.OpenSubtitles import OpenSubtitles

        values = config.providers[Provider.OPENSUBTITLES].values
        return OpenSubtitles(
            username=values.get("username", ""),
            password=values.get("password", ""),
            api_key=values.get("api_key", ""),
            user_agent=values.get("user_agent", ""),
            sync_audio_to_subs=sync,
            hearing_impaired=False,
            auto_select=False,
        )

    def subdl_client():
        from library.SubDL import SubDL

        values = config.providers[Provider.SUBDL].values
        return SubDL(
            api_key=values.get("api_key", ""),
            sync_audio_to_subs=sync,
            hearing_impaired=False,
            auto_select=False,
        )

    def subsource_client():
        from library.SubSource import SubSource

        values = config.providers[Provider.SUBSOURCE].values
        return SubSource(
            api_key=values.get("api_key", ""),
            sync_audio_to_subs=sync,
            hearing_impaired=False,
            auto_select=False,
        )

    factories = {
        Provider.OPENSUBTITLES: (
            OpenSubtitlesAdapter,
            opensubtitles_client,
        ),
        Provider.SUBDL: (SubDLAdapter, subdl_client),
        Provider.SUBSOURCE: (SubSourceAdapter, subsource_client),
    }
    return {
        provider: adapter_type(LazyClient(factory))
        for provider, (adapter_type, factory) in factories.items()
        if config.providers[provider].configured
    }
