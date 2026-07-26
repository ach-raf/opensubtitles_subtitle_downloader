"""Concurrent merge and legacy-compatible AUTO search coordination."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tui.domain import (
    Candidate,
    HealthResult,
    Provider,
    ProviderSearchResult,
    SearchRequest,
)
from tui.providers.base import ProviderAdapter, redact_secrets

AUTO_PRIORITY = (
    Provider.SUBSOURCE,
    Provider.OPENSUBTITLES,
    Provider.SUBDL,
)
PROVIDER_PRIORITY = {provider: index for index, provider in enumerate(AUTO_PRIORITY)}


@dataclass
class CoordinatedSearchResult:
    candidates: list[Candidate] = field(default_factory=list)
    errors: dict[Provider, str] = field(default_factory=dict)
    attempted: list[Provider] = field(default_factory=list)
    selected_provider: Provider | None = None


class SearchCoordinator:
    def __init__(
        self,
        adapters: dict[Provider, ProviderAdapter],
        scorer: Any | None = None,
    ) -> None:
        self.adapters = adapters
        if scorer is None:
            try:
                from library.subtitle_utils import SubtitleUtils

                scorer = SubtitleUtils()
            except Exception:
                scorer = None
        self.scorer = scorer

    def concrete(
        self, provider: Provider, request: SearchRequest
    ) -> CoordinatedSearchResult:
        adapter = self.adapters.get(provider)
        if adapter is None:
            return CoordinatedSearchResult(
                errors={provider: "Provider is not configured"}
            )
        result = self._safe_search(provider, adapter, request)
        return CoordinatedSearchResult(
            candidates=self._prepare(result.candidates, request),
            errors={provider: result.error} if result.error else {},
            attempted=[provider],
            selected_provider=provider if result.candidates else None,
        )

    def merge(
        self,
        request: SearchRequest,
        health: dict[Provider, HealthResult] | None = None,
    ) -> CoordinatedSearchResult:
        del health  # Health is diagnostic and must never hard-gate a search.
        if not self.adapters:
            return CoordinatedSearchResult()

        provider_results: dict[Provider, ProviderSearchResult] = {}
        with ThreadPoolExecutor(max_workers=len(self.adapters)) as executor:
            futures = {
                executor.submit(
                    self._safe_search,
                    provider,
                    adapter,
                    request,
                ): provider
                for provider, adapter in self.adapters.items()
            }
            for future in as_completed(futures):
                provider = futures[future]
                provider_results[provider] = future.result()

        candidates: list[Candidate] = []
        errors: dict[Provider, str] = {}
        attempted: list[Provider] = []
        for provider in Provider:
            if provider not in provider_results:
                continue
            attempted.append(provider)
            result = provider_results[provider]
            candidates.extend(result.candidates)
            if result.error:
                errors[provider] = result.error
        return CoordinatedSearchResult(
            candidates=self._prepare(candidates, request),
            errors=errors,
            attempted=attempted,
        )

    def auto(
        self,
        request: SearchRequest,
        health: dict[Provider, HealthResult] | None = None,
    ) -> CoordinatedSearchResult:
        health = health or {}
        available = [
            provider
            for provider in AUTO_PRIORITY
            if provider in self.adapters
            and not (provider in health and not health[provider].configured)
        ]
        order = sorted(
            available,
            key=lambda provider: (
                not (provider in health and health[provider].reachable),
                PROVIDER_PRIORITY[provider],
            ),
        )
        attempted: list[Provider] = []
        errors: dict[Provider, str] = {}
        for provider in order:
            attempted.append(provider)
            result = self._safe_search(
                provider,
                self.adapters[provider],
                request,
            )
            if result.error:
                errors[provider] = result.error
            candidates = self._prepare(result.candidates, request)
            if candidates:
                return CoordinatedSearchResult(
                    candidates=candidates,
                    errors=errors,
                    attempted=attempted,
                    selected_provider=provider,
                )
        return CoordinatedSearchResult(errors=errors, attempted=attempted)

    @staticmethod
    def _safe_search(
        provider: Provider,
        adapter: ProviderAdapter,
        request: SearchRequest,
    ) -> ProviderSearchResult:
        try:
            return adapter.search(request)
        except Exception as exc:
            return ProviderSearchResult(
                provider=provider,
                error=redact_secrets(f"{type(exc).__name__}: {exc}"),
            )

    def _prepare(
        self,
        candidates: list[Candidate],
        request: SearchRequest,
    ) -> list[Candidate]:
        filtered = [
            candidate
            for candidate in candidates
            if self._is_visible(candidate, request)
        ]
        deduplicated = {candidate.key: candidate for candidate in filtered}
        score_target = request.query.strip() or Path(request.media_path).stem
        for candidate in deduplicated.values():
            if self.scorer is None:
                continue
            try:
                candidate.score = float(
                    self.scorer.score_subtitle(
                        candidate.release,
                        score_target,
                        candidate.hash_match,
                    )
                )
            except Exception:
                candidate.score = 0.0
        return sorted(
            deduplicated.values(),
            key=lambda item: (
                item.score,
                item.hash_match,
                item.download_count,
                -PROVIDER_PRIORITY[item.provider],
            ),
            reverse=True,
        )

    @staticmethod
    def _is_visible(
        candidate: Candidate,
        request: SearchRequest,
    ) -> bool:
        if not request.show_ai_translated and candidate.ai_translated:
            return False
        if request.hearing_impaired == "exclude" and candidate.hearing_impaired:
            return False
        return not (
            request.hearing_impaired == "only" and not candidate.hearing_impaired
        )
