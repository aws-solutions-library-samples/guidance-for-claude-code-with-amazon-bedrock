# ABOUTME: Tests for session tag / project attribution extraction in otel-helper
# ABOUTME: Verifies project claim extraction from various IdP claim formats

"""Tests for project/session tag attribution in otel-helper."""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "otel_helper"))

# The otel_helper module is structured as __main__.py, so we need to load it specially
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "otel_helper_main",
    os.path.join(os.path.dirname(__file__), "..", "otel_helper", "__main__.py")
)
_otel_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_otel_mod)
extract_user_info = _otel_mod.extract_user_info
format_as_headers_dict = _otel_mod.format_as_headers_dict


class TestProjectExtraction:
    """Tests for project claim extraction from JWT payloads."""

    def _base_payload(self, **overrides):
        """Minimal valid payload with email."""
        p = {"email": "user@example.com", "sub": "user123", "exp": 9999999999}
        p.update(overrides)
        return p

    def test_no_project_returns_empty(self):
        """No project claim → empty string (not a default placeholder)."""
        info = extract_user_info(self._base_payload())
        assert info["project"] == ""

    def test_direct_project_claim(self):
        """Direct 'project' claim in JWT (generic IdP)."""
        info = extract_user_info(self._base_payload(project="Platform"))
        assert info["project"] == "Platform"

    def test_cognito_custom_project(self):
        """Cognito custom:project attribute."""
        info = extract_user_info(self._base_payload(**{"custom:project": "DataTeam"}))
        assert info["project"] == "DataTeam"

    def test_aws_session_tag_nested_array(self):
        """AWS session tag format: https://aws.amazon.com/tags with array values (Auth0/Okta)."""
        payload = self._base_payload(**{
            "https://aws.amazon.com/tags": {
                "principal_tags": {
                    "Project": ["InfraTeam"],
                },
                "transitive_tag_keys": ["Project"],
            }
        })
        info = extract_user_info(payload)
        assert info["project"] == "InfraTeam"

    def test_aws_session_tag_string_value(self):
        """AWS session tag with string value (Entra ID flattened format)."""
        payload = self._base_payload(**{
            "https://aws.amazon.com/tags": {
                "principal_tags": {
                    "Project": "MLOps",
                },
            }
        })
        info = extract_user_info(payload)
        assert info["project"] == "MLOps"

    def test_aws_session_tag_costcenter_fallback(self):
        """Falls back to CostCenter if Project not present in session tags."""
        payload = self._base_payload(**{
            "https://aws.amazon.com/tags": {
                "principal_tags": {
                    "CostCenter": ["CC-1234"],
                },
            }
        })
        info = extract_user_info(payload)
        assert info["project"] == "CC-1234"

    def test_session_tag_takes_precedence_over_direct(self):
        """Session tag (https://aws.amazon.com/tags) takes precedence over direct claim."""
        payload = self._base_payload(
            project="DirectClaim",
            **{"https://aws.amazon.com/tags": {"principal_tags": {"Project": ["FromTag"]}}}
        )
        info = extract_user_info(payload)
        assert info["project"] == "FromTag"

    def test_billing_code_fallback(self):
        """billing_code claim used as project fallback."""
        info = extract_user_info(self._base_payload(billing_code="BC-5678"))
        assert info["project"] == "BC-5678"

    def test_project_emitted_as_x_project_header(self):
        """Project value flows through to x-project header."""
        info = extract_user_info(self._base_payload(project="MyProject"))
        headers = format_as_headers_dict(info)
        assert headers.get("x-project") == "MyProject"

    def test_empty_project_not_in_headers(self):
        """Empty project should not appear in headers (no empty x-project)."""
        info = extract_user_info(self._base_payload())
        headers = format_as_headers_dict(info)
        assert "x-project" not in headers

    def test_custom_department_also_works(self):
        """custom:department prefix still works (Cognito PR #372 compatibility)."""
        info = extract_user_info(self._base_payload(**{"custom:department": "Engineering"}))
        assert info["department"] == "Engineering"
