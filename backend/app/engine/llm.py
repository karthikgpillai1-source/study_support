"""LLM gateway.

Phase 1 uses the Gemini API for knowledge extraction only.
Phase 2 optionally points at a self-hosted structured-generation endpoint.

Hard rule for this codebase: **no LLM ever touches planning, scheduling,
difficulty scoring, time estimates or split arithmetic.** Those live in pure
Python so results are reproducible and cheap.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

Provider = Literal["gemini", "local_llm", "none"]

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"[\{\[].*[\}\]]", re.DOTALL)

SYSTEM_INSTRUCTION = (
    "You are a curriculum analysis engine for a study planning platform. "
    "You convert raw academic notes into strict JSON. "
    "You never invent content that is absent from the source text. "
    "You never write prose outside of the JSON object."
)


class LLMError(RuntimeError):
    pass


def parse_json_response(raw: str) -> Any:
    """Best-effort extraction of a JSON value from an LLM response."""
    if not raw or not raw.strip():
        raise LLMError("Empty model response")
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _BARE_JSON_RE.search(text)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Trailing commas are the most common LLM malformation.
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as exc:
                raise LLMError(f"Model response was not valid JSON: {exc}") from exc
    raise LLMError("Model response contained no JSON")


@dataclass(slots=True)
class LLMResult:
    data: Any
    provider: Provider
    model: str
    raw: str = ""


class LLMClient:
    """Thin async facade over the configured providers."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.gemini_timeout_seconds),
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    @property
    def active_provider(self) -> Provider:
        if settings.gemini_api_key.strip():
            return "gemini"
        if settings.local_llm_url.strip():
            return "local_llm"
        return "none"

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str = SYSTEM_INSTRUCTION,
        temperature: float = 0.2,
        max_output_tokens: int = 8192,
    ) -> LLMResult:
        provider = self.active_provider
        if provider == "gemini":
            return await self._gemini(prompt, system, temperature, max_output_tokens)
        if provider == "local_llm":
            return await self._local(prompt, system, temperature, max_output_tokens)
        raise LLMError("No LLM provider is configured")

    # ------------------------------------------------------------------- gemini
    async def _gemini(
        self, prompt: str, system: str, temperature: float, max_output_tokens: int
    ) -> LLMResult:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        headers = {"x-goog-api-key": settings.gemini_api_key}
        client = await self._http()
        try:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500]
            raise LLMError(f"Gemini request failed ({exc.response.status_code}): {detail}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini request failed: {exc}") from exc

        candidates = payload.get("candidates") or []
        if not candidates:
            feedback = payload.get("promptFeedback", {})
            raise LLMError(
                f"Gemini returned no candidates: {feedback.get('blockReason', 'unknown')}"
            )
        parts = (candidates[0].get("content") or {}).get("parts") or []
        raw = "".join(part.get("text", "") for part in parts)
        return LLMResult(
            data=parse_json_response(raw), provider="gemini", model=settings.gemini_model, raw=raw
        )

    # ----------------------------------------------------------------- local llm
    async def _local(
        self, prompt: str, system: str, temperature: float, max_output_tokens: int
    ) -> LLMResult:
        """OpenAI-compatible /v1/chat/completions (llama.cpp, vLLM, Ollama)."""
        url = settings.local_llm_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/v1/chat/completions"
        body = {
            "model": settings.local_llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        client = await self._http()
        try:
            response = await client.post(url, json=body)
            response.raise_for_status()
            payload = response.json()
            raw = payload["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Local LLM request failed: {exc}") from exc
        return LLMResult(
            data=parse_json_response(raw),
            provider="local_llm",
            model=settings.local_llm_model,
            raw=raw,
        )


llm_client = LLMClient()
