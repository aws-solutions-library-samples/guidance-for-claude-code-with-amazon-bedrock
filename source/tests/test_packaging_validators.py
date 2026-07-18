# ABOUTME: Tests for the package-time profile validators (cli/validators.py) —
# ABOUTME: the monitoring endpoint check must not fire for sidecar mode.

"""validate_profile_for_packaging regression tests.

The monitoring-consistency check warned "Monitoring enabled but no
otel_collector_endpoint configured" for EVERY sidecar package: sidecar
profiles never have that field (the endpoint is hardcoded to
http://localhost:4318 at package time; there is no ALB). The warning's advice
— deploy the central monitoring stack — is exactly what sidecar mode must not
do. The check now applies to central mode only.
"""

from __future__ import annotations

from claude_code_with_bedrock.cli.validators import validate_profile_for_packaging
from claude_code_with_bedrock.config import Profile


def _profile(**overrides) -> Profile:
    defaults = {
        "name": "validator-test",
        "provider_domain": "company.okta.com",
        "client_id": "client-123",
        "credential_storage": "session",
        "aws_region": "us-gov-west-1",
        "identity_pool_name": "pool",
        "auth_type": "oidc",
        "monitoring_enabled": True,
        "allowed_bedrock_regions": ["us-gov-west-1", "us-gov-east-1"],
    }
    defaults.update(overrides)
    return Profile(**defaults)


def _endpoint_warnings(profile):
    return [e for e in validate_profile_for_packaging(profile) if e.field == "otel_collector_endpoint"]


class TestMonitoringEndpointCheck:
    def test_sidecar_without_endpoint_is_clean(self):
        """The regression: sidecar mode has no ALB endpoint by design."""
        profile = _profile(monitoring_mode="sidecar", otel_collector_endpoint=None)
        assert _endpoint_warnings(profile) == []

    def test_central_without_endpoint_warns(self):
        profile = _profile(monitoring_mode="central", otel_collector_endpoint=None)
        warnings = _endpoint_warnings(profile)
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    def test_central_with_endpoint_is_clean(self):
        profile = _profile(monitoring_mode="central", otel_collector_endpoint="https://collector.example.com:4318")
        assert _endpoint_warnings(profile) == []

    def test_monitoring_disabled_is_clean(self):
        profile = _profile(monitoring_enabled=False, monitoring_mode="central")
        assert _endpoint_warnings(profile) == []


def _region_warnings(profile):
    return [e for e in validate_profile_for_packaging(profile) if e.field == "aws_region"]


class TestAllowedRegionSentinelCheck:
    """The aws_region check must expand "all-commercial" before comparing.

    A global-model profile legitimately stores allowed_bedrock_regions =
    ["all-commercial"]. Comparing aws_region against the raw sentinel warned
    spuriously ("Region 'us-east-1' not in allowed_bedrock_regions:
    ['all-commercial']") even though the region is authorized once the sentinel
    is expanded at the CFN-param boundary.
    """

    def test_all_commercial_does_not_warn_for_commercial_region(self):
        profile = _profile(aws_region="us-east-1", allowed_bedrock_regions=["all-commercial"])
        assert _region_warnings(profile) == []

    def test_concrete_region_mismatch_still_warns(self):
        # Genuine misconfiguration must still surface.
        profile = _profile(aws_region="us-east-1", allowed_bedrock_regions=["eu-west-1"])
        warnings = _region_warnings(profile)
        assert len(warnings) == 1
        assert warnings[0].severity == "warning"

    def test_concrete_region_match_is_clean(self):
        profile = _profile(aws_region="us-east-1", allowed_bedrock_regions=["us-east-1", "us-west-2"])
        assert _region_warnings(profile) == []
