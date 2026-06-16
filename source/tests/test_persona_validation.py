# ABOUTME: Tests for validate_personas and the REFERENCE_PERSONAS seed set.
# ABOUTME: Asserts each error class is flagged and the reference personas validate cleanly.

"""Tests for ``claude_code_with_bedrock.persona_validation`` + ``persona_defaults``."""

from claude_code_with_bedrock.persona_defaults import REFERENCE_PERSONAS
from claude_code_with_bedrock.persona_validation import validate_personas


def _valid_persona(**overrides):
    base = {
        "name": "engineering",
        "group": "eng-team",
        "allowed_models": ["anthropic.*"],
        "denied_models": [],
        "enforcement_mode": "block",
    }
    base.update(overrides)
    return base


class TestValidatePersonasHappyPath:
    def test_empty_list_is_valid(self):
        assert validate_personas([], None) == []

    def test_single_valid_persona(self):
        assert validate_personas([_valid_persona()], None) == []

    def test_valid_with_matching_fallback(self):
        personas = [_valid_persona(), _valid_persona(name="sales", group="sales-team")]
        assert validate_personas(personas, "sales") == []

    def test_enforcement_mode_optional(self):
        """enforcement_mode is only checked when present."""
        persona = _valid_persona()
        del persona["enforcement_mode"]
        assert validate_personas([persona], None) == []

    def test_alert_mode_is_valid(self):
        assert validate_personas([_valid_persona(enforcement_mode="alert")], None) == []


class TestValidatePersonasErrors:
    def test_duplicate_names(self):
        personas = [_valid_persona(), _valid_persona(group="other-team")]
        errors = validate_personas(personas, None)
        assert any("Duplicate persona name 'engineering'" in e for e in errors)

    def test_missing_name(self):
        persona = _valid_persona()
        del persona["name"]
        errors = validate_personas([persona], None)
        assert any("missing a non-empty 'name'" in e for e in errors)

    def test_empty_name(self):
        errors = validate_personas([_valid_persona(name="   ")], None)
        assert any("missing a non-empty 'name'" in e for e in errors)

    def test_missing_group(self):
        persona = _valid_persona()
        del persona["group"]
        errors = validate_personas([persona], None)
        assert any("missing a non-empty 'group'" in e for e in errors)

    def test_empty_group(self):
        errors = validate_personas([_valid_persona(group="")], None)
        assert any("missing a non-empty 'group'" in e for e in errors)

    def test_invalid_enforcement_mode(self):
        errors = validate_personas([_valid_persona(enforcement_mode="halt")], None)
        assert any("invalid enforcement_mode 'halt'" in e for e in errors)

    def test_fallback_names_unknown_persona(self):
        errors = validate_personas([_valid_persona()], "ghost")
        assert any("fallback_persona 'ghost' does not name" in e for e in errors)

    def test_allowed_models_non_string_entry(self):
        errors = validate_personas([_valid_persona(allowed_models=["anthropic.*", 123])], None)
        assert any("allowed_models" in e and "non-string" in e for e in errors)

    def test_denied_models_non_string_entry(self):
        errors = validate_personas([_valid_persona(denied_models=[None])], None)
        assert any("denied_models" in e and "non-string" in e for e in errors)

    def test_model_field_not_a_list(self):
        errors = validate_personas([_valid_persona(allowed_models="anthropic.*")], None)
        assert any("allowed_models' must be a list" in e for e in errors)

    def test_non_dict_persona(self):
        errors = validate_personas(["not-a-dict"], None)
        assert any("must be a mapping" in e for e in errors)

    def test_multiple_errors_accumulate(self):
        """Several problems in one call all surface."""
        personas = [
            _valid_persona(name="", group=""),
            _valid_persona(name="dup"),
            _valid_persona(name="dup", enforcement_mode="bad"),
        ]
        errors = validate_personas(personas, "missing")
        # missing name, missing group, duplicate, bad mode, bad fallback => at least 5
        assert len(errors) >= 5


class TestReferencePersonas:
    def test_reference_personas_validate_cleanly(self):
        assert validate_personas(REFERENCE_PERSONAS, None) == []

    def test_reference_persona_names_and_groups(self):
        by_name = {p["name"]: p for p in REFERENCE_PERSONAS}
        assert by_name["engineering"]["group"] == "eng-team"
        assert by_name["sales"]["group"] == "sales-team"

    def test_sales_denies_sonnet_and_opus(self):
        """The restricted persona must deny Sonnet and Opus (bypass-guard precondition)."""
        sales = next(p for p in REFERENCE_PERSONAS if p["name"] == "sales")
        assert sales["allowed_models"] == ["anthropic.*haiku*"]
        assert "anthropic.*sonnet*" in sales["denied_models"]
        assert "anthropic.*opus*" in sales["denied_models"]

    def test_reference_personas_usable_as_fallback(self):
        assert validate_personas(REFERENCE_PERSONAS, "engineering") == []
