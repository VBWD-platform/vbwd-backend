"""JSON parsing, cleaning, validation and the repair/retry loop (S97).

Language models asked for JSON frequently wrap the object in a ```json fenced
block or emit a leading prose sentence. This module isolates the "coax a clean
JSON object out of a model" behaviour so both LLM adapters share one home for
it (DRY), and exposes the retry loop that re-prompts the model up to a
configured number of attempts before giving up with an :class:`InvalidJsonError`.

Pure standard-library; no provider SDK, no network, no filesystem. Copied into
core from the cms-ai LoopForge engine so the core LLM client owns the same
JSON-repair behaviour without importing a plugin (core stays agnostic).
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from vbwd.llm.errors import InvalidJsonError

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def clean_json_text(raw_text: str) -> str:
    """Strip Markdown ```json fences and surrounding whitespace from ``raw_text``."""
    if raw_text is None:
        return ""
    return _FENCE_PATTERN.sub("", raw_text).strip()


def parse_json_object(raw_text: str) -> Optional[dict]:
    """Return the parsed JSON object, or ``None`` if it is not a valid object.

    A valid result is always a JSON *object* (``dict``); a bare array, number
    or string is treated as invalid for the client's structured-JSON purposes.
    """
    cleaned_text = clean_json_text(raw_text)
    if not cleaned_text:
        return None
    try:
        parsed_value = json.loads(cleaned_text)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed_value, dict):
        return None
    return parsed_value


def request_valid_json(
    generate_text: Callable[[Optional[str]], str],
    *,
    json_schema: Optional[dict],
    max_attempts: int,
) -> dict:
    """Call ``generate_text`` until it yields a valid JSON object.

    ``generate_text`` is invoked with an optional repair instruction: ``None``
    on the first attempt, and a short re-prompt string on later attempts when
    the previous output failed to parse. After ``max_attempts`` invalid
    responses an :class:`InvalidJsonError` is raised. ``json_schema`` only
    enforces JSON-shape correctness (the value is an object); a ``None`` schema
    means "any object".
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    repair_instruction: Optional[str] = None
    for _attempt_index in range(max_attempts):
        raw_text = generate_text(repair_instruction)
        parsed_object = parse_json_object(raw_text)
        if parsed_object is not None:
            return parsed_object
        repair_instruction = (
            "Your previous reply was not valid JSON. Reply with ONE valid "
            "JSON object only, no prose and no Markdown fences."
        )

    raise InvalidJsonError(
        f"Model did not return valid JSON after {max_attempts} attempt(s)"
    )
