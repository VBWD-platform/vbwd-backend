"""RED tests for schema-enforcing JSON I/O (core LLM, S97).

``request_valid_json`` must ALWAYS enforce a passed ``json_schema``,
provider-agnostically: it communicates the required shape to the model up
front and rejects any object that does not match the schema, re-prompting the
schema on every retry. Both schema conventions are supported:

* flat/lightweight ``{"title": "string", "city": "string|null"}``
* full JSON-schema ``{"type": "object", "properties": {...}, "required": [...]}``

A ``None``/empty schema keeps legacy "any object" behaviour.

The helpers are pure stdlib (no SDK, no network, no filesystem) so a small
stub ``generate_text`` that returns queued canned strings and records the
instruction it was called with drives the whole loop.
"""
import pytest

from vbwd.llm.errors import InvalidJsonError
from vbwd.llm.json_io import (
    object_matches_schema,
    render_schema_instruction,
    request_valid_json,
    schema_field_types,
    schema_keys,
)


class _StubGenerator:
    """Return queued canned strings, recording each instruction argument."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.instructions = []

    def __call__(self, instruction):
        self.instructions.append(instruction)
        return self._replies.pop(0)


_FLAT_SCHEMA = {"title": "string", "city": "string|null"}

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "suggested_kind": {"type": ["string", "null"]},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary"],
}


# --------------------------------------------------------------------------- #
# schema_keys
# --------------------------------------------------------------------------- #
def test_schema_keys_flat_all_expected_none_required():
    expected, required = schema_keys(_FLAT_SCHEMA)
    assert expected == {"title", "city"}
    assert required == set()


def test_schema_keys_json_schema_properties_and_required():
    expected, required = schema_keys(_JSON_SCHEMA)
    assert expected == {"summary", "suggested_kind", "tags"}
    assert required == {"summary"}


def test_schema_keys_none_and_empty_are_empty():
    assert schema_keys(None) == (set(), set())
    assert schema_keys({}) == (set(), set())


# --------------------------------------------------------------------------- #
# schema_field_types
# --------------------------------------------------------------------------- #
def test_schema_field_types_flat_passes_token_through():
    assert schema_field_types(_FLAT_SCHEMA) == {
        "title": "string",
        "city": "string|null",
    }


def test_schema_field_types_json_schema_renders_tokens():
    assert schema_field_types(_JSON_SCHEMA) == {
        "summary": "string",
        "suggested_kind": "string|null",
        "tags": "array",
    }


def test_schema_field_types_none_is_empty():
    assert schema_field_types(None) == {}


# --------------------------------------------------------------------------- #
# object_matches_schema
# --------------------------------------------------------------------------- #
def test_object_matches_any_object_when_no_expected_keys():
    assert object_matches_schema({"anything": 1}, None) is True
    assert object_matches_schema({}, {}) is True


def test_object_matches_flat_needs_one_expected_key():
    assert object_matches_schema({"title": "x"}, _FLAT_SCHEMA) is True
    assert object_matches_schema({"response": "x"}, _FLAT_SCHEMA) is False


def test_object_matches_json_schema_needs_required_and_one_expected():
    assert object_matches_schema({"summary": "ok"}, _JSON_SCHEMA) is True
    # missing required key -> rejected even though it has no expected key
    assert object_matches_schema({"message": "hi"}, _JSON_SCHEMA) is False


def test_object_missing_all_required_is_rejected_even_with_expected_key():
    # has an expected non-required key (tags) but is missing required (summary)
    assert object_matches_schema({"tags": []}, _JSON_SCHEMA) is False


# --------------------------------------------------------------------------- #
# render_schema_instruction
# --------------------------------------------------------------------------- #
def test_render_instruction_none_for_empty_schema():
    assert render_schema_instruction(None) is None
    assert render_schema_instruction({}) is None


def test_render_instruction_flat_no_required_sentence():
    instruction = render_schema_instruction(_FLAT_SCHEMA)
    assert instruction is not None
    assert '"title": string' in instruction
    assert '"city": string|null' in instruction
    assert "required" not in instruction.lower()


def test_render_instruction_json_schema_names_keys_and_required():
    instruction = render_schema_instruction(_JSON_SCHEMA)
    assert instruction is not None
    # keys iterate in schema insertion order (deterministic, not sorted)
    assert (
        '{"summary": string, "suggested_kind": string|null, "tags": array}'
        in instruction
    )
    assert "These keys are required: summary." in instruction


# --------------------------------------------------------------------------- #
# request_valid_json — the loop
# --------------------------------------------------------------------------- #
def test_flat_schema_reprompts_wrong_shape_then_returns_correct():
    generator = _StubGenerator(
        ['{"response": "x"}', '{"title": "Berlin", "city": "Berlin"}']
    )
    result = request_valid_json(generator, json_schema=_FLAT_SCHEMA, max_attempts=3)
    assert result == {"title": "Berlin", "city": "Berlin"}

    schema_instruction = render_schema_instruction(_FLAT_SCHEMA)
    # FIRST call receives the rendered schema instruction up front.
    assert generator.instructions[0] == schema_instruction
    # SECOND call receives schema + repair.
    assert schema_instruction in generator.instructions[1]
    assert "not valid JSON matching the required shape" in generator.instructions[1]


def test_json_schema_rejects_missing_required_then_accepts_valid():
    generator = _StubGenerator(
        ['{"message": "hi"}', '{"summary": "done", "tags": ["a"]}']
    )
    result = request_valid_json(generator, json_schema=_JSON_SCHEMA, max_attempts=3)
    assert result == {"summary": "done", "tags": ["a"]}
    assert generator.instructions[0] == render_schema_instruction(_JSON_SCHEMA)


def test_none_schema_first_instruction_is_none_and_any_dict_accepted():
    generator = _StubGenerator(['{"whatever": true}'])
    result = request_valid_json(generator, json_schema=None, max_attempts=3)
    assert result == {"whatever": True}
    assert generator.instructions[0] is None


def test_raises_invalid_json_after_max_attempts_of_wrong_shape():
    generator = _StubGenerator(
        ['{"response": "1"}', '{"response": "2"}', '{"response": "3"}']
    )
    with pytest.raises(InvalidJsonError):
        request_valid_json(generator, json_schema=_FLAT_SCHEMA, max_attempts=3)


def test_max_attempts_below_one_raises_value_error():
    generator = _StubGenerator(['{"title": "x"}'])
    with pytest.raises(ValueError):
        request_valid_json(generator, json_schema=_FLAT_SCHEMA, max_attempts=0)
