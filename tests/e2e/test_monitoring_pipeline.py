"""
E2E Tests — Monitoring Pipeline (OTLP Proxy)

Verifies the otel-helper proxy starts, accepts OTLP data,
self-heals, and delivers metrics to CloudWatch.
"""

import json
import os
import tempfile
import subprocess
import time

import pytest
import requests

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


def _get_monitoring_port(profile: dict) -> int:
    """Get expected OTLP port based on monitoring mode."""
    mode = profile.get("monitoring", {}).get("mode", "none")
    if mode == "central":
        return 4318
    elif mode == "sidecar":
        return 4319
    else:
        pytest.skip("Monitoring mode is 'none' — skipping monitoring tests")


class TestMonitoringPipeline:
    """Monitoring pipeline tests — only for profiles with monitoring.mode != 'none'."""

    def test_proxy_starts_after_auth(
        self, run_credential_process, wait_for_port, e2e_profile
    ):
        """OTLP proxy port is listening after credential-process auth."""
        port = _get_monitoring_port(e2e_profile)

        # Run credential process to trigger proxy start
        result = run_credential_process(context="initial")
        assert result.returncode == 0, f"Auth failed: {result.stderr}"

        # Wait for proxy port
        assert wait_for_port(port, timeout=15), (
            f"OTLP proxy port {port} not listening after auth"
        )

    def test_otlp_post_accepted(
        self, run_credential_process, wait_for_port, e2e_profile
    ):
        """POST sample metric to OTLP proxy returns 200."""
        port = _get_monitoring_port(e2e_profile)

        # Ensure proxy is running
        result = run_credential_process(context="initial")
        assert result.returncode == 0
        assert wait_for_port(port, timeout=15)

        # POST a sample OTLP metric
        sample_metric = {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "e2e-test"},
                            }
                        ]
                    },
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {
                                    "name": "e2e.test.counter",
                                    "sum": {
                                        "dataPoints": [
                                            {
                                                "asInt": "1",
                                                "timeUnixNano": str(
                                                    int(time.time() * 1e9)
                                                ),
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    ],
                }
            ]
        }

        response = requests.post(
            f"http://127.0.0.1:{port}/v1/metrics",
            json=sample_metric,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )

        assert response.status_code == 200, (
            f"OTLP POST returned {response.status_code}: {response.text}"
        )

    def test_proxy_self_healing(
        self, run_credential_process, wait_for_port, e2e_profile
    ):
        """After killing the proxy, re-running credential-process restarts it."""
        port = _get_monitoring_port(e2e_profile)

        # Start proxy via auth
        result = run_credential_process(context="initial")
        assert result.returncode == 0
        assert wait_for_port(port, timeout=15)

        # Find and kill the proxy process
        try:
            subprocess.run(
                ["pkill", "-f", "otel-helper"],
                capture_output=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("Cannot kill proxy process on this platform")

        # Give it a moment to die
        time.sleep(1)

        # Re-run credential process — should restart proxy
        result = run_credential_process(context="initial")
        assert result.returncode == 0

        # Proxy should be back
        assert wait_for_port(port, timeout=15), (
            f"Proxy did not self-heal: port {port} not listening after restart"
        )

    def test_otel_headers_cache_populated(self, run_credential_process, e2e_profile):
        """OTEL headers cache file exists and contains x-user-email."""
        result = run_credential_process(context="initial")
        assert result.returncode == 0

        # Check common cache locations
        home = os.path.expanduser("~")
        cache_paths = [
            os.path.join(home, ".ccwb", "otel-headers.json"),
            os.path.join(home, ".config", "ccwb", "otel-headers.json"),
            os.path.join(tempfile.gettempdir(), "ccwb-otel-headers.json"),  # nosec B108
        ]

        cache_found = False
        for cache_path in cache_paths:
            if os.path.exists(cache_path):
                with open(cache_path) as f:
                    headers = json.load(f)
                assert "x-user-email" in headers or "X-User-Email" in headers, (
                    f"Cache at {cache_path} missing x-user-email header"
                )
                cache_found = True
                break

        if not cache_found:
            # Check stderr for cache path hint
            if "otel-headers" in result.stderr:
                pytest.fail(
                    f"Could not find OTEL headers cache. Tried: {cache_paths}\n"
                    f"stderr hint: {result.stderr}"
                )
            else:
                pytest.skip("OTEL headers cache not found (may not be applicable)")

    @pytest.mark.slow
    @pytest.mark.timeout(120)
    @pytest.mark.flaky(reruns=2, reruns_delay=30)
    def test_metric_arrives_in_cloudwatch(
        self,
        run_credential_process,
        wait_for_port,
        query_cloudwatch_metric,
        e2e_profile,
        stack_outputs,
    ):
        """Query CloudWatch after posting metric — verifies end-to-end pipeline."""
        port = _get_monitoring_port(e2e_profile)

        # Auth and wait for proxy
        result = run_credential_process(context="initial")
        assert result.returncode == 0
        assert wait_for_port(port, timeout=15)

        # Post a uniquely-named metric
        test_id = f"e2e-{int(time.time())}"
        sample_metric = {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": test_id}}
                        ]
                    },
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {
                                    "name": "e2e.pipeline.verification",
                                    "sum": {
                                        "dataPoints": [
                                            {
                                                "asInt": "42",
                                                "timeUnixNano": str(
                                                    int(time.time() * 1e9)
                                                ),
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    ],
                }
            ]
        }

        response = requests.post(
            f"http://127.0.0.1:{port}/v1/metrics",
            json=sample_metric,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert response.status_code == 200

        # Wait for metric to arrive in CloudWatch (with retry)
        namespace = stack_outputs.get("MonitoringNamespace", "CCWB/E2E")

        value = query_cloudwatch_metric(
            namespace=namespace,
            metric_name="e2e.pipeline.verification",
            dimensions=[{"Name": "service.name", "Value": test_id}],
        )

        assert value >= 42, f"Expected metric sum >= 42, got {value}"
