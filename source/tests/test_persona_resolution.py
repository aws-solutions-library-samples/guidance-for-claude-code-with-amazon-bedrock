# ABOUTME: Unit + fixture-parity tests for the Python shared persona resolver.
# ABOUTME: Drives resolve_persona over tests/fixtures/persona_resolution_cases.json (the parity oracle).

"""Tests for ``claude_code_with_bedrock.persona_resolution.resolve_persona`` (spec §4.3)."""

import json
from pathlib import Path

import pytest

from claude_code_with_bedrock.persona_resolution import resolve_persona

FIXTURES = Path(__file__).parent / "fixtures" / "persona_resolution_cases.json"


def _load_cases() -> list[dict]:
    with open(FIXTURES, encoding="utf-8") as f:
        return json.load(f)


def _name(persona: dict | None) -> str | None:
    """Map a resolved persona (or None) to its name for comparison with fixtures."""
    return persona["name"] if persona is not None else None


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["name"])
def test_resolution_matches_shared_fixture(case):
    """The resolver returns the persona the shared parity fixture expects."""
    result = resolve_persona(case["groups"], case["personas"], case["fallback"])
    assert _name(result) == case["expected"]


class TestResolvePersonaDirect:
    """Direct unit assertions independent of the fixture file."""

    PERSONAS = [
        {"name": "engineering", "group": "eng-team"},
        {"name": "sales", "group": "sales-team"},
    ]

    def test_returns_the_persona_object_not_just_name(self):
        """A match returns the same dict object from the input list."""
        result = resolve_persona(["eng-team"], self.PERSONAS, None)
        assert result is self.PERSONAS[0]

    def test_declared_order_is_precedence(self):
        """When a user is in two persona groups, the first declared wins."""
        result = resolve_persona({"sales-team", "eng-team"}, self.PERSONAS, None)
        assert result["name"] == "engineering"

    def test_accepts_a_set_for_groups(self):
        """user_groups may be a set, not only a list."""
        result = resolve_persona({"sales-team"}, self.PERSONAS, None)
        assert result["name"] == "sales"

    def test_scalar_string_groups_claim_matches_like_go(self):
        """A scalar (non-list) groups claim must match the whole string, not its chars.

        Parity contract (spec §4.3 / credential-helper-parity.md): the Go resolver's
        jwt.GetStringSlice normalizes a scalar claim ("eng-team") to a single-element
        slice and matches the persona. A naive ``set("eng-team")`` would instead iterate
        the string into characters {'e','n','g',...} and match nothing — diverging from
        Go. This pins the wrap-not-iterate behavior so the two implementations agree on
        the scalar shape too (the shared fixture types `groups` as a list and can't
        exercise it).
        """
        result = resolve_persona("eng-team", self.PERSONAS, None)
        assert result is not None and result["name"] == "engineering"

    def test_scalar_string_no_match_is_not_a_substring_match(self):
        """A scalar claim must compare by full-string equality, not character membership.

        Guards the inverse of the previous test: a scalar that happens to share
        characters with a group value (e.g. 'e','n','g' are in 'eng-team') must NOT
        match — only the exact group string does.
        """
        assert resolve_persona("eng", self.PERSONAS, None) is None

    def test_no_match_no_fallback_returns_none(self):
        assert resolve_persona(["contractors"], self.PERSONAS, None) is None

    def test_no_match_with_fallback_returns_fallback(self):
        result = resolve_persona(["contractors"], self.PERSONAS, "sales")
        assert result["name"] == "sales"

    def test_unknown_fallback_name_returns_none(self):
        assert resolve_persona(["contractors"], self.PERSONAS, "nope") is None

    def test_empty_personas_returns_none(self):
        assert resolve_persona(["eng-team"], [], None) is None

    def test_empty_personas_with_fallback_still_none(self):
        """A fallback name cannot resolve against an empty persona list."""
        assert resolve_persona(["eng-team"], [], "engineering") is None

    def test_match_takes_precedence_over_fallback(self):
        """A real group match wins even when a different fallback is configured."""
        result = resolve_persona(["sales-team"], self.PERSONAS, "engineering")
        assert result["name"] == "sales"
