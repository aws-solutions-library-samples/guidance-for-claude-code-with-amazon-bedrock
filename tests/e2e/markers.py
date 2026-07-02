"""
Custom pytest markers for the E2E test harness.

Usage:
    @pytest.mark.flaky_cloudwatch
    def test_metric_arrives(...):
        ...
"""

import pytest

# Marker for tests that depend on CloudWatch metric propagation (60-120s delay)
flaky_cloudwatch = pytest.mark.flaky(reruns=2, reruns_delay=30)

# Marker for tests that depend on eventual consistency (DynamoDB, S3)
flaky_eventual = pytest.mark.flaky(reruns=1, reruns_delay=5)

# Marker for tests that may hit cold-start latency (Lambda, OIDC provider)
flaky_coldstart = pytest.mark.flaky(reruns=1, reruns_delay=10)
