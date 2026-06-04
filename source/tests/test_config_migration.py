# ABOUTME: Regression harness — every historical config.json shape must still
# ABOUTME: load into the current Profile dataclass without error.

"""Verify that Profile.from_dict() accepts config.json files written by every
major release between upstream pre-Direct-IAM (Sep 2025) and our fork HEAD.

The customer-side scenario we're protecting: an IT admin who stored a profile
a year ago with `~/.ccwb/profiles/ClaudeCode.json` does `git pull` + `ccwb
package --go`. If the dataclass rejects the old field shape, the admin can't
even build a bundle -- every downstream user is blocked.

Fixtures are committed at `tests/fixtures/historical_configs/` and mirror
what the Go binary also validates under `source/go/internal/config/testdata/`.
"""

import json
from pathlib import Path

import pytest

from claude_code_with_bedrock.config import Profile

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "historical_configs"


@pytest.fixture(params=sorted(FIXTURE_DIR.glob("*.json")), ids=lambda p: p.name)
def fixture_path(request):
    return request.param


def test_historical_config_loads(fixture_path: Path) -> None:
    """Every historical config.json fixture must load into a Profile without error."""
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    profile = Profile.from_dict(data)

    # Basic invariants every version must preserve
    assert profile.name == "ClaudeCode"
    assert profile.aws_region == "us-east-1"
    # Either provider_domain is set (new-style) or was migrated from okta_domain
    assert profile.provider_domain, f"provider_domain empty after from_dict on {fixture_path.name}"


def test_legacy_okta_fields_migrated() -> None:
    """Pre-Direct-IAM configs used okta_domain / okta_client_id. After
    from_dict, these must appear as provider_domain / client_id.
    """
    data = json.loads((FIXTURE_DIR / "upstream_pre_direct_iam.json").read_text())
    # Fixture uses the legacy names
    assert "okta_domain" in data
    assert "okta_client_id" in data

    profile = Profile.from_dict(data)
    assert profile.provider_domain == "dev-12345.okta.com"
    assert profile.client_id == "0oa123abc456"


def test_provider_type_autodetected_from_okta_domain() -> None:
    """from_dict should infer provider_type='okta' when domain ends in .okta.com
    and the field was absent (line 180-200 in config.py).
    """
    data = json.loads((FIXTURE_DIR / "upstream_pre_direct_iam.json").read_text())
    assert "provider_type" not in data  # fixture must be missing the field

    profile = Profile.from_dict(data)
    assert profile.provider_type == "okta"


def test_upstream_current_azure_fields_nullable() -> None:
    """Upstream's current config has null Azure confidential-client fields.
    They must deserialize as None, not fail.
    """
    data = json.loads((FIXTURE_DIR / "upstream_current.json").read_text())
    profile = Profile.from_dict(data)

    assert profile.azure_auth_mode is None
    assert profile.client_secret is None
    assert profile.client_certificate_path is None
    assert profile.client_certificate_key_path is None
    assert profile.sso_enabled is True


def test_credential_storage_defaults_to_session() -> None:
    """Pre-Direct-IAM fixture omits credential_storage. from_dict should
    supply "session" (the safer default that uses ~/.aws/credentials).
    """
    data = {
        "name": "ClaudeCode",
        "okta_domain": "dev-12345.okta.com",
        "okta_client_id": "0oa123abc456",
        "aws_region": "us-east-1",
        "identity_pool_name": "ccwb-identity-pool",
        # credential_storage intentionally absent
    }
    profile = Profile.from_dict(data)
    assert profile.credential_storage == "session"
