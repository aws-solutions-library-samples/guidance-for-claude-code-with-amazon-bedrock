# ABOUTME: Unit tests for the init wizard's persona-based access control section
# ABOUTME: Covers the pure answer->persona transform, the questionary loop, and Profile mapping

"""Tests for persona collection in :class:`InitCommand`.

The full init wizard is far too large to drive end-to-end, so (per the task
design note) the persona logic is factored into two seams that are tested in
isolation:

* :meth:`InitCommand._persona_from_wizard_answers` — a pure transform from raw
  wizard answers to a §4.1 persona dict (parsing rules only).
* :meth:`InitCommand._gather_personas` — the interactive loop, driven here with
  ``questionary`` patched by message-keyed fakes (the pattern used elsewhere in
  ``tests/cli/commands/test_init.py``).

A final test confirms ``_save_configuration`` maps the collected persona fields
onto the :class:`Profile` so they reach ``config.yaml``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from claude_code_with_bedrock.cli.commands import init as init_module
from claude_code_with_bedrock.cli.commands.init import InitCommand


class TestPersonaFromWizardAnswers:
    """The pure answer -> persona dict transform."""

    def test_csv_models_split_into_lists(self):
        persona = InitCommand._persona_from_wizard_answers(
            {
                "name": "eng",
                "group": "eng-team",
                "allowed_models": "anthropic.*, anthropic.*haiku*",
                "denied_models": "anthropic.*opus*",
            }
        )
        assert persona["allowed_models"] == ["anthropic.*", "anthropic.*haiku*"]
        assert persona["denied_models"] == ["anthropic.*opus*"]

    def test_blank_models_become_empty_lists(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "eng", "group": "eng-team", "allowed_models": "", "denied_models": ""}
        )
        assert persona["allowed_models"] == []
        assert persona["denied_models"] == []

    def test_list_models_passed_through_and_trimmed(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "eng", "group": "g", "allowed_models": [" anthropic.* ", ""]}
        )
        assert persona["allowed_models"] == ["anthropic.*"]

    def test_blank_limits_and_budget_become_none(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "eng", "group": "g", "monthly_token_limit": "", "budget_amount_usd": ""}
        )
        assert persona["monthly_token_limit"] is None
        assert persona["budget_amount_usd"] is None

    def test_numeric_limit_and_budget_coerced(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "eng", "group": "g", "monthly_token_limit": "300000000", "budget_amount_usd": "500"}
        )
        assert persona["monthly_token_limit"] == 300000000
        assert isinstance(persona["monthly_token_limit"], int)
        assert persona["budget_amount_usd"] == 500.0
        assert isinstance(persona["budget_amount_usd"], float)

    def test_cost_tags_parsed_from_key_value_string(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "eng", "group": "g", "cost_tags": "Team=Engineering, CostCenter=CC-1001"}
        )
        assert persona["cost_tags"] == {"Team": "Engineering", "CostCenter": "CC-1001"}

    def test_cost_tags_dict_passed_through(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "eng", "group": "g", "cost_tags": {"Team": "Engineering"}}
        )
        assert persona["cost_tags"] == {"Team": "Engineering"}

    def test_malformed_cost_tag_pairs_skipped(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "eng", "group": "g", "cost_tags": "Team=Eng, junk, =novalue, Center=CC1"}
        )
        assert persona["cost_tags"] == {"Team": "Eng", "Center": "CC1"}

    def test_display_name_defaults_to_name(self):
        persona = InitCommand._persona_from_wizard_answers({"name": "engineering", "group": "g"})
        assert persona["display_name"] == "engineering"

    def test_enforcement_mode_defaults_to_block(self):
        persona = InitCommand._persona_from_wizard_answers({"name": "eng", "group": "g"})
        assert persona["enforcement_mode"] == "block"

    def test_strings_are_stripped(self):
        persona = InitCommand._persona_from_wizard_answers(
            {"name": "  eng  ", "group": "  eng-team  ", "display_name": "  Engineering  "}
        )
        assert persona["name"] == "eng"
        assert persona["group"] == "eng-team"
        assert persona["display_name"] == "Engineering"


def _make_questionary_fakes(answers: dict[str, object]):
    """Build message-keyed fake questionary callables.

    *answers* maps a substring of a prompt message to the value its ``.ask()``
    should return. Each of confirm/select/text matches the first key contained
    in the message; unmatched prompts return a safe default (False / None / "").
    """

    def _lookup(message, default):
        text = str(message)
        for needle, value in answers.items():
            if needle in text:
                return value
        return default

    def fake_confirm(message, *a, **k):
        m = MagicMock()
        m.ask.return_value = _lookup(message, False)
        return m

    def fake_select(message, *a, **k):
        m = MagicMock()
        m.ask.return_value = _lookup(message, None)
        return m

    def fake_text(message, *a, **k):
        m = MagicMock()
        m.ask.return_value = _lookup(message, "")
        return m

    return fake_confirm, fake_select, fake_text


class TestGatherPersonas:
    """The interactive loop, with questionary patched."""

    def _run(self, config, answers):
        fake_confirm, fake_select, fake_text = _make_questionary_fakes(answers)
        cmd = InitCommand()
        with (
            patch.object(init_module.questionary, "confirm", fake_confirm),
            patch.object(init_module.questionary, "select", fake_select),
            patch.object(init_module.questionary, "text", fake_text),
        ):
            cmd._gather_personas(config)

    def test_decline_leaves_config_untouched(self):
        config = {}
        self._run(config, {"Configure personas now?": False})
        assert "personas" not in config

    def test_reference_seed_happy_path(self):
        config = {}
        self._run(
            config,
            {
                "Configure personas now?": True,
                "OIDC claim name": "groups",
                "Start from": "reference",
                "Add a custom persona?": False,
                "Fallback persona": "engineering",
            },
        )
        assert config["groups_claim_name"] == "groups"
        assert config["fallback_persona"] == "engineering"
        names = [p["name"] for p in config["personas"]]
        assert names == ["engineering", "sales"]

    def test_reference_seed_is_deep_copied(self):
        """Editing the wizard result must not mutate REFERENCE_PERSONAS."""
        from claude_code_with_bedrock.persona_defaults import REFERENCE_PERSONAS

        config = {}
        self._run(
            config,
            {
                "Configure personas now?": True,
                "OIDC claim name": "groups",
                "Start from": "reference",
                "Add a custom persona?": False,
                "Fallback persona": None,
            },
        )
        config["personas"][0]["name"] = "MUTATED"
        assert REFERENCE_PERSONAS[0]["name"] == "engineering"

    def test_custom_groups_claim_name_stored(self):
        config = {}
        self._run(
            config,
            {
                "Configure personas now?": True,
                "OIDC claim name": "cognito:groups",
                "Start from": "reference",
                "Add a custom persona?": False,
                "Fallback persona": None,
            },
        )
        assert config["groups_claim_name"] == "cognito:groups"
        assert config["fallback_persona"] is None

    def test_validation_error_then_decline_reentry_skips(self):
        """A bad fallback triggers errors; declining re-entry skips cleanly."""
        config = {}
        # fallback names a persona that does not exist -> validate_personas errors.
        self._run(
            config,
            {
                "Configure personas now?": True,
                "OIDC claim name": "groups",
                "Start from": "reference",
                "Add a custom persona?": False,
                "Fallback persona": "nonexistent",
                "Re-enter persona configuration?": False,
            },
        )
        # Skipped: no persona config persisted.
        assert "personas" not in config

    def test_retry_skips_optin_prompt(self):
        """L3: the validation re-prompt must NOT re-ask "Configure personas now?".

        After a validation error the operator chose to re-enter; re-showing the
        opt-in (whose default is now False, since the retry cleared
        config["personas"]) means a reflexive Enter would silently abandon the
        attempt. We prove the opt-in is asked EXACTLY ONCE across a retry: the
        first pass asks it (operator opts in), a bad fallback triggers a re-enter,
        and the second pass must NOT ask it again (the _retry=True bypass).
        """
        # The opt-in is asked on pass 1 only. The fallback select returns a bad name
        # first (validation error -> re-enter), a good one on the retry, so pass 2
        # validates and persists.
        optin_asked = []
        fallback_seq = iter(["nonexistent", "engineering"])

        def fake_confirm(message, *a, **k):
            m = MagicMock()
            if "Configure personas now?" in message:
                optin_asked.append(message)
                m.ask.return_value = True  # opt in on pass 1
            elif "Re-enter persona configuration?" in message:
                m.ask.return_value = True  # choose to re-enter after the error
            else:  # "Add a custom persona?" etc.
                m.ask.return_value = False
            return m

        def fake_select(message, *a, **k):
            m = MagicMock()
            if "Start from" in message:
                m.ask.return_value = "reference"
            elif "Fallback persona" in message:
                m.ask.return_value = next(fallback_seq)  # bad first, good on retry
            else:
                m.ask.return_value = None
            return m

        def fake_text(message, *a, **k):
            m = MagicMock()
            m.ask.return_value = "groups" if "OIDC claim name" in message else ""
            return m

        config = {}
        cmd = InitCommand()
        with (
            patch.object(init_module.questionary, "confirm", fake_confirm),
            patch.object(init_module.questionary, "select", fake_select),
            patch.object(init_module.questionary, "text", fake_text),
        ):
            cmd._gather_personas(config)

        # The opt-in was asked exactly once (pass 1) — the retry skipped it (L3 fix);
        # otherwise it would have been asked twice. The retry then persisted personas.
        assert len(optin_asked) == 1, f"opt-in re-asked on retry: {len(optin_asked)} times"
        assert config.get("fallback_persona") == "engineering"
        assert [p["name"] for p in config["personas"]] == ["engineering", "sales"]


class TestSaveConfigurationPersonaMapping:
    """_save_configuration must route persona fields onto the Profile."""

    def _minimal_config(self, **extra):
        config = {
            "aws": {
                "region": "us-east-1",
                "identity_pool_name": "claude-code-auth",
                "stacks": {},
                "allowed_bedrock_regions": ["us-east-1"],
            },
            "monitoring": {"enabled": True},
            "sso_enabled": True,
        }
        config.update(extra)
        return config

    def test_personas_mapped_onto_profile(self, tmp_path):
        from claude_code_with_bedrock import config as config_module

        personas = [
            {"name": "engineering", "group": "eng-team", "allowed_models": ["anthropic.*"]},
        ]
        cfg = self._minimal_config(
            personas=personas,
            groups_claim_name="cognito:groups",
            fallback_persona="engineering",
            account_budget_amount_usd=2500.0,
        )

        captured = {}

        class FakeConfig:
            def get_profile(self, name):
                return None

            def add_profile(self, profile):
                captured["profile"] = profile

            def set_active_profile(self, name):
                pass

            def save(self):
                pass

        with patch.object(config_module.Config, "load", return_value=FakeConfig()):
            InitCommand()._save_configuration(cfg, "default")

        profile = captured["profile"]
        assert profile.personas == personas
        assert profile.groups_claim_name == "cognito:groups"
        assert profile.fallback_persona == "engineering"
        # #31: account-total budget must flow from config_data → wizard_fields → Profile.
        assert profile.account_budget_amount_usd == 2500.0

    def test_non_persona_config_uses_defaults(self):
        from claude_code_with_bedrock import config as config_module

        cfg = self._minimal_config()  # no persona keys
        captured = {}

        class FakeConfig:
            def get_profile(self, name):
                return None

            def add_profile(self, profile):
                captured["profile"] = profile

            def set_active_profile(self, name):
                pass

            def save(self):
                pass

        with patch.object(config_module.Config, "load", return_value=FakeConfig()):
            InitCommand()._save_configuration(cfg, "default")

        profile = captured["profile"]
        assert profile.personas == []
        assert profile.groups_claim_name == "groups"
        assert profile.fallback_persona is None
        # No account budget configured → None (deploy.py skips the account-total budget).
        assert profile.account_budget_amount_usd is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
