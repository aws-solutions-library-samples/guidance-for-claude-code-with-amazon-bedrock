# ABOUTME: Regression tests for additional_managed_policy_arns init round-trip
# ABOUTME: Guards save/reload parity, old-config compat, and the ARN list validator

"""Re-running `ccwb init` must preserve additional managed policy ARNs.

`_check_existing_deployment` rebuilds the wizard config dict from the saved
Profile; any field it omits silently resets on re-run (see PRs #436, #619,
#624). Old profiles without the field must load with an empty list.
"""

import sys
from pathlib import Path
from unittest.mock import patch

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from claude_code_with_bedrock.cli.commands.init import InitCommand
from claude_code_with_bedrock.cli.utils.validators import validate_managed_policy_arns
from claude_code_with_bedrock.config import Config, Profile

POLICY_ARNS = [
    "arn:aws:iam::123456789012:policy/corp-ip-restriction",
    "arn:aws:iam::123456789012:policy/extra-guardrail",
]


def _make_profile(**overrides) -> Profile:
    fields = {
        "name": "test",
        "provider_domain": "example.okta.com",
        "client_id": "0oa1234567890",
        "identity_pool_name": "claude-code-auth",
        "credential_storage": "keyring",
        "aws_region": "us-east-1",
    }
    fields.update(overrides)
    return Profile(**fields)


def _rebuild_config(profile: Profile) -> dict:
    """Run _check_existing_deployment with AWS interaction stubbed out."""
    command = InitCommand()
    fake_config = Config()
    with (
        patch.object(Config, "load", return_value=fake_config),
        patch.object(fake_config, "get_profile", return_value=profile),
        patch.object(InitCommand, "_stack_exists", side_effect=Exception("no creds")),
    ):
        return command._check_existing_deployment("test")


def test_rerun_preserves_additional_policy_arns():
    profile = _make_profile(additional_managed_policy_arns=list(POLICY_ARNS))
    rebuilt = _rebuild_config(profile)
    assert rebuilt["additional_managed_policy_arns"] == POLICY_ARNS


def test_rerun_defaults_to_empty_list():
    rebuilt = _rebuild_config(_make_profile())
    assert rebuilt["additional_managed_policy_arns"] == []


def test_old_config_without_field_loads_with_default():
    """Backward compat: profiles saved before this field existed still load."""
    old_data = {
        "name": "legacy",
        "provider_domain": "example.okta.com",
        "client_id": "0oa1234567890",
        "identity_pool_name": "claude-code-auth",
        "aws_region": "us-east-1",
    }
    profile = Profile.from_dict(old_data)
    assert profile.additional_managed_policy_arns == []


def test_field_round_trips_through_serialization():
    profile = _make_profile(additional_managed_policy_arns=list(POLICY_ARNS))
    reloaded = Profile.from_dict(profile.to_dict())
    assert reloaded.additional_managed_policy_arns == POLICY_ARNS


class TestManagedPolicyArnValidator:
    def test_empty_is_valid(self):
        assert validate_managed_policy_arns("") is True
        assert validate_managed_policy_arns("   ") is True

    def test_single_customer_arn(self):
        assert validate_managed_policy_arns("arn:aws:iam::123456789012:policy/corp-ip-restriction") is True

    def test_comma_separated_arns_with_spaces(self):
        assert validate_managed_policy_arns(", ".join(POLICY_ARNS)) is True

    def test_aws_managed_and_govcloud_arns(self):
        assert validate_managed_policy_arns("arn:aws:iam::aws:policy/ReadOnlyAccess") is True
        assert validate_managed_policy_arns("arn:aws-us-gov:iam::123456789012:policy/corp-ip-restriction") is True

    def test_path_prefixed_policy(self):
        assert validate_managed_policy_arns("arn:aws:iam::123456789012:policy/guardrails/ip-restrict") is True

    def test_invalid_arn_names_the_entry(self):
        result = validate_managed_policy_arns("not-an-arn")
        assert result != True  # noqa: E712 — questionary contract returns str on failure
        assert "not-an-arn" in result

    def test_role_arn_rejected(self):
        result = validate_managed_policy_arns("arn:aws:iam::123456789012:role/some-role")
        assert isinstance(result, str)

    def test_one_bad_entry_fails_the_list(self):
        value = POLICY_ARNS[0] + ",bogus"
        result = validate_managed_policy_arns(value)
        assert isinstance(result, str)
        assert "bogus" in result
