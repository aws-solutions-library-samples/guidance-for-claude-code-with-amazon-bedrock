"""
E2E Tests — --explain Contract Validation

Verifies that credential-process --explain output matches the expected
schema for each profile. Catches unintended config drift or field renames.
"""

import json
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(10)]

# Required top-level keys in --explain output
REQUIRED_KEYS = {
    "version",
    "commit",
    "profile",
    "platform",
    "auth",
    "monitoring",
    "quota",
    "storage",
    "paths",
}

# Required nested keys per section
REQUIRED_AUTH_KEYS = {"mode", "reason"}
REQUIRED_MONITORING_KEYS = {"enabled", "mode", "config_delivery"}
REQUIRED_QUOTA_KEYS = {"enabled", "fail_mode", "auth_method"}
REQUIRED_STORAGE_KEYS = {"mode"}
REQUIRED_PLATFORM_KEYS = {"os", "arch"}
REQUIRED_PATHS_KEYS = {"config_dir", "config_file"}


class TestExplainContract:
    """Validate --explain JSON schema matches expectations per profile."""

    def test_explain_returns_valid_json(self, credential_process_binary):
        """--explain exits 0 with parseable JSON."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"--explain exited {result.returncode}: {result.stderr}"
        )
        data = json.loads(result.stdout)
        assert isinstance(data, dict)

    def test_explain_has_required_top_level_keys(self, credential_process_binary):
        """All required top-level sections present."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        missing = REQUIRED_KEYS - set(data.keys())
        assert not missing, f"Missing top-level keys in --explain: {missing}"

    def test_explain_auth_section(self, credential_process_binary, e2e_profile):
        """auth section has required keys and mode matches profile."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        auth = data["auth"]

        missing = REQUIRED_AUTH_KEYS - set(auth.keys())
        assert not missing, f"Missing auth keys: {missing}"

        # Mode should match profile declaration
        expected_mode = e2e_profile["auth"]["type"]
        assert auth["mode"] == expected_mode, (
            f"--explain auth.mode={auth['mode']} but profile declares auth.type={expected_mode}"
        )

    def test_explain_monitoring_section(self, credential_process_binary, e2e_profile):
        """monitoring section has required keys and mode matches profile."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        monitoring = data["monitoring"]

        missing = REQUIRED_MONITORING_KEYS - set(monitoring.keys())
        assert not missing, f"Missing monitoring keys: {missing}"

        expected_mode = e2e_profile["monitoring"]["mode"]
        assert monitoring["mode"] == expected_mode, (
            f"--explain monitoring.mode={monitoring['mode']} but profile declares {expected_mode}"
        )

    def test_explain_quota_section(self, credential_process_binary, e2e_profile):
        """quota section has required keys and enabled matches profile."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        quota = data["quota"]

        missing = REQUIRED_QUOTA_KEYS - set(quota.keys())
        assert not missing, f"Missing quota keys: {missing}"

        expected_enabled = e2e_profile["quota"]["enabled"]
        assert quota["enabled"] == expected_enabled, (
            f"--explain quota.enabled={quota['enabled']} but profile declares {expected_enabled}"
        )

    def test_explain_platform_section(self, credential_process_binary):
        """platform section has os and arch."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)
        platform = data["platform"]

        missing = REQUIRED_PLATFORM_KEYS - set(platform.keys())
        assert not missing, f"Missing platform keys: {missing}"

        # OS should match the actual runtime
        expected_os = (
            "windows"
            if sys.platform == "win32"
            else ("darwin" if sys.platform == "darwin" else "linux")
        )
        assert platform["os"] == expected_os, (
            f"Platform OS mismatch: {platform['os']} vs {expected_os}"
        )

    def test_explain_version_and_commit(self, credential_process_binary):
        """version and commit fields are non-empty strings."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)

        assert data["version"], "version field is empty"
        assert data["commit"], "commit field is empty"
        assert data["version"] != "dev" or data["commit"] != "unknown", (
            "Binary appears to be a development build (version=dev, commit=unknown)"
        )

    def test_explain_config_delivery_matches_profile(
        self, credential_process_binary, e2e_profile
    ):
        """config_delivery field matches profile declaration."""
        result = subprocess.run(
            [str(credential_process_binary), "--explain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        data = json.loads(result.stdout)

        expected = e2e_profile.get("config_delivery", "static")
        actual = data["monitoring"].get("config_delivery", "static")
        assert actual == expected, (
            f"--explain config_delivery={actual} but profile declares {expected}"
        )
