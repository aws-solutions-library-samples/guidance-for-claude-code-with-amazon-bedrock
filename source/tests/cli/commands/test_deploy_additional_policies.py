# ABOUTME: Tests that deploy passes AdditionalManagedPolicyArns to the auth stack
# ABOUTME: Covers OIDC and IDC paths, present-when-set and absent-when-empty

"""`ccwb deploy` must forward additional_managed_policy_arns to CloudFormation.

The parameter is only appended when the profile sets it — omitting it lets the
template's Default ('') keep existing deployments unchanged.
"""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from rich.console import Console

from claude_code_with_bedrock.cli.commands.deploy import DeployCommand
from claude_code_with_bedrock.config import Profile

POLICY_ARNS = [
    "arn:aws:iam::123456789012:policy/corp-ip-restriction",
    "arn:aws:iam::123456789012:policy/extra-guardrail",
]


def _make_profile(auth_type: str, policy_arns: list[str]) -> Profile:
    fields = {
        "name": "test",
        "provider_domain": "example.okta.com",
        "client_id": "0oa1234567890",
        "identity_pool_name": "claude-code-auth",
        "credential_storage": "keyring",
        "aws_region": "us-east-1",
        "provider_type": "okta",
        "auth_type": auth_type,
        "additional_managed_policy_arns": policy_arns,
    }
    if auth_type == "idc":
        fields.update(
            {
                "idc_start_url": "https://example.awsapps.com/start",
                "idc_account_id": "123456789012",
                "idc_permission_set_name": "BedrockDeveloperAccess",
                "sso_region": "us-east-1",
            }
        )
    return Profile(**fields)


def _deploy_auth_params(profile: Profile) -> list[dict]:
    """Run the real auth-stack deploy path and capture the boto3 parameters."""
    command = DeployCommand()
    cf_manager = Mock()
    cf_manager.deploy_stack.return_value = Mock(success=True)

    rc = command._deploy_stack("auth", profile, Console(file=None, quiet=True), cf_manager)
    assert rc == 0
    return cf_manager.deploy_stack.call_args.kwargs["parameters"]


def _param_value(params: list[dict], key: str):
    for p in params:
        if p["ParameterKey"] == key:
            return p["ParameterValue"]
    return None


@pytest.mark.parametrize("auth_type", ["oidc", "idc"])
def test_param_present_when_policies_configured(auth_type):
    params = _deploy_auth_params(_make_profile(auth_type, list(POLICY_ARNS)))
    assert _param_value(params, "AdditionalManagedPolicyArns") == ",".join(POLICY_ARNS)


@pytest.mark.parametrize("auth_type", ["oidc", "idc"])
def test_param_absent_when_no_policies(auth_type):
    """Empty list → parameter omitted → template Default keeps old behavior."""
    params = _deploy_auth_params(_make_profile(auth_type, []))
    assert _param_value(params, "AdditionalManagedPolicyArns") is None
