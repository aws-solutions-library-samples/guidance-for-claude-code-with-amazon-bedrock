# ABOUTME: Regression test ensuring ccwb init lets you set max_session_duration and retains it
# ABOUTME: Guards against the hardcoded clobber that reset the value on every re-run

"""Regression tests: `ccwb init` must let users set max_session_duration and
must not reset a previously configured value when re-run.

The OIDC step of `_gather_configuration` used to unconditionally overwrite
``config["max_session_duration"]`` with a federation-type default (43200 for
direct STS, 28800 for Cognito). That silently discarded any custom value on
every re-run and gave users no way to change it. These tests drive the OIDC
step and inspect the config captured at the ``oidc_complete`` checkpoint.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import questionary

from claude_code_with_bedrock.cli.commands.init import InitCommand


class _StopAtOidcComplete(Exception):
    """Raised from progress.save_step once the OIDC step finishes."""


def _run_oidc_step(existing_config=None, duration_answer=None):
    """Drive `_gather_configuration` through the OIDC step for an Okta provider.

    Returns the in-memory config dict captured when the wizard reaches the
    ``oidc_complete`` checkpoint (right after max_session_duration is resolved).

    Args:
        existing_config: if provided, seeds the wizard as an update-in-place run.
        duration_answer: value the "Max session duration" prompt returns. When
            None, the prompt returns its own default (simulates pressing Enter).
    """
    captured = {}

    progress = MagicMock()
    progress.get_last_step.return_value = None
    progress.get_saved_data.return_value = {}

    def save_step(step, data=None, *a, **k):
        if step == "oidc_complete":
            captured["config"] = dict(data)
            raise _StopAtOidcComplete()

    progress.save_step.side_effect = save_step

    def fake_select(message, *a, **k):
        m = MagicMock()
        text = str(message)
        if "authentication method" in text:
            m.ask.return_value = "oidc"
        elif "credential" in text.lower() or "storage" in text.lower():
            m.ask.return_value = "keyring"
        elif "Federation type" in text:
            m.ask.return_value = "direct"
        else:
            m.ask.return_value = None
        return m

    def fake_text(message, *a, **k):
        m = MagicMock()
        text = str(message)
        if "Max session duration" in text:
            m.ask.return_value = duration_answer if duration_answer is not None else k.get("default")
        elif "provider domain" in text:
            m.ask.return_value = "company.okta.com"
        elif "Client ID" in text:
            m.ask.return_value = "0oa1234567890xyz"
        else:
            m.ask.return_value = k.get("default", "")
        return m

    def fake_confirm(*a, **k):
        m = MagicMock()
        m.ask.return_value = False
        return m

    cmd = InitCommand()
    with (
        patch.object(questionary, "select", fake_select),
        patch.object(questionary, "text", fake_text),
        patch.object(questionary, "confirm", fake_confirm),
    ):
        try:
            cmd._gather_configuration(progress, existing_config=existing_config)
        except _StopAtOidcComplete:
            pass

    assert "config" in captured, "wizard never reached the oidc_complete checkpoint"
    return captured["config"]


def test_can_set_custom_max_session_duration():
    """A user-entered duration must be written to config, not the hardcoded default."""
    config = _run_oidc_step(duration_answer="21600")
    assert config["max_session_duration"] == 21600


def test_rerun_retains_custom_max_session_duration():
    """Re-running init and accepting the default must keep the existing value."""
    existing = {
        "okta": {"domain": "company.okta.com", "client_id": "0oa1234567890xyz"},
        "max_session_duration": 14400,
    }
    # duration_answer=None -> prompt returns its own default, i.e. the user
    # presses Enter to accept. The default must be the existing 14400.
    config = _run_oidc_step(existing_config=existing, duration_answer=None)
    assert config["max_session_duration"] == 14400


@pytest.mark.parametrize("federation,expected", [("direct", 43200), ("cognito", 28800)])
def test_default_duration_follows_federation_type(federation, expected):
    """With no prior value, the prompt default matches the federation recommendation."""

    def fake_select(message, *a, **k):
        m = MagicMock()
        text = str(message)
        if "authentication method" in text:
            m.ask.return_value = "oidc"
        elif "credential" in text.lower() or "storage" in text.lower():
            m.ask.return_value = "keyring"
        elif "Federation type" in text:
            m.ask.return_value = federation
        else:
            m.ask.return_value = None
        return m

    captured = {}
    progress = MagicMock()
    progress.get_last_step.return_value = None
    progress.get_saved_data.return_value = {}

    def save_step(step, data=None, *a, **k):
        if step == "oidc_complete":
            captured["config"] = dict(data)
            raise _StopAtOidcComplete()

    progress.save_step.side_effect = save_step

    def fake_text(message, *a, **k):
        m = MagicMock()
        text = str(message)
        if "Max session duration" in text:
            # Accept whatever default the wizard proposes.
            m.ask.return_value = k.get("default")
        elif "provider domain" in text:
            m.ask.return_value = "company.okta.com"
        elif "Client ID" in text:
            m.ask.return_value = "0oa1234567890xyz"
        else:
            m.ask.return_value = k.get("default", "")
        return m

    def fake_confirm(*a, **k):
        m = MagicMock()
        m.ask.return_value = False
        return m

    cmd = InitCommand()
    with (
        patch.object(questionary, "select", fake_select),
        patch.object(questionary, "text", fake_text),
        patch.object(questionary, "confirm", fake_confirm),
    ):
        try:
            cmd._gather_configuration(progress)
        except _StopAtOidcComplete:
            pass

    assert captured["config"]["max_session_duration"] == expected
