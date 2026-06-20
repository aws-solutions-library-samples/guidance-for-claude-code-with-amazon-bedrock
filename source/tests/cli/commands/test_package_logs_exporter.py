# ABOUTME: Regression tests for OTEL_LOGS_EXPORTER in generated settings.json
# ABOUTME: The collector defines only a metrics pipeline, so logs export must be disabled

"""Regression tests: generated settings.json disables OTLP logs export.

The OTEL collector config (otel-collector.yaml) defines only a metrics pipeline
in both SSM service-config variants. When settings.json sets
OTEL_LOGS_EXPORTER=otlp, Claude Code POSTs /v1/logs to the collector, which has
no logs pipeline to route them -> the OTLP receiver drops them and the ALB
returns HTTPCode_Target_4XX. Disabling logs export (OTEL_LOGS_EXPORTER=none)
removes that traffic while leaving metrics unaffected.

Both the standard package command and the Cowork (CodeBuild) variant must set
"none" explicitly -- deleting the key could let a global/user default re-enable
"otlp".
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.cli.commands.package_cb import PackageCbCommand
from claude_code_with_bedrock.config import Profile


def _monitoring_profile() -> Profile:
    return Profile(
        name="test",
        provider_domain="test.okta.com",
        client_id="test-client-id",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        allowed_bedrock_regions=["us-east-1", "us-west-2"],
        cross_region_profile="us",
        monitoring_enabled=True,
        otel_collector_endpoint="https://collector.example.com",
        stack_names={"monitoring": "test-pool-otel-collector"},
    )


def _read_settings_env(output_dir: Path) -> dict:
    settings_path = output_dir / "claude-settings" / "settings.json"
    with open(settings_path, encoding="utf-8") as f:
        return json.load(f)["env"]


class TestLogsExporterDisabled:
    """OTEL_LOGS_EXPORTER must be 'none' so the collector stops 4xx-ing /v1/logs."""

    def test_standard_package_disables_logs_exporter(self):
        command = PackageCommand()
        profile = _monitoring_profile()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)
            env = _read_settings_env(output_dir)

        # Telemetry is on (endpoint resolved from profile) ...
        assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
        # ... metrics still export ...
        assert env["OTEL_METRICS_EXPORTER"] == "otlp"
        # ... but logs export is explicitly disabled (not deleted).
        assert env["OTEL_LOGS_EXPORTER"] == "none"

    def test_cowork_package_disables_logs_exporter(self):
        command = PackageCbCommand()
        profile = _monitoring_profile()

        cfn_outputs = json.dumps([{"OutputKey": "CollectorEndpoint", "OutputValue": "https://collector.example.com"}])

        class _FakeResult:
            returncode = 0
            stdout = cfn_outputs

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            with patch(
                "claude_code_with_bedrock.cli.commands.package_cb.subprocess.run",
                return_value=_FakeResult(),
            ):
                command._create_claude_settings(
                    output_dir, profile, include_coauthored_by=True, profile_name="ClaudeCode"
                )
            env = _read_settings_env(output_dir)

        assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
        assert env["OTEL_METRICS_EXPORTER"] == "otlp"
        assert env["OTEL_LOGS_EXPORTER"] == "none"
