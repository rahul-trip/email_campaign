"""Reading JSON out of a model's reply.

Models wrap JSON in code fences or add a sentence of commentary even when told not to, so the
parser takes the outermost ``{...}`` and nothing else. A reply that is broken, the wrong shape or
cut off is asked for once more, with a reminder, because the second try usually works and a
failed lead costs a whole stage to retry.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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


def _ask[T](
    llm: LlmClient, system: str, user: str, temperature: float | None, read: Callable[[str], T]
) -> T:
    """One model call whose reply ``read`` turns into a value, asked a second time with a
    reminder when the first reply was broken, mis-shaped or cut off. ``read`` raises
    ``ProviderError`` for a reply it cannot use. Rate limits and other errors are not retried
    here, because the shared HTTP client already handles those."""

    def once(prompt: str) -> T:
        return read(llm.complete(system, prompt, json_mode=True, temperature=temperature).text)

    try:
        return once(user)
    except ProviderError as error:
        if error.retryable or not _worth_asking_again(str(error)):
            raise
        why = "it was cut off" if _CUT_OFF in str(error) else str(error).split(": ", 1)[-1][:120]
        return once(user + _REMINDER.format(why=why))


def ask_object(
    llm: LlmClient, system: str, user: str, *, temperature: float | None = None
) -> dict[str, Any]:
    """A model call whose reply must be a JSON object, of any shape. The reply is not capped
    here: the model's configured limit applies, because a reasoning model spends tokens
    thinking first and a cap chosen for the answer alone cuts the answer off."""
    return _ask(llm, system, user, temperature, lambda text: parse_json_object(llm.name, text))


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
    or cut-off reply is asked for once more (``ask_object`` explains why).
    """

    def read(text: str) -> M:
        try:
            return model.model_validate(parse_json_object(llm.name, text))
        except ValidationError as error:
            message = f"the reply did not have the expected shape: {error}"
            raise ProviderError(llm.name, message) from None

    return _ask(llm, system, user, temperature, read)


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
