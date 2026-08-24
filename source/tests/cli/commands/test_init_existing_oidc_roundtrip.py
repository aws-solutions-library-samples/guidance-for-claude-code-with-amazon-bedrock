# ABOUTME: Regression test ensuring re-running init preserves a saved existing_oidc_provider_arn
# ABOUTME: Guards _check_existing_deployment against round-trip drift with _save_configuration (issue #528)

"""Regression test: re-running `ccwb init` must preserve the reused OIDC provider ARN.

Issue #528: when a second profile shares an OIDC issuer in one AWS account, the
user sets `existing_oidc_provider_arn` so the auth stack reuses the existing IAM
OIDC provider instead of failing with EntityAlreadyExists.

`_check_existing_deployment` rebuilds the in-memory config dict from the saved
Profile on a re-run of init. If it does not restore `existing_oidc_provider_arn`,
the prompt default resolves to "" (init.py: `config.get(...) or ""`), the user
presses Enter, the field is wiped, deploy stops passing ExistingOIDCProviderArn,
the template recreates the shared provider, and the deploy fails with
EntityAlreadyExists — the exact failure this feature prevents.

This test fails without the reload-path restore and passes with it.
"""

import sys
from pathlib import Path
from unittest.mock import patch

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from claude_code_with_bedrock.cli.commands.init import InitCommand
from claude_code_with_bedrock.config import Config, Profile

_ARN = "arn:aws:iam::123456789012:oidc-provider/company.okta.com"


def _make_profile(existing_oidc_provider_arn=_ARN) -> Profile:
    """A direct-federation profile that reuses an existing OIDC provider, as if previously saved."""
    return Profile(
        name="test",
        provider_domain="company.okta.com",
        client_id="0oa1234567890",
        identity_pool_name="claude-code-auth",
        credential_storage="session",
        aws_region="us-east-1",
        provider_type="okta",
        federation_type="direct",
        existing_oidc_provider_arn=existing_oidc_provider_arn,
    )


def _rebuild_config(profile: Profile) -> dict:
    """Run _check_existing_deployment with AWS interaction stubbed out."""
    command = InitCommand()
    fake_config = Config()
    with (
        patch.object(Config, "load", return_value=fake_config),
        patch.object(fake_config, "get_profile", return_value=profile),
        # Avoid any AWS calls; pretend the stack check could not run.
        patch.object(InitCommand, "_stack_exists", side_effect=Exception("no creds")),
    ):
        return command._check_existing_deployment("test")


def test_rerun_preserves_existing_oidc_provider_arn():
    """existing_oidc_provider_arn must survive the profile -> config rebuild."""
    rebuilt = _rebuild_config(_make_profile())

    assert rebuilt.get("existing_oidc_provider_arn") == _ARN, (
        "existing_oidc_provider_arn dropped on init re-run; the next deploy would "
        "recreate the shared provider and fail EntityAlreadyExists (issue #528)"
    )


def test_rebuilt_arn_prefills_prompt_default():
    """The rebuilt config must drive a non-empty prompt default on re-run.

    Mirrors the expression init.py uses for the questionary default
    (`config.get("existing_oidc_provider_arn") or ""`).
    """
    rebuilt = _rebuild_config(_make_profile())

    prompt_default = rebuilt.get("existing_oidc_provider_arn") or ""
    assert prompt_default == _ARN


def test_rerun_omits_arn_when_not_set():
    """A profile that never reused a provider must not gain a spurious key.

    The reload uses a truthy guard (like the other OIDC fields), so None/empty is
    simply absent — the prompt default then correctly resolves to "".
    """
    rebuilt = _rebuild_config(_make_profile(existing_oidc_provider_arn=None))

    assert "existing_oidc_provider_arn" not in rebuilt
    assert (rebuilt.get("existing_oidc_provider_arn") or "") == ""
