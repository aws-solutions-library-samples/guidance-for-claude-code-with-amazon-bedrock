# ABOUTME: Tests for the bedrock model-selection section of the init wizard
# ABOUTME: Verifies Q3 auto-select falls through to Q4-Q6 tier questions (no early return)

"""Tests for bedrock model selection in the init wizard."""

from unittest.mock import MagicMock, patch

from claude_code_with_bedrock.cli.commands.init import InitCommand


def _make_mock_progress(pre_config: dict | None = None, last_step: str = "monitoring_complete") -> MagicMock:
    """Return a WizardProgress-shaped mock pre-loaded with data from a previous step."""
    progress = MagicMock()
    progress.get_last_step.return_value = last_step
    progress.get_saved_data.return_value = pre_config or {}
    return progress


def _select_side_effect(values: list):
    """
    Return a side_effect function for questionary.select that consumes *values* in order.
    Each questionary.select(...) call returns a mock whose .ask() returns the next value.
    """
    it = iter(values)

    def _factory(*args, **kwargs):
        m = MagicMock()
        m.ask.return_value = next(it)
        return m

    return _factory


def _confirm_side_effect(values: list):
    """Same as _select_side_effect but for questionary.confirm."""
    it = iter(values)

    def _factory(*args, **kwargs):
        m = MagicMock()
        m.ask.return_value = next(it)
        return m

    return _factory


