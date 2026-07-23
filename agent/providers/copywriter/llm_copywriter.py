"""agent/providers/copywriter/llm_copywriter.py — Generic LLM-based copywriter.

SDK-free by design: a single POST to an OpenAI-compatible /chat/completions
endpoint. Anthropic, OpenAI, Gemini, GitHub Copilot, Ollama (local), and any
OpenAI-compatible host (Groq, Together, ...) all expose this shape, so
switching providers is a 2-line config.yaml edit — no new dependency, no new
adapter class.

See system_specification.md Module C for the negative-constraint prompt
directives (banned phrases, structure rules) this adapter must honor.
"""

from __future__ import annotations

import json
import logging
import os
import time

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.config.models import LlmConfig, SenderProfile
from agent.domain.models import Company, Contact
from agent.prompts import build_copywriter_system_prompt, build_copywriter_user_prompt
from agent.providers.discovery.base import ProviderError
from .base import CopyOutput, CopywriterProvider

logger = logging.getLogger(__name__)

# Each preset supplies a default base_url + the env var holding its API key.
# llm.base_url / llm.key_env in config.yaml override these when set (and are
# REQUIRED for "openai_compatible", which has no default host).
#
# extra_headers are provider quirks that don't fit the plain
# "Authorization: Bearer <key>" shape used by everyone else — currently only
# GitHub Copilot, whose /chat/completions endpoint additionally requires an
# Editor-Version and Copilot-Integration-Id header to accept the request.
_PROVIDER_PRESETS: dict[str, dict[str, object]] = {
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "key_env": "ANTHROPIC_API_KEY",
        "extra_headers": {},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "extra_headers": {},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "extra_headers": {},
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "key_env": "",  # local, no auth
        "extra_headers": {},
    },
    "github_copilot": {
        "base_url": "https://api.githubcopilot.com",
        "key_env": "COPILOT_API_KEY",
        "extra_headers": {
            "Editor-Version": "vscode/1.85.0",
            "Copilot-Integration-Id": "vscode-chat",
        },
    },
    "openai_compatible": {
        "base_url": "",  # user MUST set llm.base_url
        "key_env": "LLM_API_KEY",
        "extra_headers": {},
    },
}


def _parse_copy_json(text: str) -> dict:
    """Extract and parse the JSON object from an LLM response.

    Defensive because models frequently wrap JSON in ```json fences or add
    stray commentary despite instructions not to.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line (``` or ```json) and any trailing fence.
        parts = stripped.split("```")
        stripped = parts[1] if len(parts) > 1 else stripped
        stripped = stripped.removeprefix("json").strip()

    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ProviderError(f"LLM response contained no JSON object: {text[:200]!r}")

    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(f"LLM response was not valid JSON: {exc}") from exc


class LlmCopywriter(CopywriterProvider):
    """Provider-agnostic LLM copywriter using the OpenAI-compatible chat API.

    Works with any provider in _PROVIDER_PRESETS, or a fully custom
    "openai_compatible" host via llm.base_url / llm.key_env in config.yaml.
    """

    def __init__(self, llm: LlmConfig, sender: SenderProfile, per_call_delay_seconds: float = 1.0) -> None:
        preset = _PROVIDER_PRESETS.get(llm.provider)
        if preset is None:
            raise ProviderError(
                f"Unknown llm.provider {llm.provider!r}. Available: {list(_PROVIDER_PRESETS)}"
            )

        base_url = llm.base_url or preset["base_url"]
        if not base_url:
            raise ProviderError(
                f"llm.provider={llm.provider!r} has no default base_url — "
                "set llm.base_url in config.yaml."
            )

        key_env = llm.key_env or preset["key_env"]
        api_key = ""
        if key_env:
            api_key = os.getenv(key_env, "")
            if not api_key:
                raise ProviderError(
                    f"llm.provider={llm.provider!r} requires the {key_env} environment "
                    "variable to be set (in .env or agent/.env)."
                )

        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._extra_headers: dict[str, str] = dict(preset["extra_headers"])  # type: ignore[arg-type]
        self._model = llm.model
        self._temperature = llm.temperature
        self._max_tokens = llm.max_tokens
        self._sender = sender
        self._delay = per_call_delay_seconds

    def write(self, company: Company, contact: Contact, config) -> CopyOutput:  # type: ignore[override]
        system_prompt = build_copywriter_system_prompt(
            signature_name=config.signature_name,
            signature_title=config.signature_title,
        )
        user_prompt = build_copywriter_user_prompt(company, contact, self._sender)

        raw_text = self._call_api(system_prompt, user_prompt)
        if self._delay:
            time.sleep(self._delay)

        payload = _parse_copy_json(raw_text)

        for key in ("pitch_email", "follow_up", "commonalities"):
            if key not in payload:
                raise ProviderError(f"LLM response JSON is missing required key {key!r}: {payload}")

        commonalities = payload["commonalities"]
        if isinstance(commonalities, list):
            commonalities_text = "\n".join(f"• {c}" for c in commonalities)
        else:
            commonalities_text = str(commonalities)

        return CopyOutput(
            pitch_email=str(payload["pitch_email"]),
            follow_up=str(payload["follow_up"]),
            commonalities=commonalities_text,
        )

    @retry(
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _call_api(self, system_prompt: str, user_prompt: str) -> str:
        headers = {"Content-Type": "application/json", **self._extra_headers}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        try:
            resp = requests.post(
                f"{self._base_url}/chat/completions", headers=headers, json=body, timeout=60
            )
        except requests.exceptions.RequestException as exc:
            logger.warning("LLM request error: %s", exc)
            raise

        if resp.status_code == 429:
            raise requests.exceptions.ConnectionError("LLM endpoint rate-limited (429)")
        if resp.status_code >= 500:
            raise requests.exceptions.ConnectionError(f"LLM endpoint server error {resp.status_code}")
        if not resp.ok:
            raise ProviderError(f"LLM endpoint HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"Unexpected LLM response shape: {data}") from exc
