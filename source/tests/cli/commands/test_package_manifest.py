# ABOUTME: Tests that ccwb package produces complete output for each profile type.
# ABOUTME: Verifies the wiring of build steps by mocking subprocess and file I/O,
# ABOUTME: ensuring each profile type produces the expected manifest of output files.

"""Tests that ccwb package produces complete output for each profile type.

For a sidecar OIDC profile:
  - output should contain collector-config.yaml
  - output should reference otelcol build
  - output should reference credential-process binary

For a central monitoring profile:
  - output should NOT contain collector-config.yaml or otelcol

For IDC zero-binary:
  - output should NOT contain any Go binaries
  - output should contain collector-config.yaml (IDC template)
"""

import inspect
import json
from unittest.mock import MagicMock

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


# ---------------------------------------------------------------------------
# Fixtures: profile factories
# ---------------------------------------------------------------------------


def _make_oidc_sidecar_profile():
    """OIDC profile with sidecar monitoring — requires all binaries + collector."""
    return Profile(
        name="test-oidc-sidecar",
        provider_domain="auth.example.com",
        client_id="client-abc",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        auth_type="oidc",
        monitoring_enabled=True,
        monitoring_mode="sidecar",
        otel_collector_endpoint="https://alb.example.com",
    )


def _make_oidc_central_profile():
    """OIDC profile with central monitoring — no collector config or otelcol binary."""
    return Profile(
        name="test-oidc-central",
        provider_domain="auth.example.com",
        client_id="client-abc",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        auth_type="oidc",
        monitoring_enabled=True,
        monitoring_mode="central",
        otel_collector_endpoint="https://alb.example.com",
    )


def _make_idc_zero_binary_profile():
    """IDC profile without quota — zero-binary mode, no Go builds."""
    return Profile(
        name="test-idc-zero",
        provider_domain="",
        client_id="",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="",
        auth_type="idc",
        monitoring_enabled=True,
        monitoring_mode="sidecar",
        # No quota_api_endpoint → zero-binary mode
    )


# ---------------------------------------------------------------------------
# Helper: run the package command's post-build phase (config + collector config)
# ---------------------------------------------------------------------------


def _run_config_phase(profile, output_dir, built_executables=None, built_otel_helpers=None):
    """Run the configuration-generation phase of PackageCommand.

    This exercises _generate_collector_config, _create_config, _create_installer,
    _create_claude_settings without actually invoking subprocess for Go builds.
    """
    cmd = PackageCommand()

    # _create_config needs a federation identifier and type
    federation_identifier = "arn:aws:iam::123456789012:role/test-role"
    federation_type = "direct"

    # Create config.json
    cmd._create_config(output_dir, profile, federation_identifier, federation_type, profile.name, MagicMock())

    # Generate collector config if sidecar
    _is_sidecar = getattr(profile, "monitoring_mode", "central") == "sidecar"
    _is_idc_auth = getattr(profile, "effective_auth_type", profile.auth_type) == "idc"

    if profile.monitoring_enabled and _is_sidecar:
        if _is_idc_auth:
            cmd._generate_collector_config(
                output_dir=output_dir,
                template_name="collector-config-idc.yaml",
                region=profile.aws_region or "us-east-1",
                idc_user_email="test@example.com",
            )
        else:
            cmd._generate_collector_config(
                output_dir=output_dir,
                template_name="collector-config.yaml",
                region=profile.aws_region or "us-east-1",
            )

    # Create installer
    if built_executables is None:
        built_executables = []
    if built_otel_helpers is None:
        built_otel_helpers = []

    # Ensure installer prerequisites exist
    (output_dir / "claude-settings").mkdir(exist_ok=True)
    cmd._create_installer(output_dir, profile, built_executables, built_otel_helpers)

    # Create Claude settings
    cmd._create_claude_settings(output_dir, profile)


# ---------------------------------------------------------------------------
# Tests: OIDC Sidecar Profile Manifest
# ---------------------------------------------------------------------------


