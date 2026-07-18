# ABOUTME: Tests for the init wizard extra_files step and its round-trip wiring
# ABOUTME: Covers add/edit/remove/cancel flows and _check_existing_deployment restore

"""Tests for the `ccwb init` extra_files step.

The wizard step (`_configure_extra_files`) must:
- add, edit, and remove entries;
- validate each entry and reject bad ones without saving;
- preserve the existing list on cancel / non-interactive (prompt returns None);
- round-trip through save (_save_configuration) and reload
  (_check_existing_deployment) without drift.
"""

import sys
from pathlib import Path
from unittest.mock import patch

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from claude_code_with_bedrock.cli.commands.init import InitCommand
from claude_code_with_bedrock.config import Config, Profile


class _FakeAsk:
    """Stand-in for a questionary object whose .ask() returns a queued value."""

    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


def _make_profile(extra_files=None) -> Profile:
    return Profile(
        name="test",
        provider_domain="example.okta.com",
        client_id="0oa1234567890",
        identity_pool_name="claude-code-auth",
        credential_storage="keyring",
        aws_region="us-east-1",
        extra_files=extra_files or [],
    )


def _rebuild_config(profile: Profile) -> dict:
    command = InitCommand()
    fake_config = Config()
    with (
        patch.object(Config, "load", return_value=fake_config),
        patch.object(fake_config, "get_profile", return_value=profile),
        patch.object(InitCommand, "_stack_exists", side_effect=Exception("no creds")),
    ):
        return command._check_existing_deployment("test")


class TestExtraFilesRoundTrip:
    """_check_existing_deployment must restore extra_files from the profile."""

    def test_rerun_preserves_extra_files(self):
        entries = [
            {"name": "certs", "targets": "all", "from": "~/secure/certs"},
            {"name": "pre.sh", "targets": ["macos"], "from": "~/x/pre.sh"},
        ]
        rebuilt = _rebuild_config(_make_profile(entries))
        assert rebuilt["extra_files"] == entries

    def test_rerun_empty_extra_files(self):
        rebuilt = _rebuild_config(_make_profile([]))
        assert rebuilt["extra_files"] == []


