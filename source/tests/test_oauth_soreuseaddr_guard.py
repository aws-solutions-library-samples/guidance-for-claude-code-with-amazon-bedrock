# ABOUTME: Tests that SO_REUSEADDR on the OAuth port-lock socket is guarded to non-Windows
# ABOUTME: On Windows SO_REUSEADDR lets a 2nd active listener bind the same port (defeats #428 lock)
"""SO_REUSEADDR must be set on POSIX but NOT on Windows.

PR #429 (merged) added SO_REUSEADDR to the port-lock socket to fix a macOS/Linux
TIME_WAIT regression, but applied it unconditionally. On Windows SO_REUSEADDR before
bind() lets a SECOND active listener bind the SAME port, which defeats the
inter-process port lock (#428) and can reintroduce the cold-start double-browser bug.

These tests pin the platform-conditional behavior at both bind sites:
run() and authenticate_for_monitoring().
"""

import errno
import socket
from unittest.mock import MagicMock, patch

import pytest

import credential_provider.__main__ as cp


@pytest.fixture
def auth():
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
        patch.object(cp.MultiProviderAuth, "_load_config", return_value=config),
        patch.object(cp.MultiProviderAuth, "_init_credential_storage"),
    ):
        return cp.MultiProviderAuth(profile="TestProfile")


def _reuseaddr_was_set(mock_sock):
    """True if setsockopt(SOL_SOCKET, SO_REUSEADDR, 1) was called on the socket."""
    for call in mock_sock.setsockopt.call_args_list:
        if call.args[:3] == (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1):
            return True
    return False


def _make_lock_socket():
    """A mock lock socket whose bind() raises EADDRINUSE to short-circuit the flow
    right after the (guarded) setsockopt call."""
    mock_sock = MagicMock()
    mock_sock.bind.side_effect = OSError(errno.EADDRINUSE, "in use")
    return mock_sock


# --- run() bind site ---


@pytest.mark.parametrize("system,expected", [("Windows", False), ("Linux", True), ("Darwin", True)])
def test_run_reuseaddr_guarded_by_platform(auth, system, expected):
    mock_sock = _make_lock_socket()
    with (
        patch.object(cp.platform, "system", return_value=system),
        patch.object(cp.socket, "socket", return_value=mock_sock),
        patch.object(auth, "get_cached_credentials", return_value=None),
        patch.object(auth, "_wait_for_auth_completion", return_value=None),
        patch("builtins.print"),
    ):
        auth.run()
    assert _reuseaddr_was_set(mock_sock) is expected


# --- authenticate_for_monitoring() bind site ---


@pytest.mark.parametrize("system,expected", [("Windows", False), ("Linux", True), ("Darwin", True)])
def test_monitoring_reuseaddr_guarded_by_platform(auth, system, expected):
    mock_sock = _make_lock_socket()
    with (
        patch.object(cp.platform, "system", return_value=system),
        patch.object(cp.socket, "socket", return_value=mock_sock),
        patch.object(auth, "_wait_for_auth_completion", return_value=None),
        patch.object(auth, "get_monitoring_token", return_value=None),
    ):
        auth.authenticate_for_monitoring()
    assert _reuseaddr_was_set(mock_sock) is expected
