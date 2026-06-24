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

    def test_name_with_spaces_is_rejected(self):
        # A name with a space sanitizes lossily into a logical id; reject it up front
        # with a clear message rather than letting it surface as a CFN error later.
        errors = validate_personas([_valid_persona(name="data science")], None)
        assert any("not DNS/IAM-safe" in e for e in errors)

    def test_name_with_non_ascii_is_rejected(self):
        # Non-ASCII names yield CloudFormation logical ids that fail the
        # ^[A-Za-z0-9]+$ rule (E3001) once title-cased — reject before render.
        errors = validate_personas([_valid_persona(name="écran")], None)
        assert any("not DNS/IAM-safe" in e for e in errors)

    def test_name_with_dot_is_rejected(self):
        errors = validate_personas([_valid_persona(name="eng.team")], None)
        assert any("not DNS/IAM-safe" in e for e in errors)

    def test_hyphenated_and_numeric_names_are_valid(self):
        # The documented-safe shapes must keep validating cleanly.
        assert validate_personas([_valid_persona(name="data-science")], None) == []
        assert validate_personas([_valid_persona(name="tier1")], None) == []

    def test_distinct_names_colliding_on_logical_id_are_rejected(self):
        # L4: two DNS/IAM-safe but DISTINCT names that sanitize to the same CFN logical
        # id (`data-science` and `data--science` both -> `DataScience`) would silently
        # overwrite resources in the rendered stack. validate_personas must flag it
        # upfront (the renderer also raises, but later).
        personas = [
            _valid_persona(name="data-science", group="ds-team"),
            _valid_persona(name="data--science", group="ds2-team"),
        ]
        errors = validate_personas(personas, None)
        assert any("same CloudFormation logical id" in e and "DataScience" in e for e in errors), errors

    def test_logical_id_collision_message_names_both_personas(self):
        personas = [
            _valid_persona(name="data-science", group="a"),
            _valid_persona(name="data--science", group="b"),
        ]
        errors = validate_personas(personas, None)
        collision = [e for e in errors if "same CloudFormation logical id" in e]
        assert collision and "'data-science'" in collision[0] and "'data--science'" in collision[0]

    def test_distinct_non_colliding_names_pass(self):
        # Guard against a false-positive: distinct names with distinct logical ids
        # must NOT be flagged as a collision.
        personas = [
            _valid_persona(name="data-science", group="a"),
            _valid_persona(name="data-engineering", group="b"),
        ]
        assert validate_personas(personas, None) == []

    def test_logical_id_collision_consistent_with_renderer(self):
        # The validator's collision detection must use the SAME mapping the renderer
        # emits — assert the colliding pair actually collides in persona_template.
        from claude_code_with_bedrock.persona_template import _logical_id

        assert _logical_id("data-science") == _logical_id("data--science")

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

    def test_budget_without_cost_tags_is_rejected(self):
        """A budgeted persona needs cost_tags to scope its AWS Budget.

        The budgets renderer (_cost_filters_for_persona) raises on a budgeted
        persona with no cost_tags; without this upfront check that surfaced one
        command later as a `ccwb deploy` failure. validate_personas must catch it
        so the wizard and a hand-edited config.yaml both fail at save/validate time.
        """
        errors = validate_personas([_valid_persona(budget_amount_usd=100.0, cost_tags={})], None)
        assert any("budget_amount_usd but no cost_tags" in e for e in errors)

    def test_budget_with_cost_tags_is_valid(self):
        persona = _valid_persona(budget_amount_usd=100.0, cost_tags={"Team": "Engineering"})
        assert validate_personas([persona], None) == []

    def test_no_budget_no_cost_tags_is_valid(self):
        """A persona without a budget needs no cost_tags."""
        persona = _valid_persona()
        persona.pop("cost_tags", None)
        assert validate_personas([persona], None) == []

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
