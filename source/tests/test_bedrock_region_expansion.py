# ABOUTME: Regression tests that the "all-commercial" region sentinel never
# ABOUTME: reaches the AllowedBedrockRegions CFN param / aws:RequestedRegion IAM condition.

"""Regression: global-model region sentinel must not deny Bedrock invokes.

A profile whose selected model is a *global* inference profile stores
``allowed_bedrock_regions = ["all-commercial"]`` (the model's destination-region
sentinel). Before the fix, that string was passed verbatim as the
``AllowedBedrockRegions`` CloudFormation parameter, which becomes the federated
role's ``aws:RequestedRegion`` StringEquals condition. ``"all-commercial"``
equals no real region, so every ``bedrock:InvokeModelWithResponseStream`` call
was denied with AccessDenied even though auth succeeded.

These tests assert the sentinel is expanded into concrete regions at every
CFN-parameter boundary.
"""

from unittest.mock import patch

from claude_code_with_bedrock.config import Config, Profile


def _global_profile() -> Profile:
    """A Google-federated profile pinned to a global model, as saved by init."""
    return Profile(
        name="aws-demo",
        provider_domain="accounts.google.com",
        client_id="319-abc.apps.googleusercontent.com",
        credential_storage="session",
        aws_region="us-east-1",
        identity_pool_name="claude-code-auth",
        provider_type="google",
        federation_type="direct",
        selected_model="global.anthropic.claude-sonnet-4-6",
        allowed_bedrock_regions=["all-commercial"],
    )


def test_get_aws_config_expands_all_commercial():
    """Config.get_aws_config_for_profile must not emit the raw sentinel."""
    profile = _global_profile()
    cfg = Config()
    with patch.object(cfg, "get_profile", return_value=profile):
        aws_config = cfg.get_aws_config_for_profile("aws-demo")

    regions = aws_config["AllowedBedrockRegions"]
    assert "all-commercial" not in regions, (
        "The sentinel leaked into AllowedBedrockRegions — the IAM aws:RequestedRegion "
        "condition would match no region and deny every Bedrock invoke"
    )
    # The customer's request region must be authorized.
    assert "us-east-1" in regions.split(",")


def test_expansion_covers_the_reported_arn_region():
    """The us-east-1 invoke from the CloudTrail AccessDenied must now be allowed."""
    from claude_code_with_bedrock.models import expand_bedrock_regions

    expanded = expand_bedrock_regions(["all-commercial"])
    # inference-profile/global.anthropic.claude-sonnet-* is invoked in us-east-1
    assert "us-east-1" in expanded
    assert not any(r.startswith("all-") for r in expanded)