class TestOIDCSidecarManifest:
    """OIDC sidecar profile must produce collector-config.yaml and reference otelcol + credential-process."""

    def test_collector_config_present(self, tmp_path):
        """Sidecar OIDC must produce collector-config.yaml."""
        profile = _make_oidc_sidecar_profile()
        _run_config_phase(profile, tmp_path)
        assert (tmp_path / "collector-config.yaml").exists(), (
            "collector-config.yaml missing from OIDC sidecar package — "
            "local collector will have no configuration."
        )

    def test_collector_config_has_region(self, tmp_path):
        """collector-config.yaml must have the region substituted (no ${REGION} placeholders)."""
        profile = _make_oidc_sidecar_profile()
        _run_config_phase(profile, tmp_path)
        content = (tmp_path / "collector-config.yaml").read_text(encoding="utf-8")
        assert "${REGION}" not in content
        assert "us-east-1" in content

    def test_installer_references_otelcol(self, tmp_path):
        """Installer must reference otelcol binary for sidecar deployment."""
        profile = _make_oidc_sidecar_profile()
        # Create a dummy executable so installer generation succeeds
        dummy_exec = tmp_path / "credential-process-macos-arm64"
        dummy_exec.touch()
        built_executables = [("macos-arm64", dummy_exec)]
        _run_config_phase(profile, tmp_path, built_executables=built_executables)

        installer = tmp_path / "install.sh"
        assert installer.exists(), "install.sh not generated"
        content = installer.read_text(encoding="utf-8")
        assert "otelcol" in content, (
            "Installer does not reference otelcol — sidecar collector will not be installed."
        )

    def test_installer_references_credential_process(self, tmp_path):
        """Installer must reference credential-process binary."""
        profile = _make_oidc_sidecar_profile()
        dummy_exec = tmp_path / "credential-process-macos-arm64"
        dummy_exec.touch()
        built_executables = [("macos-arm64", dummy_exec)]
        _run_config_phase(profile, tmp_path, built_executables=built_executables)

        installer = tmp_path / "install.sh"
        assert installer.exists()
        content = installer.read_text(encoding="utf-8")
        assert "credential-process" in content, (
            "Installer does not reference credential-process binary."
        )

    def test_claude_settings_has_otel_endpoint(self, tmp_path):
        """Claude settings must configure OTEL endpoint for sidecar (localhost:4318)."""
        profile = _make_oidc_sidecar_profile()
        _run_config_phase(profile, tmp_path)

        settings_path = tmp_path / "claude-settings" / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert settings["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"


# ---------------------------------------------------------------------------
# Tests: OIDC Central Profile Manifest
# ---------------------------------------------------------------------------


class TestOIDCCentralManifest:
    """OIDC central profile must NOT produce collector-config.yaml or reference otelcol."""

    def test_no_collector_config(self, tmp_path):
        """Central mode must NOT produce collector-config.yaml (collector runs on ECS)."""
        profile = _make_oidc_central_profile()
        _run_config_phase(profile, tmp_path)
        assert not (tmp_path / "collector-config.yaml").exists(), (
            "collector-config.yaml should NOT exist for central monitoring — "
            "it would confuse the installer into deploying a local collector."
        )

    def test_no_otelcol_in_output(self, tmp_path):
        """Central mode should not ship otelcol binaries."""
        profile = _make_oidc_central_profile()
        _run_config_phase(profile, tmp_path)
        otelcol_files = list(tmp_path.glob("otelcol-*"))
        assert len(otelcol_files) == 0, (
            f"Unexpected otelcol binaries in central mode package: {otelcol_files}"
        )

    def test_installer_still_valid(self, tmp_path):
        """Central mode must still produce a usable installer."""
        profile = _make_oidc_central_profile()
        dummy_exec = tmp_path / "credential-process-macos-arm64"
        dummy_exec.touch()
        built_executables = [("macos-arm64", dummy_exec)]
        _run_config_phase(profile, tmp_path, built_executables=built_executables)

        installer = tmp_path / "install.sh"
        assert installer.exists()
        content = installer.read_text(encoding="utf-8")
        # Central mode installer should NOT try to install a local collector
        assert "credential-process" in content


# ---------------------------------------------------------------------------
# Tests: IDC Zero-Binary Manifest
# ---------------------------------------------------------------------------


class TestIDCZeroBinaryManifest:
    """IDC zero-binary mode must NOT include Go binaries but MUST include collector-config.yaml."""

    def test_no_go_binaries_in_output(self, tmp_path):
        """IDC zero-binary must not produce credential-process or otel-helper binaries."""
        profile = _make_idc_zero_binary_profile()
        _run_config_phase(profile, tmp_path)
        # No credential-process-* or otel-helper-* files should exist
        cred_binaries = list(tmp_path.glob("credential-process-*"))
        otel_binaries = list(tmp_path.glob("otel-helper-*"))
        assert len(cred_binaries) == 0, (
            f"credential-process binaries found in IDC zero-binary package: {cred_binaries}"
        )
        assert len(otel_binaries) == 0, (
            f"otel-helper binaries found in IDC zero-binary package: {otel_binaries}"
        )

    def test_collector_config_present_with_idc_template(self, tmp_path):
        """IDC zero-binary sidecar MUST produce collector-config.yaml with static identity."""
        profile = _make_idc_zero_binary_profile()
        _run_config_phase(profile, tmp_path)
        assert (tmp_path / "collector-config.yaml").exists(), (
            "collector-config.yaml missing from IDC zero-binary sidecar package."
        )

    def test_collector_config_has_static_identity(self, tmp_path):
        """IDC collector config must bake in the user email (no runtime otel-helper)."""
        profile = _make_idc_zero_binary_profile()
        _run_config_phase(profile, tmp_path)
        content = (tmp_path / "collector-config.yaml").read_text(encoding="utf-8")
        assert "test@example.com" in content, (
            "IDC collector-config.yaml does not contain baked-in user email."
        )
        assert "${USER_EMAIL}" not in content, (
            "IDC collector-config.yaml still has ${USER_EMAIL} placeholder — "
            "identity was not substituted."
        )

    def test_no_otelcol_binaries(self, tmp_path):
        """IDC zero-binary must NOT include otelcol binaries (no Go toolchain assumed)."""
        profile = _make_idc_zero_binary_profile()
        _run_config_phase(profile, tmp_path)
        otelcol_files = list(tmp_path.glob("otelcol-*"))
        assert len(otelcol_files) == 0, (
            f"otelcol binaries found in IDC zero-binary package: {otelcol_files} — "
            "IDC zero-binary contract assumes no build tools on admin machine."
        )


# ---------------------------------------------------------------------------
# Tests: Structural Wiring (source-level guards)
# ---------------------------------------------------------------------------


class TestPackageWiringCompleteness:
    """Source-level assertions that handle() calls all required build methods.

    These tests use inspect.getsource() to verify call sites exist, catching
    deletions in code review (like the PR #338 otelcol regression).
    """

    def test_handle_calls_build_go_binaries(self):
        """handle() must call _build_go_binaries for Go cross-compilation."""
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        assert "_build_go_binaries" in src, (
            "_build_go_binaries call missing from handle() — "
            "Go cross-compilation is broken."
        )

    def test_handle_calls_build_otelcol(self):
        """handle() must call _build_otelcol for sidecar profiles."""
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        assert "_build_otelcol" in src, (
            "_build_otelcol call missing from handle() — "
            "sidecar packages will not include the collector binary."
        )

    def test_handle_calls_generate_collector_config(self):
        """handle() must call _generate_collector_config for sidecar profiles."""
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        assert "_generate_collector_config" in src, (
            "_generate_collector_config call missing from handle() — "
            "sidecar packages will ship without collector-config.yaml."
        )

    def test_handle_has_idc_zero_binary_guard(self):
        """handle() must skip binary builds for IDC zero-binary mode."""
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        assert "is_idc_zero_binary" in src, (
            "IDC zero-binary guard missing from handle() — "
            "would attempt to build binaries on machines without Go."
        )

    def test_sidecar_guard_on_otelcol_build(self):
        """_build_otelcol call must be guarded by sidecar mode check."""
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        # Verify both the call and the sidecar guard exist
        assert "_build_otelcol" in src
        assert "sidecar" in src, (
            "No sidecar guard around _build_otelcol — "
            "collector would be built unnecessarily for central mode."
        )
