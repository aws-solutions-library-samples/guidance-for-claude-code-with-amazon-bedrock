# ABOUTME: Regression tests for IDC credential-refresh hooks in generated settings.json
# ABOUTME: IDC wires awsCredentialExport (silent refresh) + awsAuthRefresh --login (visible sign-in message)

"""Regression tests: IDC profiles wire BOTH credential hooks, each for its role.

Claude Code has two credential hooks that (verified empirically) work together:
  - awsCredentialExport — output captured SILENTLY; the primary resolver,
    re-invoked ~5 min before the emitted Expiration. Drives the silent hourly
    STS role-credential refresh while the SSO session is still valid.
  - awsAuthRefresh — output is DISPLAYED to the user; fires on the first
    credential failure. The ONLY channel that surfaces the binary's sign-in
    message, because awsCredentialExport discards stderr.

IDC needs both:
  - Without awsCredentialExport, 1-hour role creds expire mid-session with no
    re-invoke -> retry loop -> (on EC2) silent instance-role fallback.
  - Without awsAuthRefresh, a missing SSO session produces a silent retry loop
    with no message (awsCredentialExport swallows the fail-fast instruction).

awsAuthRefresh uses `--login` (sign-in only): its output is shown to the user, so
it must NOT print credentials. The fail-fast guard makes `--login` exit
immediately when run non-interactively, so it surfaces the "relaunch with
claude-bedrock" message instead of hanging (the original reason it was dropped).

Non-IDC (OIDC) session profiles keep just awsAuthRefresh (full flow), unchanged.
"""

import json
import tempfile
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


def _idc_profile(credential_storage: str = "session") -> Profile:
    return Profile(
        name="idc-test",
        provider_domain="",
        client_id="",
        credential_storage=credential_storage,
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        allowed_bedrock_regions=["us-east-1", "us-west-2"],
        cross_region_profile="us",
        auth_type="idc",
        sso_enabled=False,
        idc_start_url="https://d-1234567890.awsapps.com/start",
        idc_account_id="123456789012",
        idc_permission_set_name="ClaudeCodeRole",
    )


def _oidc_session_profile() -> Profile:
    return Profile(
        name="oidc-test",
        provider_domain="test.okta.com",
        client_id="test-client-id",
        credential_storage="session",
        aws_region="us-east-1",
        identity_pool_name="test-pool",
        allowed_bedrock_regions=["us-east-1", "us-west-2"],
        cross_region_profile="us",
        auth_type="oidc",
        sso_enabled=True,
    )


def _read_settings(output_dir: Path) -> dict:
    settings_path = output_dir / "claude-settings" / "settings.json"
    with open(settings_path, encoding="utf-8") as f:
        return json.load(f)


class TestIdcCredentialHooks:
    def test_idc_session_wires_auth_refresh_with_login(self):
        """awsAuthRefresh is the only hook whose output is displayed, so it must
        be wired for IDC to surface the sign-in message. It uses --login (shown
        to the user, never prints credentials) and is safe from the old deadlock
        because the fail-fast guard exits immediately when non-interactive."""
        command = PackageCommand()
        profile = _idc_profile(credential_storage="session")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="idc-test")
            settings = _read_settings(output_dir)

        refresh = settings.get("awsAuthRefresh")
        assert refresh is not None, "IDC must wire awsAuthRefresh to display the sign-in message"
        assert "--login" in refresh, "awsAuthRefresh output is displayed, so it must use --login (no credential leak)"
        assert "--profile idc-test" in refresh

    def test_idc_keyring_wires_auth_refresh_with_login(self):
        command = PackageCommand()
        profile = _idc_profile(credential_storage="keyring")

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="idc-test")
            settings = _read_settings(output_dir)

        refresh = settings.get("awsAuthRefresh")
        assert refresh is not None
        assert "--login" in refresh

    def test_idc_credential_process_env_is_full_flow(self):
        """The silent AWS_CREDENTIAL_PROCESS path remains the full flow (it
        returns credential JSON to the SDK) and is targeted at the profile."""
        command = PackageCommand()
        profile = _idc_profile()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="idc-test")
            settings = _read_settings(output_dir)

        cred_process = settings["env"]["AWS_CREDENTIAL_PROCESS"]
        assert "--login" not in cred_process, "credential resolution must run the full flow, not --login"
        assert "--profile idc-test" in cred_process

    def test_idc_wires_credential_export_for_refresh(self):
        """Regression: AWS_CREDENTIAL_PROCESS is resolved once at startup and
        cached, so IDC role creds (1h permission-set lifetime) expire mid-session
        with no re-invoke -> retry loop -> instance-role fallback. awsCredentialExport
        gives Claude Code a silent, timer-driven refresh (~5 min before Expiration)
        without the interactive deadlock that ruled out awsAuthRefresh for IDC."""
        for storage in ("session", "keyring"):
            command = PackageCommand()
            profile = _idc_profile(credential_storage=storage)
            with tempfile.TemporaryDirectory() as tmpdir:
                output_dir = Path(tmpdir)
                command._create_claude_settings(output_dir, profile, profile_name="idc-test")
                settings = _read_settings(output_dir)

            export = settings.get("awsCredentialExport")
            assert export is not None, f"IDC ({storage}) must wire awsCredentialExport for refresh"
            # Refresh must run the full credential flow (returns JSON), not --login.
            assert "--login" not in export
            assert "--profile idc-test" in export

    def test_idc_disables_instance_metadata_fallback(self):
        """With IMDS disabled, a refresh failure surfaces as a clear credentials
        error instead of silently falling back to the EC2 instance role (wrong
        identity, broken attribution/quota)."""
        command = PackageCommand()
        profile = _idc_profile()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="idc-test")
            settings = _read_settings(output_dir)

        assert settings["env"].get("AWS_EC2_METADATA_DISABLED") == "true"

    def test_oidc_does_not_disable_instance_metadata(self):
        """The IMDS guard is IDC-specific; OIDC must not get it."""
        command = PackageCommand()
        profile = _oidc_session_profile()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="oidc-test")
            settings = _read_settings(output_dir)

        assert "AWS_EC2_METADATA_DISABLED" not in settings["env"]
        # OIDC must NOT get awsCredentialExport (keeps awsAuthRefresh instead).
        assert "awsCredentialExport" not in settings

    def test_oidc_session_auth_refresh_unchanged(self):
        """Non-IDC session profiles keep the existing full credential-process
        awsAuthRefresh command (no --login) — this path is unchanged."""
        command = PackageCommand()
        profile = _oidc_session_profile()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            command._create_claude_settings(output_dir, profile, profile_name="oidc-test")
            settings = _read_settings(output_dir)

        refresh = settings.get("awsAuthRefresh")
        assert refresh is not None
        assert "--login" not in refresh
        assert "--profile oidc-test" in refresh
