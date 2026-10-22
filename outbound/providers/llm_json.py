"""Reading JSON out of a model's reply.

Models wrap JSON in code fences or add a sentence of commentary even when told not to, so the
parser takes the outermost ``{...}`` and nothing else. A reply that is broken, the wrong shape or
cut off is asked for once more, with a reminder, because the second try usually works and a
failed lead costs a whole stage to retry.
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


_REMINDER = (
    "\n\nYour last reply could not be used ({why}). Reply again with only the JSON object, as"
    " briefly as you can: no commentary and no long reasoning."
)
_CUT_OFF = "cut off at the token limit"


def _ask_once[M: BaseModel](
    llm: LlmClient, system: str, user: str, model: type[M], temperature: float | None
) -> M:
    reply = llm.complete(system, user, json_mode=True, temperature=temperature)
    try:
        return model.model_validate(parse_json_object(llm.name, reply.text))
    except ValidationError as error:
        message = f"the reply did not have the expected shape: {error}"
        raise ProviderError(llm.name, message) from None


def ask_json[M: BaseModel](
    llm: LlmClient,
    system: str,
    user: str,
    model: type[M],
    *,
    temperature: float | None = None,
) -> M:
    """A model call whose reply must be a JSON object of the given shape.

    ``temperature`` overrides the configured one (extraction wants it low). A broken, mis-shaped
    or cut-off reply is asked for once more; only rate limits and other errors are not retried
    here, because the shared HTTP client already handles those.
    """
    try:
        return _ask_once(llm, system, user, model, temperature)
    except ProviderError as error:
        if error.retryable or not _worth_asking_again(str(error)):
            raise
        why = "it was cut off" if _CUT_OFF in str(error) else str(error).split(": ", 1)[-1][:120]
        return _ask_once(llm, system, user + _REMINDER.format(why=why), model, temperature)


def _worth_asking_again(message: str) -> bool:
    return any(
        part in message
        for part in (
            "not valid JSON",
            "no JSON object",
            "not an object",
            "expected shape",
            _CUT_OFF,
            "empty reply",
        )
    )
