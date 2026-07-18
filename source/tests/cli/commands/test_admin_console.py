# ABOUTME: Unit tests for the admin-console Lambda handler
# ABOUTME: Tests ALB OIDC identity extraction, IDC admin authorization, and API routing

"""Tests for the admin_console Lambda handler.

Auth model under test: the ALB's authenticate-oidc listener action has
already validated the caller's JWT before invoking this Lambda (see
admin-console.yaml's AdminListenerRule) — the Lambda only decodes the
already-validated x-amzn-oidc-data header for identity, then does a SEPARATE
live IAM Identity Center group lookup to authorize access to /admin*.
"""

import base64
import importlib.util
import json
import os
import sys
from unittest.mock import patch

import pytest

_LAMBDA_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "..",
        "deployment",
        "infrastructure",
        "lambda-functions",
        "admin_console",
    )
)


def _oidc_data_header(email: str) -> str:
    """Build a fake (unsigned) x-amzn-oidc-data value — signature verification
    is the ALB's job, not this Lambda's, so tests don't need a real JWT."""
    header = base64.b64encode(b"{}").decode().rstrip("=")
    payload = base64.b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    signature = base64.b64encode(b"fake").decode().rstrip("=")
    return f"{header}.{payload}.{signature}"


@pytest.fixture
def handler(monkeypatch):
    """Import the admin_console Lambda module fresh for each test."""
    monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("IDC_INSTANCE_ARN", "arn:aws:sso:::instance/ssoins-test")
    monkeypatch.setenv("ADMIN_GROUP", "Claude-Code-Admins")
    monkeypatch.setenv("BASE_URL", "https://downloads.example.com")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    if "index" in sys.modules:
        del sys.modules["index"]
    if _LAMBDA_DIR not in sys.path:
        sys.path.insert(0, _LAMBDA_DIR)

    spec = importlib.util.spec_from_file_location("index", os.path.join(_LAMBDA_DIR, "index.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["index"] = module
    spec.loader.exec_module(module)
    return module


class TestExtractUserEmail:
    def test_no_header_returns_empty(self, handler):
        assert handler.extract_user_email({}) == ""

    def test_valid_header_returns_email(self, handler):
        headers = {"x-amzn-oidc-data": _oidc_data_header("alice@example.com")}
        assert handler.extract_user_email(headers) == "alice@example.com"

    def test_malformed_header_returns_empty(self, handler):
        assert handler.extract_user_email({"x-amzn-oidc-data": "not.a.jwt.at.all"}) == ""


class TestGroupNameToConfigKey:
    def test_strips_prefix_and_pluralization(self, handler):
        assert handler.group_name_to_config_key("Claude-Code-Developers") == "developer"

    def test_short_name_not_singularized(self, handler):
        # len <= 3 after stripping trailing 's' guard avoids mangling short names
        assert handler.group_name_to_config_key("Claude-Ops") == "ops"


class TestLambdaHandlerAuth:
    def test_missing_oidc_header_returns_401(self, handler):
        event = {"path": "/admin", "httpMethod": "GET", "headers": {}}
        response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 401

    @patch("index.get_user_idc_groups", return_value=["Claude-Code-Developers"])
    def test_non_admin_group_returns_403(self, mock_groups, handler):
        event = {
            "path": "/admin",
            "httpMethod": "GET",
            "headers": {"x-amzn-oidc-data": _oidc_data_header("dev@example.com")},
        }
        response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 403

    @patch("index.get_user_idc_groups", return_value=["Claude-Code-Admins"])
    def test_admin_group_case_insensitive_match(self, mock_groups, handler):
        """ADMIN_GROUP comparison is case-insensitive, matching the CDK original."""
        event = {
            "path": "/admin/api/groups",
            "httpMethod": "GET",
            "headers": {"x-amzn-oidc-data": _oidc_data_header("admin@example.com")},
        }
        with patch("index.sso_admin_client") as mock_sso, patch("index.identity_store_client"):
            mock_sso.list_instances.return_value = {"Instances": [{"IdentityStoreId": "d-1234567890"}]}
            mock_sso.get_paginator.return_value.paginate.return_value = [{"Groups": []}]
            response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 200

    @patch("index.get_user_idc_groups", return_value=["Claude-Code-Admins"])
    def test_post_without_origin_header_rejected(self, mock_groups, handler):
        """CSRF defense-in-depth: admin POST requests require a matching Origin header."""
        event = {
            "path": "/admin/api/config",
            "httpMethod": "POST",
            "headers": {"x-amzn-oidc-data": _oidc_data_header("admin@example.com")},
            "body": "{}",
        }
        response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 403

    @patch("index.get_user_idc_groups", return_value=["Claude-Code-Admins"])
    def test_post_with_matching_origin_allowed(self, mock_groups, handler):
        event = {
            "path": "/admin/api/config",
            "httpMethod": "POST",
            "headers": {
                "x-amzn-oidc-data": _oidc_data_header("admin@example.com"),
                "origin": "https://downloads.example.com",
            },
            "body": json.dumps({"mappings": []}),
        }
        with patch("index.s3_client") as mock_s3:
            response = handler.lambda_handler(event, None)
            mock_s3.put_object.assert_called_once()
        assert response["statusCode"] == 200

    @patch("index.get_user_idc_groups", return_value=["Claude-Code-Admins"])
    def test_unknown_admin_path_returns_404(self, mock_groups, handler):
        event = {
            "path": "/admin/api/does-not-exist",
            "httpMethod": "GET",
            "headers": {"x-amzn-oidc-data": _oidc_data_header("admin@example.com")},
        }
        response = handler.lambda_handler(event, None)
        assert response["statusCode"] == 404


class TestApiListModels:
    def test_excludes_deprecated_and_non_claude_models(self, handler):
        with patch("index.bedrock_client") as mock_bedrock:
            mock_bedrock.list_inference_profiles.return_value = {
                "inferenceProfileSummaries": [
                    {
                        "inferenceProfileId": "us.anthropic.claude-sonnet-4-6",
                        "inferenceProfileName": "Claude Sonnet 4.6",
                        "status": "ACTIVE",
                    },
                    {
                        "inferenceProfileId": "us.anthropic.claude-3-opus-20240229-v1:0",
                        "inferenceProfileName": "Claude 3 Opus (deprecated)",
                        "status": "ACTIVE",
                    },
                    {
                        "inferenceProfileId": "us.amazon.titan-text",
                        "inferenceProfileName": "Titan",
                        "status": "ACTIVE",
                    },
                ]
            }
            response = handler.api_list_models()
        body = json.loads(response["body"])
        model_ids = [m["modelId"] for m in body["models"]]
        assert "us.anthropic.claude-sonnet-4-6" in model_ids
        assert "us.anthropic.claude-3-opus-20240229-v1:0" not in model_ids
        assert "us.amazon.titan-text" not in model_ids


class TestAdminConfigStorage:
    def test_load_admin_config_defaults_when_missing(self, handler):
        with patch("index.s3_client") as mock_s3:
            mock_s3.get_object.side_effect = Exception("NoSuchKey")
            config = handler.load_admin_config()
        assert config == {"mappings": []}

    def test_save_admin_config_writes_expected_key(self, handler):
        with patch("index.s3_client") as mock_s3:
            handler.save_admin_config({"mappings": [{"groupName": "x"}]})
            mock_s3.put_object.assert_called_once()
            call_kwargs = mock_s3.put_object.call_args.kwargs
            assert call_kwargs["Key"] == "admin/config.json"
            assert call_kwargs["Bucket"] == "test-bucket"


class TestGenerateMdmConfigs:
    def test_writes_expected_s3_keys(self, handler):
        with patch("index.s3_client") as mock_s3:
            handler.generate_mdm_configs(
                config_key="developer",
                idc_start_url="https://d-1234567890.awsapps.com/start",
                account_id="123456789012",
                role_name="ClaudeCode-Developers",
                models_list=[{"modelId": "us.anthropic.claude-sonnet-4-6", "modelName": "Claude Sonnet 4.6"}],
            )
        put_calls = mock_s3.put_object.call_args_list
        written_keys = {c.kwargs["Key"] for c in put_calls}
        assert written_keys == {
            "config/developer/default.json",
            "config/developer/bootstrap.json",
            "config/developer/Claude.mobileconfig",
            "config/developer/Claude.reg",
        }

    def test_bootstrap_config_has_explicit_policy_toggles(self, handler):
        """Bootstrap responses must set every policy toggle explicitly (omitted
        keys are treated as unset by Claude Desktop, not inherited from MDM)."""
        captured = {}

        def _capture_put(**kwargs):
            if kwargs["Key"] == "config/developer/bootstrap.json":
                captured["body"] = json.loads(kwargs["Body"])

        with patch("index.s3_client") as mock_s3:
            mock_s3.put_object.side_effect = _capture_put
            handler.generate_mdm_configs(
                config_key="developer",
                idc_start_url="https://d-1234567890.awsapps.com/start",
                account_id="123456789012",
                role_name="ClaudeCode-Developers",
                models_list=[{"modelId": "us.anthropic.claude-sonnet-4-6", "modelName": "Claude Sonnet 4.6"}],
            )
        assert "isLocalDevMcpEnabled" in captured["body"]
        assert "bootstrapEnabled" in captured["body"]
        assert captured["body"]["bootstrapUrl"] == "https://downloads.example.com/api/bootstrap"
