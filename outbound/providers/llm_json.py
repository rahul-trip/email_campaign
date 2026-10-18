"""Reading JSON out of a model's reply.

Models wrap JSON in code fences or add a sentence of commentary even when told not to, so the
parser takes the outermost ``{...}`` and nothing else.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from outbound.providers.errors import ProviderError
from outbound.providers.ports import LlmClient


def parse_json_object(provider: str, text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ProviderError(provider, "the model's reply contained no JSON object")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError(provider, f"the model's reply was not valid JSON: {exc.msg}") from None
    if not isinstance(parsed, dict):
        raise ProviderError(provider, "the model's reply was JSON but not an object")
    return parsed


def ask_json[M: BaseModel](llm: LlmClient, system: str, user: str, model: type[M]) -> M:
    """One model call whose reply must be a JSON object of the given shape."""
    reply = llm.complete(system, user, json_mode=True)
    try:
        return model.model_validate(parse_json_object(llm.name, reply.text))
    except ValidationError as error:
        message = f"the reply did not have the expected shape: {error}"
        raise ProviderError(llm.name, message) from None
