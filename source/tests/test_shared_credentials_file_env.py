# ABOUTME: Regression tests for #797 — Python credential provider must honor
# ABOUTME: AWS_SHARED_CREDENTIALS_FILE (parity with the Go credential-process).
"""Tests that the Python credential provider honors AWS_SHARED_CREDENTIALS_FILE.

Issue #797: in session-storage mode the provider writes a static profile block
into the AWS shared credentials file. If the provider ignores
AWS_SHARED_CREDENTIALS_FILE (writing/clearing ~/.aws/credentials while the AWS
SDK reads a relocated file, e.g. C:\\ProgramData\\.aws\\credentials), a stale
block in the SDK's file can never be refreshed or cleared — permanently
shadowing credential_process.

The Go binary and the Python provider must resolve the identical path for the
same env value (.claude/rules/credential-helper-parity.md).
"""

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def auth():
    """A session-mode MultiProviderAuth instance with config/storage mocked out."""
    config = {
        "provider_domain": "test.okta.com",
        "client_id": "test-client-id",
        "identity_pool_id": "us-east-1:test-pool",
        "aws_region": "us-east-1",
        "credential_storage": "session",
        "provider_type": "okta",
        "federation_type": "cognito",
        "max_session_duration": 28800,
    }
    with (
        patch("credential_provider.__main__.MultiProviderAuth._load_config", return_value=config),
        patch("credential_provider.__main__.MultiProviderAuth._init_credential_storage"),
    ):
        from credential_provider.__main__ import MultiProviderAuth

        instance = MultiProviderAuth(profile="ClaudeCode")
        instance.credential_storage = "session"
        return instance


def test_helper_honors_env_var(auth, tmp_path, monkeypatch):
    """When AWS_SHARED_CREDENTIALS_FILE is set, the helper returns that path."""
    custom = tmp_path / "relocated" / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(custom))
    assert auth._credentials_file_path() == custom


def test_helper_falls_back_when_unset(auth, monkeypatch):
    """Env unset -> byte-identical to the historical ~/.aws/credentials path.

    This is what makes the change safe for existing installs (none set the var).
    """
    monkeypatch.delenv("AWS_SHARED_CREDENTIALS_FILE", raising=False)
    assert auth._credentials_file_path() == Path.home() / ".aws" / "credentials"


def _example_creds():
    return {
        "Version": 1,
        "AccessKeyId": "AKIAEXAMPLE797",
        "SecretAccessKey": "secret797",
        "SessionToken": "token797",
        "Expiration": "2099-01-01T00:00:00Z",
    }


def test_save_and_read_round_trip_custom_path(auth, tmp_path, monkeypatch):
    """save -> read targets the relocated file, creating parent dirs as needed.

    Mirrors the customer's C:\\ProgramData\\.aws\\credentials scenario.
    """
    custom = tmp_path / "programdata" / ".aws" / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(custom))

    auth.save_to_credentials_file(_example_creds(), "ClaudeCode")

    assert custom.exists(), "credentials must be written to the relocated path"
    got = auth.read_from_credentials_file("ClaudeCode")
    assert got is not None
    assert got["AccessKeyId"] == "AKIAEXAMPLE797"
    assert got["SessionToken"] == "token797"


def test_home_file_untouched_when_env_set(auth, tmp_path, monkeypatch):
    """Divergence guard: with the env var set, save must NOT touch ~/.aws/credentials.

    Pins the #797 defect (provider writes file A while the SDK reads file B). On
    the unfixed code save wrote the home path, overwriting the sentinel -> fails.
    Uses a fake home so a fail-without-fix run never touches the real file.
    """
    fake_home = tmp_path / "home"
    (fake_home / ".aws").mkdir(parents=True)
    home_creds = fake_home / ".aws" / "credentials"
    sentinel = (
        "[ClaudeCode]\naws_access_key_id = HOME_SENTINEL\n"
        "aws_secret_access_key = s\naws_session_token = t\n"
    )
    home_creds.write_text(sentinel)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    custom = tmp_path / "programdata" / ".aws" / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(custom))

    auth.save_to_credentials_file(_example_creds(), "ClaudeCode")
    auth.remove_from_credentials_file("ClaudeCode")

    assert home_creds.read_text() == sentinel, "home credentials file must be untouched"


def test_clear_removes_section_from_custom_path(auth, tmp_path, monkeypatch):
    """The clear/recovery path must DELETE the section from the relocated file.

    Regression for the Python parity gap: the clear path previously wrote an
    "EXPIRED" static placeholder, which (once routed into the SDK-read relocated
    file by #797) would permanently shadow credential_process (#767/#768). It must
    remove the section instead so the SDK falls through and recovers.
    """
    custom = tmp_path / "programdata" / ".aws" / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(custom))

    # Seed a stale block in the relocated file.
    auth.save_to_credentials_file(_example_creds(), "ClaudeCode")
    assert auth.read_from_credentials_file("ClaudeCode") is not None

    auth.remove_from_credentials_file("ClaudeCode")

    # Section gone -> read returns None, and no "EXPIRED" placeholder remains.
    assert auth.read_from_credentials_file("ClaudeCode") is None
    from configparser import ConfigParser

    cfg = ConfigParser(inline_comment_prefixes=())
    cfg.read(custom)
    assert "ClaudeCode" not in cfg, "clear must delete the section, not leave an EXPIRED placeholder"


def test_clear_preserves_other_profiles(auth, tmp_path, monkeypatch):
    """Clearing our profile must not disturb unrelated profiles in the same file."""
    custom = tmp_path / "programdata" / ".aws" / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(custom))

    auth.save_to_credentials_file(_example_creds(), "ClaudeCode")
    auth.save_to_credentials_file(_example_creds(), "OtherProfile")

    auth.remove_from_credentials_file("ClaudeCode")

    from configparser import ConfigParser

    cfg = ConfigParser(inline_comment_prefixes=())
    cfg.read(custom)
    assert "ClaudeCode" not in cfg
    assert "OtherProfile" in cfg, "unrelated profiles must be preserved"


def test_read_missing_custom_path_returns_none(auth, tmp_path, monkeypatch):
    """A missing relocated file is 'no credentials' (None), not an error."""
    custom = tmp_path / "noexist" / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(custom))
    assert auth.read_from_credentials_file("ClaudeCode") is None


def test_go_python_path_parity(auth, tmp_path, monkeypatch):
    """Go and Python must resolve the identical path for the same env value.

    The Go credentialsFilePath() returns AWS_SHARED_CREDENTIALS_FILE verbatim
    when set. Python must match exactly (same string), or the two binaries would
    read/write different files for the same environment.
    """
    custom = tmp_path / "shared" / "credentials"
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(custom))
    # str() of the Python Path must equal the raw env value the Go binary uses.
    assert str(auth._credentials_file_path()) == str(custom)
