"""
E2E Tests — Config Delivery (Bootstrap Endpoint)

Verifies the bootstrap config endpoint returns valid configuration,
handles token validation, and includes OTLP headers.
"""

import json
import time

import jwt
import pytest
import requests

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


@pytest.fixture
def bootstrap_url(stack_outputs):
    """Get bootstrap config endpoint URL from stack outputs."""
    url = stack_outputs.get("BootstrapConfigUrl") or stack_outputs.get("ConfigEndpoint")
    if not url:
        pytest.skip("Bootstrap config URL not in stack outputs")
    return url


@pytest.fixture
def valid_token(run_credential_process):
    """Get a valid bearer token from the credential process."""
    result = run_credential_process(
        context="initial",
        extra_args=["--token-only"],
    )
    if result.returncode != 0:
        # Fallback: extract from explain
        result = run_credential_process(extra_args=["--explain"])
        if result.returncode == 0:
            explain = json.loads(result.stdout)
            token = explain.get("auth", {}).get("id_token")
            if token:
                return token
        pytest.skip("Cannot obtain valid token for bootstrap tests")
    return result.stdout.strip()


class TestConfigDelivery:
    """Config delivery tests — only for profiles with config_delivery=bootstrap."""

    def test_bootstrap_endpoint_reachable(self, bootstrap_url, valid_token):
        """GET /config with valid Bearer token returns 200."""
        response = requests.get(
            bootstrap_url,
            headers={"Authorization": f"Bearer {valid_token}"},
            timeout=15,
        )

        assert response.status_code == 200, (
            f"Bootstrap endpoint returned {response.status_code}: {response.text[:200]}"
        )

    def test_bootstrap_returns_valid_config(self, bootstrap_url, valid_token):
        """Response contains required config keys."""
        response = requests.get(
            bootstrap_url,
            headers={"Authorization": f"Bearer {valid_token}"},
            timeout=15,
        )
        assert response.status_code == 200

        config = response.json()

        required_keys = ["inferenceProvider", "inferenceRegion", "inferenceModels"]
        for key in required_keys:
            assert key in config, f"Missing required config key: {key}"

        # Validate types
        assert isinstance(config["inferenceProvider"], str)
        assert isinstance(config["inferenceRegion"], str)
        assert isinstance(config["inferenceModels"], list)
        assert len(config["inferenceModels"]) > 0, "inferenceModels is empty"

    def test_bootstrap_includes_otlp_headers(self, bootstrap_url, valid_token):
        """Response includes otlpHeaders with x-user-email."""
        response = requests.get(
            bootstrap_url,
            headers={"Authorization": f"Bearer {valid_token}"},
            timeout=15,
        )
        assert response.status_code == 200

        config = response.json()

        otlp_headers = config.get("otlpHeaders", {})
        assert otlp_headers, "otlpHeaders missing from config response"

        # Check for user email header (case-insensitive)
        header_keys_lower = {k.lower(): v for k, v in otlp_headers.items()}
        assert "x-user-email" in header_keys_lower, (
            f"otlpHeaders missing x-user-email. Keys: {list(otlp_headers.keys())}"
        )

    def test_bootstrap_rejects_expired_token(self, bootstrap_url):
        """Expired JWT returns 401."""
        # Create an expired JWT (not cryptographically valid but expired)
        expired_token = jwt.encode(
            {
                "sub": "e2e-test-user",
                "exp": int(time.time()) - 3600,  # 1 hour ago
                "iat": int(time.time()) - 7200,
                "iss": "e2e-test",
            },
            "fake-secret-for-e2e",
            algorithm="HS256",
        )

        response = requests.get(
            bootstrap_url,
            headers={"Authorization": f"Bearer {expired_token}"},
            timeout=15,
        )

        assert response.status_code == 401, (
            f"Expired token should return 401, got {response.status_code}"
        )

    def test_bootstrap_rejects_wrong_audience(self, bootstrap_url):
        """JWT with wrong audience returns 403."""
        # Create a JWT with wrong audience
        wrong_aud_token = jwt.encode(
            {
                "sub": "e2e-test-user",
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
                "iss": "e2e-test",
                "aud": "wrong-audience-value",
            },
            "fake-secret-for-e2e",
            algorithm="HS256",
        )

        response = requests.get(
            bootstrap_url,
            headers={"Authorization": f"Bearer {wrong_aud_token}"},
            timeout=15,
        )

        assert response.status_code in (401, 403), (
            f"Wrong audience should return 401 or 403, got {response.status_code}"
        )
