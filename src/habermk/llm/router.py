"""Call models in order, with rate limiting, retries and fallback."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from habermk.llm.prompt import SYSTEM_PROMPT, build_messages
from habermk.llm.providers import PROVIDERS, ModelError
from habermk.validate import LLMFormatError, parse_llm_json

log = logging.getLogger(__name__)


class AllModelsFailed(RuntimeError):
    """No model produced a usable answer. Keep the story pending; never post."""


@dataclass
class ModelSpec:
    id: str                       # "provider:model"
    min_interval_s: float = 0
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def provider(self) -> str:
        return self.id.split(":", 1)[0]

    @property
    def model(self) -> str:
        return self.id.split(":", 1)[1]


class Router:
    def __init__(self, specs: list[ModelSpec], temperature: float = 0.2,
                 providers: dict[str, Any] | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 max_wait_s: float = 90):
        self.specs = specs
        self.temperature = temperature
        self._providers = providers if providers is not None else {}
        self._sleep = sleep
        self._clock = clock
        self._last_call: dict[str, float] = {}
        self.max_wait_s = max_wait_s

    @classmethod
    def from_config(cls, llm_cfg: dict[str, Any], only: list[str] | None = None) -> "Router":
        specs = [ModelSpec(**m) for m in llm_cfg["models"]]
        if only is not None:
            by_id = {s.id: s for s in specs}
            specs = [by_id.get(i, ModelSpec(id=i)) for i in only]
        return cls(specs, temperature=llm_cfg.get("temperature", 0.2))

    def _provider(self, name: str):
        if name not in self._providers:
            self._providers[name] = PROVIDERS[name]()
        return self._providers[name]

    def _throttle(self, spec: ModelSpec) -> None:
        last = self._last_call.get(spec.id)
        if last is not None:
            wait = spec.min_interval_s - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_call[spec.id] = self._clock()

    def call_one(self, spec: ModelSpec, headline: str, outlet: str, text: str) -> dict[str, Any]:
        """One model, up to 2 attempts. Raises ModelError / LLMFormatError."""
        messages = build_messages(headline, outlet, text)
        last_error: Exception | None = None
        for attempt in range(2):
            self._throttle(spec)
            try:
                raw = self._provider(spec.provider).complete(
                    spec.model, SYSTEM_PROMPT, messages, self.temperature, spec.params
                )
                return parse_llm_json(raw)
            except ModelError as e:
                last_error = e
                if not e.retryable or attempt == 1:
                    raise
                self._sleep(min(e.retry_after, self.max_wait_s))
            except LLMFormatError as e:
                last_error = e
                if attempt == 1:
                    raise
        raise last_error  # pragma: no cover

    def generate(self, headline: str, outlet: str, text: str) -> tuple[dict[str, Any], str]:
        """First model that answers wins. Returns (result, model_id)."""
        failures = []
        for spec in self.specs:
            try:
                return self.call_one(spec, headline, outlet, text), spec.id
            except (ModelError, LLMFormatError) as e:
                log.warning("model %s failed: %s", spec.id, e)
                failures.append(f"{spec.id}: {e}")
        raise AllModelsFailed("; ".join(failures))
