"""A chat-completions client for any OpenAI-compatible endpoint.

Anthropic, OpenAI, Gemini, GitHub Copilot, Ollama and hosts such as Groq or Together all accept
the same request shape, so one adapter covers them and a preset supplies each one's address and
quirks. Ported from the legacy ``agent/providers/copywriter/llm_copywriter.py`` with the same
presets; the difference is that it now returns token counts, which the meter turns into cost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from outbound.providers.errors import ProviderError
from outbound.providers.http import HttpClient, require_api_key
from outbound.providers.ports import LlmResult

LLM_TIMEOUT_SECONDS = 90.0  # a long reply from a large model is slow, not broken


@dataclass(frozen=True)
class Preset:
    base_url: str
    needs_key: bool = True
    json_mode: bool = True  # whether the endpoint accepts ``response_format``
    headers: dict[str, str] = field(default_factory=dict)


PRESETS: dict[str, Preset] = {
    # Anthropic's compatibility layer ignores ``response_format``; the prompt asks for JSON.
    "anthropic": Preset("https://api.anthropic.com/v1", json_mode=False),
    "openai": Preset("https://api.openai.com/v1"),
    "gemini": Preset("https://generativelanguage.googleapis.com/v1beta/openai"),
    "ollama": Preset("http://localhost:11434/v1", needs_key=False),
    # Copilot's endpoint also wants these two headers or it rejects the request.
    "github_copilot": Preset(
        "https://api.githubcopilot.com",
        json_mode=False,
        headers={"Editor-Version": "vscode/1.85.0", "Copilot-Integration-Id": "vscode-chat"},
    ),
    "openai_compatible": Preset(""),  # the caller must supply base_url
}


class OpenAiCompatibleLlm:
    def __init__(
        self,
        preset: str,
        model: str,
        api_key: str = "",
        *,
        base_url: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4_000,
        reasoning_effort: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self.name = preset
        selected = PRESETS.get(preset)
        if selected is None:
            raise ProviderError(preset, f"unknown LLM provider; choose from {sorted(PRESETS)}")
        if not model:
            raise ProviderError(preset, "no model is set (LLM_MODEL)")
        address = base_url or selected.base_url
        if not address:
            raise ProviderError(preset, "this provider has no default address; set LLM_BASE_URL")

        headers = dict(selected.headers)
        if selected.needs_key:
            headers["Authorization"] = f"Bearer {require_api_key(preset, api_key)}"

        self.model = model
        self._json_mode = selected.json_mode
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._reasoning_effort = reasoning_effort.strip().lower()
        self._http = HttpClient(
            preset,
            address,
            headers=headers,
            timeout=LLM_TIMEOUT_SECONDS,
            client=client,
        )

    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LlmResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self._max_tokens,
        }
        if json_mode and self._json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._reasoning_effort:
            body["reasoning"] = {"effort": self._reasoning_effort}
        payload = self._http.post_object("/chat/completions", body)
        return self._parse(payload)

    def _parse(self, payload: Any) -> LlmResult:
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(self.name, "unexpected reply shape from the model") from None
        if payload["choices"][0].get("finish_reason") == "length":
            # Reasoning models spend output tokens thinking first, so a low cap cuts the answer.
            raise ProviderError(
                self.name, "the reply was cut off at the token limit; raise LLM_MAX_TOKENS"
            )
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(self.name, "the model returned an empty reply")
        usage = payload.get("usage") or {}
        return LlmResult(
            text=text,
            provider=self.name,
            model=str(payload.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )
