"""Thin wrappers around each AI provider. All return the raw reply text.

Any failure is raised as ModelError so the router can retry or fall back.
API keys come only from environment variables.
"""
from __future__ import annotations

import os
from typing import Any

from habermk.llm.prompt import RESULT_SCHEMA


class ModelError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False, retry_after: float = 0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def _require_key(name: str) -> str:
    key = os.environ.get(name, "").strip()
    if not key:
        raise ModelError(f"{name} is not set", retryable=False)
    return key


class GroqProvider:
    def __init__(self) -> None:
        import groq

        self._groq = groq
        self.client = groq.Groq(api_key=_require_key("GROQ_API_KEY"), max_retries=0, timeout=60)

    def complete(self, model: str, system: str, messages: list[dict], temperature: float,
                 params: dict[str, Any]) -> str:
        g = self._groq
        kwargs: dict[str, Any] = {"response_format": {"type": "json_object"}, **params}
        try:
            resp = self.client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, *messages],
                temperature=temperature,
                max_completion_tokens=2048,
                **kwargs,
            )
        except g.RateLimitError as e:
            wait = float(e.response.headers.get("retry-after", "30") or 30)
            raise ModelError(f"groq rate limit: {e}", retryable=True, retry_after=wait) from e
        except (g.APITimeoutError, g.APIConnectionError, g.InternalServerError) as e:
            raise ModelError(f"groq unavailable: {e}", retryable=True, retry_after=10) from e
        except g.APIError as e:
            raise ModelError(f"groq error: {e}") from e
        return resp.choices[0].message.content or ""


class GeminiProvider:
    def __init__(self) -> None:
        from google import genai

        self._genai = genai
        self.client = genai.Client(api_key=_require_key("GEMINI_API_KEY"))

    def complete(self, model: str, system: str, messages: list[dict], temperature: float,
                 params: dict[str, Any]) -> str:
        from google.genai import errors, types

        contents = [
            types.Content(role="model" if m["role"] == "assistant" else "user",
                          parts=[types.Part(text=m["content"])])
            for m in messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json",
            **params,
        )
        try:
            resp = self.client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as e:
            retryable = e.code == 429 or e.code >= 500
            wait = 30 if e.code == 429 else 10
            raise ModelError(f"gemini {e.code}: {e}", retryable=retryable, retry_after=wait) from e
        except Exception as e:  # network errors surface as httpx exceptions
            raise ModelError(f"gemini unavailable: {e}", retryable=True, retry_after=10) from e
        return resp.text or ""


class AnthropicProvider:
    """Optional paid comparison (Claude). Needs ANTHROPIC_API_KEY."""

    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=_require_key("ANTHROPIC_API_KEY"), max_retries=0)

    def complete(self, model: str, system: str, messages: list[dict], temperature: float,
                 params: dict[str, Any]) -> str:
        a = self._anthropic
        kwargs: dict[str, Any] = {
            "output_config": {"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
            **params,
        }
        if model.startswith("claude-haiku"):
            kwargs["temperature"] = temperature  # newer models reject sampling params
        try:
            resp = self.client.messages.create(
                model=model, max_tokens=2048, system=system, messages=messages, **kwargs,
            )
        except a.RateLimitError as e:
            wait = float(e.response.headers.get("retry-after", "30") or 30)
            raise ModelError(f"anthropic rate limit: {e}", retryable=True, retry_after=wait) from e
        except (a.APITimeoutError, a.APIConnectionError, a.InternalServerError) as e:
            raise ModelError(f"anthropic unavailable: {e}", retryable=True, retry_after=10) from e
        except a.APIError as e:
            raise ModelError(f"anthropic error: {e}") from e
        if resp.stop_reason == "refusal":
            return '{"status":"SKIP","sentence":"","evidence":"","scope":"MK","reason":"model declined"}'
        return next((b.text for b in resp.content if b.type == "text"), "")


PROVIDERS = {"groq": GroqProvider, "gemini": GeminiProvider, "anthropic": AnthropicProvider}
