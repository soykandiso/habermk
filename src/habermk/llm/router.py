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


class AllModelsCooling(AllModelsFailed):
    """Every model is resting after a long rate limit (e.g. a used-up daily free
    quota). Not the story's fault: it must not count as a failed attempt."""


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
                 max_wait_s: float = 90,
                 wall: Callable[[], float] = time.time):
        self.specs = specs
        self.temperature = temperature
        self._providers = providers if providers is not None else {}
        self._sleep = sleep
        self._clock = clock
        self._wall = wall
        self._last_call: dict[str, float] = {}
        self.max_wait_s = max_wait_s
        # model id -> epoch seconds until which it is not called (kept in state)
        self.cooldown_until: dict[str, float] = {}

    def active_cooldowns(self) -> dict[str, float]:
        now = self._wall()
        return {k: v for k, v in self.cooldown_until.items() if v > now}

    def available(self) -> list[ModelSpec]:
        now = self._wall()
        return [s for s in self.specs if self.cooldown_until.get(s.id, 0) <= now]

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
                if e.retryable and e.retry_after > self.max_wait_s:
                    # e.g. the daily free quota is used up: rest this model instead
                    # of sleeping, and skip it in the next runs too
                    self.cooldown_until[spec.id] = self._wall() + e.retry_after
                    log.warning("model %s rests for %.0f s", spec.id, e.retry_after)
                    raise
                if not e.retryable or attempt == 1:
                    raise
                self._sleep(e.retry_after)
            except LLMFormatError as e:
                last_error = e
                if attempt == 1:
                    raise
        raise last_error  # pragma: no cover

    def generate(self, headline: str, outlet: str, text: str) -> tuple[dict[str, Any], str]:
        """First model that answers wins. Returns (result, model_id)."""
        specs = self.available()
        if not specs:
            raise AllModelsCooling("every model is resting after a rate limit")
        failures = []
        for spec in specs:
            try:
                return self.call_one(spec, headline, outlet, text), spec.id
            except (ModelError, LLMFormatError) as e:
                log.warning("model %s failed: %s", spec.id, e)
                failures.append(f"{spec.id}: {e}")
        if not self.available():
            raise AllModelsCooling("; ".join(failures))
        raise AllModelsFailed("; ".join(failures))
