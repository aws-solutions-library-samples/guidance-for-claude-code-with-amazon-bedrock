# ABOUTME: Tests for generic AWS session tag extraction in otel-helper
# ABOUTME: Verifies that all principal_tags from the JWT flow through as x-tag-* headers

"""Tests for session tag attribution in otel-helper."""

import importlib.util
import os

# Load the otel_helper module
_spec = importlib.util.spec_from_file_location(
    "otel_helper_main", os.path.join(os.path.dirname(__file__), "..", "otel_helper", "__main__.py")
)
_otel_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_otel_mod)
extract_user_info = _otel_mod.extract_user_info
format_as_headers_dict = _otel_mod.format_as_headers_dict


class TestSessionTagExtraction:
    """Tests for generic AWS session tag extraction from JWT payloads."""

    def _base_payload(self, **overrides):
        """Minimal valid payload with email."""
        p = {"email": "user@example.com", "sub": "user123", "exp": 9999999999}
        p.update(overrides)
        return p

    def test_no_session_tags_returns_empty_dict(self):
        """No AWS tags claim → empty session_tags dict."""
        info = extract_user_info(self._base_payload())
        assert info["session_tags"] == {}

    def test_single_tag_array_format(self):
        """Single tag with array value (Auth0/Okta format)."""
        payload = self._base_payload(
            **{
                "https://aws.amazon.com/tags": {
                    "principal_tags": {"Project": ["Platform"]},
                }
            }
        )
        info = extract_user_info(payload)
        assert info["session_tags"] == {"Project": "Platform"}

    def test_single_tag_string_format(self):
        """Single tag with string value (Entra ID format)."""
        payload = self._base_payload(
            **{
                "https://aws.amazon.com/tags": {
                    "principal_tags": {"Project": "MLOps"},
                }
            }
        )
        info = extract_user_info(payload)
        assert info["session_tags"] == {"Project": "MLOps"}

    def test_multiple_tags(self):
        """Multiple tags all extracted."""
        payload = self._base_payload(
            **{
                "https://aws.amazon.com/tags": {
                    "principal_tags": {
                        "Project": ["Platform"],
                        "CostCenter": ["CC-1234"],
                        "Environment": ["production"],
                    },
                }
            }
        )
        info = extract_user_info(payload)
        assert info["session_tags"] == {
            "Project": "Platform",
            "CostCenter": "CC-1234",
            "Environment": "production",
        }

    def test_empty_tag_values_excluded(self):
        """Tags with empty values are not included."""
        payload = self._base_payload(
            **{
                "https://aws.amazon.com/tags": {
                    "principal_tags": {
                        "Project": ["Platform"],
                        "EmptyTag": [""],
                        "NullTag": [],
                    },
                }
            }
        )
        info = extract_user_info(payload)
        assert info["session_tags"] == {"Project": "Platform"}

    def test_malformed_aws_tags_claim(self):
        """Non-dict aws_tags claim doesn't crash."""
        payload = self._base_payload(**{"https://aws.amazon.com/tags": "not a dict"})
        info = extract_user_info(payload)
        assert info["session_tags"] == {}

    def test_tags_emitted_as_x_tag_headers(self):
        """Session tags flow through as x-tag-<key> headers."""
        payload = self._base_payload(
            **{
                "https://aws.amazon.com/tags": {
                    "principal_tags": {
                        "Project": ["InfraTeam"],
                        "CostCenter": ["CC-5678"],
                    },
                }
            }
        )
        info = extract_user_info(payload)
        headers = format_as_headers_dict(info)
        assert headers["x-tag-project"] == "InfraTeam"
        assert headers["x-tag-costcenter"] == "CC-5678"

    def test_no_tags_no_x_tag_headers(self):
        """No session tags → no x-tag-* headers emitted."""
        info = extract_user_info(self._base_payload())
        headers = format_as_headers_dict(info)
        tag_headers = {k: v for k, v in headers.items() if k.startswith("x-tag-")}
        assert tag_headers == {}

    def test_tag_key_normalized_to_lowercase(self):
        """Tag keys are lowercased in header names."""
        payload = self._base_payload(
            **{
                "https://aws.amazon.com/tags": {
                    "principal_tags": {"BillingCode": ["BC-999"]},
                }
            }
        )
        info = extract_user_info(payload)
        headers = format_as_headers_dict(info)
        assert "x-tag-billingcode" in headers
        assert headers["x-tag-billingcode"] == "BC-999"

    def test_existing_claims_still_work(self):
        """Existing fixed claims (department, team, etc.) are unaffected."""
        info = extract_user_info(
            self._base_payload(
                department="Engineering",
                team="Platform",
            )
        )
        assert info["department"] == "Engineering"
        assert info["team"] == "Platform"
        headers = format_as_headers_dict(info)
        assert headers["x-department"] == "Engineering"
        assert headers["x-team-id"] == "Platform"

    def test_custom_prefix_cognito_compat(self):
        """custom: prefix works as fallback for Cognito attributes."""
        # custom: is lower priority than direct claim (backward compat)
        info = extract_user_info(self._base_payload(**{"custom:department": "DataScience"}))
        assert info["department"] == "DataScience"
