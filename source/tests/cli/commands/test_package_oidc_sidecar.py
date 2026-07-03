# ABOUTME: Regression tests for OIDC sidecar otelcol packaging gap (fix/oidc-sidecar-otelcol-packaging)
# ABOUTME: Verifies that sidecar mode writes http://localhost:4318, ships collector-config.yaml,
# ABOUTME: and that the installer template includes otelcol download + collector profile logic.

"""Tests for OIDC sidecar monitoring package correctness."""

import json
import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


def _make_oidc_profile(
    monitoring_mode="sidecar", monitoring_enabled=True, endpoint: str | None = "https://alb.example.com"
):
    return Profile(
        name="test-oidc",
        provider_domain="auth.example.com",
        client_id="client-abc",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        auth_type="oidc",
        monitoring_enabled=monitoring_enabled,
        monitoring_mode=monitoring_mode,
        otel_collector_endpoint=endpoint,
    )


class TestSidecarEndpointOverride:
    """_create_claude_settings must use http://localhost:4318 for sidecar mode."""

    def test_sidecar_mode_writes_localhost_endpoint(self):
        """OIDC sidecar profile must have OTEL endpoint set to http://localhost:4318."""
        command = PackageCommand()
        profile = _make_oidc_profile(monitoring_mode="sidecar")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

            settings_path = output_dir / "claude-settings" / "settings.json"
            settings = json.loads(settings_path.read_text())
            assert settings["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"

    def test_sidecar_without_saved_endpoint_still_configures_localhost(self):
        """Regression: real sidecar deploys have NO saved otel_collector_endpoint
        (there is no central monitoring stack to read one from). Telemetry must
        still be configured to http://localhost:4318 — the previous code only
        applied the localhost override *after* resolving a non-empty endpoint, so
        a None endpoint fell through to the 'no endpoint found' path and telemetry
        was silently left unconfigured."""
        command = PackageCommand()
        profile = _make_oidc_profile(monitoring_mode="sidecar", endpoint=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

            settings_path = output_dir / "claude-settings" / "settings.json"
            settings = json.loads(settings_path.read_text())
            assert settings["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"
            assert settings["env"]["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"

    def test_central_mode_preserves_profile_endpoint(self):
        """Central mode must NOT override the ALB endpoint with localhost."""
        command = PackageCommand()
        profile = _make_oidc_profile(monitoring_mode="central", endpoint="https://alb.example.com")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

            settings_path = output_dir / "claude-settings" / "settings.json"
            settings = json.loads(settings_path.read_text())
            assert settings["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://alb.example.com"

    def test_sidecar_does_not_log_http_warning(self, capsys):
        """Sidecar mode should not emit the 'Using HTTP endpoint' warning."""
        command = PackageCommand()
        profile = _make_oidc_profile(monitoring_mode="sidecar")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile)

        # The rich console prints to stdout; read what was captured
        captured = capsys.readouterr()
        assert "WARNING: Using HTTP endpoint" not in captured.out


def _make_idc_profile(monitoring_mode="sidecar", monitoring_enabled=True, quota=False):
    return Profile(
        name="test-idc",
        provider_domain="",
        client_id="",
        credential_storage="keyring",
        aws_region="us-east-1",
        identity_pool_name="",
        auth_type="idc",
        monitoring_enabled=monitoring_enabled,
        monitoring_mode=monitoring_mode,
        quota_api_endpoint="https://quota.example.com/check" if quota else None,
    )


class TestOIDCSidecarCollectorConfig:
    """Package must include collector-config.yaml for OIDC and IDC sidecar profiles."""

    def test_oidc_sidecar_produces_collector_config(self, tmp_path):
        """OIDC + sidecar → _generate_collector_config writes collector-config.yaml."""
        profile = _make_oidc_profile(monitoring_mode="sidecar")
        cmd = PackageCommand()
        cmd._generate_collector_config(
            output_dir=tmp_path,
            template_name="collector-config.yaml",
            region=profile.aws_region,
        )
        assert (tmp_path / "collector-config.yaml").exists()

    def test_collector_config_region_substituted(self, tmp_path):
        """${REGION} placeholder must be replaced by _generate_collector_config."""
        profile = _make_oidc_profile(monitoring_mode="sidecar")
        cmd = PackageCommand()
        cmd._generate_collector_config(
            output_dir=tmp_path,
            template_name="collector-config.yaml",
            region=profile.aws_region,
        )
        content = (tmp_path / "collector-config.yaml").read_text()
        assert "${REGION}" not in content
        assert "us-east-1" in content

    def test_oidc_central_mode_no_collector_config(self, tmp_path):
        """OIDC central mode must NOT call _generate_collector_config."""
        profile = _make_oidc_profile(monitoring_mode="central")
        _is_sidecar = getattr(profile, "monitoring_mode", "central") == "sidecar"
        assert not _is_sidecar
        assert not (tmp_path / "collector-config.yaml").exists()

    def test_idc_sidecar_produces_collector_config(self, tmp_path):
        """IDC + sidecar → _generate_collector_config writes collector-config.yaml with static identity."""
        cmd = PackageCommand()
        cmd._generate_collector_config(
            output_dir=tmp_path,
            template_name="collector-config-idc.yaml",
            region="us-east-1",
            idc_user_email="alice@example.com",
        )
        assert (tmp_path / "collector-config.yaml").exists()
        content = (tmp_path / "collector-config.yaml").read_text()
        assert "alice@example.com" in content
        assert "${USER_EMAIL}" not in content
        assert "${REGION}" not in content

    def test_idc_quota_sidecar_produces_collector_config(self, tmp_path):
        """IDC + quota + sidecar must also produce collector-config.yaml.

        is_idc_zero_binary=False when quota is set, so previously neither
        the zero-binary block nor the OIDC block fired — no config was written.
        """
        cmd = PackageCommand()
        cmd._generate_collector_config(
            output_dir=tmp_path,
            template_name="collector-config-idc.yaml",
            region="us-east-1",
            idc_user_email="bob@example.com",
        )
        assert (tmp_path / "collector-config.yaml").exists()
        content = (tmp_path / "collector-config.yaml").read_text()
        assert "bob@example.com" in content


class TestInstallerOtelcolBlock:
    """install.sh must COPY the bundled otelcol binary (not download it) when present."""

    def _get_installer(self, profile):
        command = PackageCommand()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "config.json").write_text("{}")
            (output_dir / "claude-settings").mkdir()
            built_executables = [("macos-arm64", output_dir / "credential-process-macos-arm64")]
            (output_dir / "credential-process-macos-arm64").touch()
            return command._create_installer(output_dir, profile, built_executables, built_otel_helpers=[]).read_text(
                encoding="utf-8"
            )

    def test_installer_copies_bundled_otelcol(self):
        """Installer must reference the shipped otelcol-$BINARY_SUFFIX binary, not download it."""
        profile = _make_oidc_profile(monitoring_mode="sidecar")
        content = self._get_installer(profile)
        assert "otelcol-$BINARY_SUFFIX" in content
        assert "collector-config.yaml" in content

    def test_installer_does_not_download_otelcol_contrib(self):
        """Regression: the install-time GitHub download of otelcol-contrib must be gone.

        otelcol is now built via OCB and shipped IN the package (like credential-process
        and otel-helper). The end-user installer must never reach out to GitHub.
        """
        profile = _make_oidc_profile(monitoring_mode="sidecar")
        content = self._get_installer(profile)
        assert "opentelemetry-collector-releases" not in content
        assert "otelcol-contrib" not in content

    def test_installer_warns_when_binary_missing(self):
        """If config is present but the collector binary wasn't built, the installer must warn."""
        profile = _make_oidc_profile(monitoring_mode="sidecar")
        content = self._get_installer(profile)
        # The elif branch warns the admin to rebuild with Go installed
        assert "collector binary" in content

    def test_installer_creates_collector_aws_profile(self):
        """Installer must create a <profile>-collector AWS profile for SigV4 auth."""
        profile = _make_oidc_profile(monitoring_mode="sidecar")
        content = self._get_installer(profile)
        assert "-collector" in content

    def test_installer_collector_profile_uses_credential_process(self):
        """The -collector profile must resolve creds via credential_process (auto-refresh)."""
        profile = _make_oidc_profile(monitoring_mode="sidecar")
        content = self._get_installer(profile)
        assert "${PROFILE_NAME}-collector" in content
        # The comment must NOT claim the false 'infinite recursion' rationale
        assert "infinite recursion" not in content

    def test_central_mode_installer_still_valid(self):
        """Central mode profile must still produce a valid installer (collector block is gated)."""
        profile = _make_oidc_profile(monitoring_mode="central")
        content = self._get_installer(profile)
        # collector-config.yaml guard must be present so the block stays conditional
        assert "collector-config.yaml" in content


class TestBuildOtelcolTargets:
    """The restored _build_otelcol must resolve platforms via the shared _GO_PLATFORM_MAP."""

    def test_shared_platform_map_used_by_both_builds(self):
        """_GO_PLATFORM_MAP and _go_ldflags exist and are the single source of truth."""
        from claude_code_with_bedrock.cli.commands.package import _GO_PLATFORM_MAP

        assert _GO_PLATFORM_MAP["macos-arm64"] == ("darwin", "arm64")
        assert _GO_PLATFORM_MAP["linux-x64"] == ("linux", "amd64")
        assert _GO_PLATFORM_MAP["windows"] == ("windows", "amd64")

    def test_windows_ldflags_not_stripped(self):
        """Windows binaries must NOT be stripped (Defender Wacatac.B!ml on stripped Go)."""
        from claude_code_with_bedrock.cli.commands.package import _go_ldflags

        flags = _go_ldflags("windows")
        assert "-s" not in flags.split()
        assert "-w" not in flags.split()
        # Version injection must still be present
        assert "-X" in flags

    def test_non_windows_ldflags_stripped(self):
        """macOS/Linux binaries are stripped (-s -w) for size."""
        from claude_code_with_bedrock.cli.commands.package import _go_ldflags

        darwin_flags = _go_ldflags("darwin")
        linux_flags = _go_ldflags("linux")
        assert "-s" in darwin_flags and "-w" in darwin_flags
        assert "-s" in linux_flags and "-w" in linux_flags
        # Version injection must also be present
        assert "-X" in darwin_flags
        assert "-X" in linux_flags

    def test_build_otelcol_method_exists(self):
        """_build_otelcol must be restored on PackageCommand (regression for PR #338 removal)."""
        assert hasattr(PackageCommand, "_build_otelcol")

    def test_build_otelcol_called_for_sidecar_profile(self):
        """handle() must invoke _build_otelcol for OIDC sidecar profiles.

        This is the direct regression test for PR #338, which deleted the call site.
        If _build_otelcol is deleted or its call is removed, this test fails.
        """
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        # The call must be present and guarded by monitoring_mode == "sidecar"
        assert "_build_otelcol" in src, (
            "_build_otelcol call missing from handle() — was it deleted again? See PR #338 regression."
        )
        assert "sidecar" in src, "sidecar guard missing from handle() — otelcol would be built for all profiles"

    def test_build_otelcol_uses_go_platform_map(self):
        """_build_otelcol must use _GO_PLATFORM_MAP, not a local copy.

        A local platform_map in _build_otelcol would drift from _build_go_binaries.
        Both must share the same source of truth.
        """
        import inspect

        src = inspect.getsource(PackageCommand._build_otelcol)
        assert "_GO_PLATFORM_MAP" in src, (
            "_build_otelcol has its own local platform map — use the shared _GO_PLATFORM_MAP"
        )

    def test_build_otelcol_uses_go_ldflags(self):
        """_build_otelcol must use _go_ldflags(), not inline '-s -w'.

        Inlining ldflags would silently strip Windows binaries (Wacatac.B!ml AV trigger).
        """
        import inspect

        src = inspect.getsource(PackageCommand._build_otelcol)
        assert "_go_ldflags" in src, "_build_otelcol does not call _go_ldflags() — Windows otelcol would be stripped"

    def test_build_otelcol_supports_windows_ocb(self):
        """_build_otelcol must download a Windows OCB binary when packaging on Windows.

        The previous code fell through to 'linux' on Windows, downloading a non-executable
        binary and silently failing the sidecar build on Windows admin machines.
        """
        import inspect

        src = inspect.getsource(PackageCommand._build_otelcol)
        assert '"windows"' in src, (
            "_build_otelcol has no Windows OCB branch — packaging sidecar from a Windows "
            "admin machine would download a non-executable Linux OCB binary."
        )

    def test_generate_collector_config_method_exists(self):
        """_generate_collector_config must exist as the single testable config-writing path."""
        assert hasattr(PackageCommand, "_generate_collector_config"), (
            "_generate_collector_config missing — collector config tests replicate "
            "production logic inline and will go stale on refactor."
        )

    def test_generate_collector_config_called_in_handle(self):
        """handle() must invoke _generate_collector_config for sidecar profiles.

        Without this call, sidecar packages would ship without a collector-config.yaml,
        leaving the local collector unable to start.
        """
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        assert "_generate_collector_config" in src, (
            "_generate_collector_config call missing from handle() — "
            "sidecar packages will ship without collector-config.yaml."
        )

    def test_build_go_binaries_called_in_handle(self):
        """handle() must invoke _build_go_binaries for Go cross-compilation path.

        This is the primary binary build path for OIDC profiles with use_go=True.
        If the call site is removed, no credential-process or otel-helper binaries
        will be built.
        """
        import inspect

        src = inspect.getsource(PackageCommand.handle)
        assert "_build_go_binaries" in src, (
            "_build_go_binaries call missing from handle() — "
            "Go cross-compilation path is broken, no binaries will be built."
        )
