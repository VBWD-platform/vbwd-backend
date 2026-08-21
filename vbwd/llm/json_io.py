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
from typing import Any, Callable, Dict, Optional, Set, Tuple

from vbwd.llm.errors import InvalidJsonError

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_REPAIR_INSTRUCTION = (
    "Your previous reply was not valid JSON matching the required shape. Reply "
    "with ONE valid JSON object only, no prose and no Markdown fences."
)


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


def _is_json_schema_style(json_schema: dict) -> bool:
    """A ``properties`` sub-dict marks the full JSON-schema convention."""
    return isinstance(json_schema.get("properties"), dict)


def schema_keys(json_schema: Optional[dict]) -> Tuple[Set[str], Set[str]]:
    """Return ``(expected_keys, required_keys)`` for either schema convention.

    JSON-schema style (a ``properties`` sub-dict): expected keys are
    ``properties.keys()`` and required keys are ``schema["required"]``. Flat
    style: every top-level key is expected and none is individually required.
    A ``None``/empty schema yields ``(set(), set())`` — "any object".
    """
    if not json_schema:
        return set(), set()
    if _is_json_schema_style(json_schema):
        properties = json_schema["properties"]
        expected_keys = set(properties.keys())
        required_keys = set(json_schema.get("required", []))
        return expected_keys, required_keys
    return set(json_schema.keys()), set()


def _render_type_token(field_type: Any) -> str:
    """Map one schema type value to a readable token (``'string|null'`` etc.)."""
    if isinstance(field_type, dict):
        type_value = field_type.get("type", "string")
        if isinstance(type_value, list):
            return "|".join(str(part).strip().lower() for part in type_value)
        return str(type_value).strip().lower()
    return str(field_type).strip().lower()


def schema_field_types(json_schema: Optional[dict]) -> Dict[str, str]:
    """Map each expected field to a readable type token, in schema order.

    JSON-schema style renders ``{"type": "string"}`` -> ``"string"`` and
    ``{"type": ["string", "null"]}`` -> ``"string|null"``. Flat style passes
    the token through, lower-cased/stripped. Empty/None schema -> ``{}``.
    """
    if not json_schema:
        return {}
    if _is_json_schema_style(json_schema):
        properties = json_schema["properties"]
        return {name: _render_type_token(spec) for name, spec in properties.items()}
    return {name: _render_type_token(token) for name, token in json_schema.items()}


def object_matches_schema(obj: dict, json_schema: Optional[dict]) -> bool:
    """Return whether ``obj`` satisfies the schema's expected/required keys.

    With no expected keys (empty/None schema) any object matches. Otherwise a
    match needs every required key present AND at least one expected key
    present — the latter clause rejects free-form wrappers like
    ``{"response": "..."}`` when none of the schema's keys appear.
    """
    expected_keys, required_keys = schema_keys(json_schema)
    if not expected_keys:
        return True
    if not required_keys.issubset(obj.keys()):
        return False
    return bool(expected_keys & obj.keys())


def render_schema_instruction(json_schema: Optional[dict]) -> Optional[str]:
    """Return a one-line instruction naming the exact keys and their types.

    ``None`` when the schema has no expected keys. Keys iterate in the schema's
    own insertion order (deterministic, not sorted). The trailing "required"
    sentence is omitted when no key is required.
    """
    field_types = schema_field_types(json_schema)
    if not field_types:
        return None
    key_shape = ", ".join(
        f'"{name}": {type_token}' for name, type_token in field_types.items()
    )
    instruction = (
        "Reply with ONLY a single JSON object (no prose, no Markdown fences) "
        f"with EXACTLY these keys: {{{key_shape}}}."
    )
    _expected_keys, required_keys = schema_keys(json_schema)
    if required_keys:
        ordered_required = [
            name for name in field_types.keys() if name in required_keys
        ]
        instruction += " These keys are required: " + ", ".join(ordered_required) + "."
    return instruction


def request_valid_json(
    generate_text: Callable[[Optional[str]], str],
    *,
    json_schema: Optional[dict],
    max_attempts: int,
) -> dict:
    """Call ``generate_text`` until it yields a schema-matching JSON object.

    The passed ``json_schema`` is ALWAYS enforced, provider-agnostically. On
    the FIRST attempt ``generate_text`` receives the rendered schema
    instruction (or ``None`` when the schema is empty/``None``), so the model
    learns the required shape up front. A reply is accepted only when it parses
    to a JSON object AND :func:`object_matches_schema` holds. On rejection every
    retry re-states the schema instruction joined with the repair sentence.
    After ``max_attempts`` failures an :class:`InvalidJsonError` is raised. A
    ``None``/empty schema means "any object" (legacy behaviour: first-attempt
    instruction is ``None`` and any object is accepted).
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    schema_instruction = render_schema_instruction(json_schema)
    instruction: Optional[str] = schema_instruction
    for _attempt_index in range(max_attempts):
        raw_text = generate_text(instruction)
        parsed_object = parse_json_object(raw_text)
        if parsed_object is not None and object_matches_schema(
            parsed_object, json_schema
        ):
            return parsed_object
        if schema_instruction:
            instruction = f"{schema_instruction}\n\n{_REPAIR_INSTRUCTION}"
        else:
            instruction = _REPAIR_INSTRUCTION

    raise InvalidJsonError(
        f"Model did not return valid JSON after {max_attempts} attempt(s)"
    )
