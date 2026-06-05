# ABOUTME: Tests for the Windows chunked monitoring-token keyring storage (#427 fix)
# ABOUTME: Regression coverage for scouturier's PR #429 finding #3 (recoverable orphan chunks)
"""Tests for Windows monitoring-token chunk hygiene on save and clear.

PR #429 added a chunked Windows keyring format for the monitoring id_token
({profile}-monitoring-1..N + {profile}-monitoring-meta) to fix #427. scouturier's
review (finding #3) showed the cleanup paths trust meta.count, so:

  - SAVE of a shorter token leaves higher-index chunks from a prior larger token
    behind (a recoverable plaintext tail), and
  - CLEAR only expires 1..meta.count and is gated on meta presence, so a meta-less
    chunk set (e.g. a crash between the chunk writes and the meta write) is never
    scrubbed.

These tests pin both behaviors.
"""

from unittest.mock import patch

import pytest

SERVICE = "claude-code-with-bedrock"
PROFILE = "TestProfile"


class FakeKeyring:
    """In-memory keyring backend keyed by (service, name)."""

    def __init__(self):
        self.store = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        # Real backends raise if absent; callers here only delete when present.
        self.store.pop((service, name), None)


def _entry(name):
    return (SERVICE, f"{PROFILE}-{name}")


@pytest.fixture
def auth():
    """A keyring-mode MultiProviderAuth instance with config/storage mocked out."""
    config = {
        "provider_domain": "test.okta.com",
        "client_id": "test-client-id",
        "identity_pool_id": "us-east-1:test-pool",
        "aws_region": "us-east-1",
        "credential_storage": "keyring",
        "provider_type": "okta",
        "federation_type": "cognito",
        "max_session_duration": 28800,
    }
    with (
        patch("credential_provider.__main__.MultiProviderAuth._load_config", return_value=config),
        patch("credential_provider.__main__.MultiProviderAuth._init_credential_storage"),
    ):
        from credential_provider.__main__ import MultiProviderAuth

        instance = MultiProviderAuth(profile=PROFILE)
        instance.credential_storage = "keyring"
        return instance


@pytest.fixture
def fake_keyring():
    fk = FakeKeyring()
    with patch("credential_provider.__main__.keyring", fk):
        yield fk


def test_save_purges_orphaned_chunks_when_token_shrinks(auth, fake_keyring):
    """A shorter token must not leave a prior, larger token's tail chunk behind."""
    big = {"token": "A" * 2500, "expires": 111, "email": "a@example.com", "profile": PROFILE}
    auth._save_monitoring_keyring_windows(big)
    # 2500 chars / 1000 -> 3 chunks
    assert fake_keyring.get_password(*_entry("monitoring-3")) is not None
    assert fake_keyring.get_password(*_entry("monitoring-meta")) is not None

    small = {"token": "B" * 1500, "expires": 222, "email": "a@example.com", "profile": PROFILE}
    auth._save_monitoring_keyring_windows(small)
    # 1500 chars / 1000 -> 2 chunks; the old chunk 3 must be gone, not left holding "AAA...".
    assert fake_keyring.get_password(*_entry("monitoring-3")) is None

    # And the reassembled token is exactly the new one (no stale tail).
    assert auth._read_monitoring_keyring_windows()["token"] == "B" * 1500


def test_clear_expires_orphaned_chunk_beyond_meta_count(auth, fake_keyring):
    """clear_cached_credentials must scrub chunks beyond the (stale) meta.count."""
    fake_keyring.set_password(*_entry("monitoring-1"), "AAA")
    fake_keyring.set_password(*_entry("monitoring-2"), "BBB")
    fake_keyring.set_password(*_entry("monitoring-3"), "CCC")  # orphan from a larger prior token
    fake_keyring.set_password(
        *_entry("monitoring-meta"),
        '{"count": 2, "expires": 999, "email": "a@example.com", "profile": "TestProfile"}',
    )

    with patch("credential_provider.__main__.platform.system", return_value="Windows"):
        auth.clear_cached_credentials()

    assert fake_keyring.get_password(*_entry("monitoring-3")) == "EXPIRED"


def test_clear_scrubs_chunks_when_meta_is_absent(auth, fake_keyring):
    """A meta-less chunk set (crash between chunk and meta writes) must still be cleared."""
    fake_keyring.set_password(*_entry("monitoring-1"), "AAA")
    fake_keyring.set_password(*_entry("monitoring-2"), "BBB")
    # No -monitoring-meta entry on purpose.

    with patch("credential_provider.__main__.platform.system", return_value="Windows"):
        auth.clear_cached_credentials()

    assert fake_keyring.get_password(*_entry("monitoring-1")) == "EXPIRED"
    assert fake_keyring.get_password(*_entry("monitoring-2")) == "EXPIRED"