class TestConfigureExtraFiles:
    """Drive the interactive loop with mocked questionary prompts."""

    def _run(self, existing, confirm, selects, texts, checkboxes):
        """Run _configure_extra_files with queued prompt responses.

        confirm    -> the single top-level questionary.confirm value
        selects    -> queued questionary.select return values (actions + pickers)
        texts      -> queued questionary.text return values (from, name)
        checkboxes -> queued questionary.checkbox return values (targets)
        """
        command = InitCommand()
        select_iter = iter(selects)
        text_iter = iter(texts)
        checkbox_iter = iter(checkboxes)
        # Record the choices passed to each checkbox call so tests can assert
        # the pre-checked state (the real Add-vs-Edit default bug).
        self.checkbox_choices = []

        def _capture_checkbox(*a, **k):
            self.checkbox_choices.append(k.get("choices", []))
            return _FakeAsk(next(checkbox_iter))

        with (
            patch("questionary.confirm", return_value=_FakeAsk(confirm)),
            patch("questionary.select", side_effect=lambda *a, **k: _FakeAsk(next(select_iter))),
            patch("questionary.text", side_effect=lambda *a, **k: _FakeAsk(next(text_iter))),
            patch("questionary.checkbox", side_effect=_capture_checkbox),
            # Source-exists warning must not depend on the filesystem.
            patch.object(Path, "exists", return_value=True),
        ):
            return command._configure_extra_files(existing)

    def test_decline_keeps_existing(self):
        existing = [{"name": "certs", "targets": "all", "from": "~/c"}]
        result = self._run(existing, confirm=False, selects=[], texts=[], checkboxes=[])
        assert result == existing

    def test_confirm_none_keeps_existing(self):
        existing = [{"name": "certs", "targets": "all", "from": "~/c"}]
        result = self._run(existing, confirm=None, selects=[], texts=[], checkboxes=[])
        assert result == existing

    def test_add_entry(self):
        result = self._run(
            existing=[],
            confirm=True,
            selects=["Add", "Done"],
            texts=["~/ccwb-extras/pre.sh", "pre.sh"],
            checkboxes=[["macos"]],
        )
        assert result == [{"name": "pre.sh", "targets": ["macos"], "from": "~/ccwb-extras/pre.sh"}]

    def test_add_prechecks_nothing(self):
        """Regression: a new Add must start with no target pre-checked, so a
        sticky 'all' default can't silently subsume the admin's selection."""
        self._run(
            existing=[],
            confirm=True,
            selects=["Add", "Done"],
            texts=["~/x/pre.sh", "pre.sh"],
            checkboxes=[["macos"]],
        )
        choices = self.checkbox_choices[0]
        assert all(not c.checked for c in choices), "Add must not pre-check any target"

    def test_edit_prechecks_existing_targets(self):
        """Editing pre-checks exactly the entry's current targets."""
        existing = [{"name": "certs", "targets": ["macos", "linux"], "from": "~/c"}]
        self._run(
            existing=existing,
            confirm=True,
            selects=["Edit", 0, "Done"],
            texts=["~/c", "certs"],
            checkboxes=[["macos", "linux"]],
        )
        checked = {c.value for c in self.checkbox_choices[0] if c.checked}
        assert checked == {"macos", "linux"}

    def test_add_saves_checked_targets_verbatim(self):
        """Regression: selections are saved exactly as checked, with no collapse.

        The earlier bug flattened any selection containing 'all' down to ['all'],
        discarding the specific platforms the admin had also checked.
        """
        result = self._run(
            existing=[],
            confirm=True,
            selects=["Add", "Done"],
            texts=["~/secure/certs", "certs"],
            checkboxes=[["all", "macos", "linux", "windows"]],
        )
        assert result == [{"name": "certs", "targets": ["all", "macos", "linux", "windows"], "from": "~/secure/certs"}]

    def test_add_specific_platforms_only(self):
        """Checking specific platforms (no 'all') saves exactly those."""
        result = self._run(
            existing=[],
            confirm=True,
            selects=["Add", "Done"],
            texts=["~/x/pre.sh", "pre.sh"],
            checkboxes=[["macos", "windows"]],
        )
        assert result == [{"name": "pre.sh", "targets": ["macos", "windows"], "from": "~/x/pre.sh"}]

    def test_invalid_entry_not_saved(self):
        """A zip-slip name is rejected; nothing is added."""
        result = self._run(
            existing=[],
            confirm=True,
            selects=["Add", "Done"],
            texts=["~/x", "../escape"],
            checkboxes=[["all"]],
        )
        assert result == []

    def test_remove_entry(self):
        existing = [
            {"name": "certs", "targets": "all", "from": "~/c"},
            {"name": "pre.sh", "targets": ["macos"], "from": "~/p"},
        ]
        # confirm=True, then select "Remove", picker returns index 0, then "Done".
        result = self._run(
            existing=existing,
            confirm=True,
            selects=["Remove", 0, "Done"],
            texts=[],
            checkboxes=[],
        )
        assert result == [{"name": "pre.sh", "targets": ["macos"], "from": "~/p"}]

    def test_edit_entry(self):
        existing = [{"name": "certs", "targets": "all", "from": "~/c"}]
        # "Edit", picker index 0, new from/name, new targets.
        result = self._run(
            existing=existing,
            confirm=True,
            selects=["Edit", 0, "Done"],
            texts=["~/new/certs", "certs"],
            checkboxes=[["linux", "macos"]],
        )
        assert result == [{"name": "certs", "targets": ["linux", "macos"], "from": "~/new/certs"}]

    def test_add_cancel_source_keeps_list(self):
        """Cancelling the source prompt (None) drops back to the menu."""
        result = self._run(
            existing=[],
            confirm=True,
            selects=["Add", "Done"],
            texts=[None],
            checkboxes=[],
        )
        assert result == []