class TestQ3AutoSelectFallsThroughToTierQuestions:
    """Q3 auto-select must not return early — Q4-Q6 must still execute."""

    def test_auto_select_model_with_explicit_sonnet_and_haiku_defaults(self):
        """
        Simulate: Q2=eu, Q3=auto-select, Q4=auto, Q5=sonnet-4-6, Q6=haiku-4-5.
        Expected profile fields:
          selected_model         = None
          default_opus_model     = None   (Q4 auto)
          default_sonnet_model   = "eu.anthropic.claude-sonnet-4-6"
          default_haiku_model    = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
        """
        command = InitCommand()

        # Config already saved at monitoring_complete — bedrock section not yet filled
        pre_config: dict = {
            "okta": {"domain": "test.okta.com", "client_id": "test-client-id"},
            "aws": {
                "region": "eu-central-1",
                "stack_base_name": "claude-code-auth",
                "identity_pool_name": "test-pool",
                "credential_storage": "session",
                "federation_type": "direct",
            },
            "monitoring": {"enabled": False},
            "codebuild": {"enabled": False},
            "distribution": {"enabled": False, "type": None},
        }
        progress = _make_mock_progress(pre_config, last_step="monitoring_complete")

        # questionary.select calls in execution order (monitoring_complete skips okta/aws/monitoring):
        # 1. Distribution method       → "__disabled__"
        # 2. Source region (Q1)        → "eu-central-1"
        # 3. Cross-region profile (Q2) → "eu"
        # 4. Claude model (Q3)         → "__auto__"  ← the key branch under test
        # 5. Default Opus (Q4)         → "__auto__"
        # 6. Default Sonnet (Q5)       → "sonnet-4-6"
        # 7. Default Haiku (Q6)        → "haiku-4-5"
        select_values = ["__disabled__", "eu-central-1", "eu", "__auto__", "__auto__", "sonnet-4-6", "haiku-4-5"]

        # questionary.confirm calls in execution order:
        # 1. Enable Windows builds? → False
        # 2. Enable CoWork MDM config? → False
        confirm_values = [False, False]

        with patch("questionary.select", side_effect=_select_side_effect(select_values)), patch(
            "questionary.confirm", side_effect=_confirm_side_effect(confirm_values)
        ):
            result = command._gather_configuration(progress)

        assert result is not None, "Wizard should complete without returning None"

        aws = result["aws"]
        # Q3 auto-select: primary model env var must not be set
        assert aws["selected_model"] is None, "selected_model should be None for auto-select"

        # Q4 auto: opus default not set
        assert aws["default_opus_model"] is None, "default_opus_model should be None for auto-select"

        # Q5 sonnet-4-6 chosen: should resolve to the EU model ID
        assert aws["default_sonnet_model"] == "eu.anthropic.claude-sonnet-4-6", (
            f"Expected eu sonnet model ID, got {aws['default_sonnet_model']!r}"
        )

        # Q6 haiku-4-5 chosen: should resolve to the EU model ID
        assert aws["default_haiku_model"] == "eu.anthropic.claude-haiku-4-5-20251001-v1:0", (
            f"Expected eu haiku model ID, got {aws['default_haiku_model']!r}"
        )

    def test_explicit_model_with_tier_defaults(self):
        """
        Regression: Q3=explicit model, Q4-Q6 as before — all four fields must be set.
        selected_model = eu sonnet-4-6 ID; tier defaults same as test above.
        """
        command = InitCommand()

        pre_config: dict = {
            "okta": {"domain": "test.okta.com", "client_id": "test-client-id"},
            "aws": {
                "region": "eu-central-1",
                "stack_base_name": "claude-code-auth",
                "identity_pool_name": "test-pool",
                "credential_storage": "session",
                "federation_type": "direct",
            },
            "monitoring": {"enabled": False},
            "codebuild": {"enabled": False},
            "distribution": {"enabled": False, "type": None},
        }
        progress = _make_mock_progress(pre_config, last_step="monitoring_complete")

        # Q3 = "sonnet-4-6" (explicit model)
        select_values = ["__disabled__", "eu-central-1", "eu", "sonnet-4-6", "__auto__", "sonnet-4-6", "haiku-4-5"]
        confirm_values = [False, False]

        with patch("questionary.select", side_effect=_select_side_effect(select_values)), patch(
            "questionary.confirm", side_effect=_confirm_side_effect(confirm_values)
        ):
            result = command._gather_configuration(progress)

        assert result is not None
        aws = result["aws"]

        assert aws["selected_model"] == "eu.anthropic.claude-sonnet-4-6"
        assert aws["default_opus_model"] is None
        assert aws["default_sonnet_model"] == "eu.anthropic.claude-sonnet-4-6"
        assert aws["default_haiku_model"] == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_path_a_regression_q2_auto_returns_early_no_tier_questions(self):
        """
        Path A regression: Q2=auto-select exits the bedrock section immediately.
        Tier fields must all be None and selected_model must be None.
        Q3-Q6 must NOT be asked (the mock sequence has only 2 select values).
        """
        command = InitCommand()

        pre_config: dict = {
            "okta": {"domain": "test.okta.com", "client_id": "test-client-id"},
            "aws": {
                "region": "us-east-1",
                "stack_base_name": "claude-code-auth",
                "identity_pool_name": "test-pool",
                "credential_storage": "session",
                "federation_type": "direct",
            },
            "monitoring": {"enabled": False},
            "codebuild": {"enabled": False},
            "distribution": {"enabled": False, "type": None},
        }
        progress = _make_mock_progress(pre_config, last_step="monitoring_complete")

        # Q2 = "__auto__" → wizard returns early from bedrock section
        # Only 3 select values needed: distribution + Q1 + Q2 (no Q3-Q6)
        select_values = ["__disabled__", "us-east-1", "__auto__"]
        confirm_values = [False, False]

        with patch("questionary.select", side_effect=_select_side_effect(select_values)), patch(
            "questionary.confirm", side_effect=_confirm_side_effect(confirm_values)
        ):
            result = command._gather_configuration(progress)

        assert result is not None
        aws = result["aws"]

        assert aws["selected_model"] is None
        assert aws["default_opus_model"] is None
        assert aws["default_sonnet_model"] is None
        assert aws["default_haiku_model"] is None
        # Auto-select populates all destination regions from the model registry
        from claude_code_with_bedrock.models import get_all_destination_regions
        assert aws["allowed_bedrock_regions"] == get_all_destination_regions()
