# ABOUTME: Tests for inference profiles CLI helper functions
# ABOUTME: Covers _get_profiles_cache_path, _load_profiles_cache, _save_profiles_cache,
# ABOUTME: _get_current_claude_json_model, and _write_claude_json_model

"""Tests for the inference profiles CLI helper functions."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Import the profiles module directly from its file path to avoid triggering
# cli/__init__.py, which pulls in optional CLI-only dependencies (questionary,
# cfn-flip, etc.) that are not required for unit-testing these helpers.
# ---------------------------------------------------------------------------
_SOURCE_ROOT = Path(__file__).parent.parent.parent.parent
_PROFILES_PATH = _SOURCE_ROOT / "claude_code_with_bedrock" / "cli" / "commands" / "profiles.py"

# Ensure the source root is on sys.path so that intra-package imports inside
# profiles.py (e.g. from claude_code_with_bedrock.models import ...) resolve.
sys.path.insert(0, str(_SOURCE_ROOT))

_spec = importlib.util.spec_from_file_location(
    "claude_code_with_bedrock.cli.commands.profiles",
    _PROFILES_PATH,
)
_profiles_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_profiles_mod)

_get_profiles_cache_path = _profiles_mod._get_profiles_cache_path
_load_profiles_cache = _profiles_mod._load_profiles_cache
_save_profiles_cache = _profiles_mod._save_profiles_cache
_get_current_claude_json_model = _profiles_mod._get_current_claude_json_model
_write_claude_json_model = _profiles_mod._write_claude_json_model


# ---------------------------------------------------------------------------
# _get_profiles_cache_path
# ---------------------------------------------------------------------------


class TestGetProfilesCachePath:
    """Tests for _get_profiles_cache_path()."""

    def test_returns_path_object(self):
        """Result must be a pathlib.Path instance."""
        result = _get_profiles_cache_path("default")
        assert isinstance(result, Path)

    def test_profile_name_is_embedded_in_filename(self):
        """The profile name must appear in the file name."""
        result = _get_profiles_cache_path("my-profile")
        assert "my-profile" in result.name

    def test_filename_ends_with_json(self):
        """Cache file must have a .json extension."""
        result = _get_profiles_cache_path("default")
        assert result.suffix == ".json"

    def test_path_is_inside_claude_code_session_dir(self):
        """Cache path must be inside the .claude-code-session directory."""
        # _get_profiles_cache_path returns Path.home() / ".claude-code-session" / <file>
        # Check by inspecting the parent directory name directly — no mock needed.
        result = _get_profiles_cache_path("default")
        assert result.parent.name == ".claude-code-session"

    def test_different_profile_names_produce_different_paths(self):
        """Two distinct profile names must resolve to different file paths."""
        path_a = _get_profiles_cache_path("profile-a")
        path_b = _get_profiles_cache_path("profile-b")
        assert path_a != path_b


# ---------------------------------------------------------------------------
# _load_profiles_cache
# ---------------------------------------------------------------------------


class TestLoadProfilesCache:
    """Tests for _load_profiles_cache()."""

    def test_returns_empty_dict_when_file_does_not_exist(self, tmp_path, monkeypatch):
        """Missing cache file must yield an empty dict."""
        # Arrange — point home to tmp_path so no real ~/.claude-code-session is read
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Act
        result = _load_profiles_cache("no-such-profile")

        # Assert
        assert result == {}

    def test_returns_dict_from_valid_json_file(self, tmp_path, monkeypatch):
        """A well-formed JSON cache file must be loaded and returned as-is."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cache_dir = tmp_path / ".claude-code-session"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "test-profile-inference-profiles.json"
        expected = {"sonnet-4-6": "arn:aws:bedrock:us-east-1:123456789012:inference-profile/abc123"}
        cache_file.write_text(json.dumps(expected))

        # Act
        result = _load_profiles_cache("test-profile")

        # Assert
        assert result == expected

    def test_returns_empty_dict_when_file_is_corrupted(self, tmp_path, monkeypatch):
        """A file containing invalid JSON must not raise; return {} instead."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cache_dir = tmp_path / ".claude-code-session"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "bad-profile-inference-profiles.json"
        cache_file.write_text("this is not json {{{")

        # Act
        result = _load_profiles_cache("bad-profile")

        # Assert
        assert result == {}

    def test_returns_dict_preserving_multiple_model_keys(self, tmp_path, monkeypatch):
        """All model-key→ARN pairs in the cache file must be returned."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cache_dir = tmp_path / ".claude-code-session"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "multi-inference-profiles.json"
        expected = {
            "sonnet-4-6": "arn:aws:bedrock:us-east-1:123:inference-profile/s46",
            "opus-4-6":   "arn:aws:bedrock:us-east-1:123:inference-profile/o46",
            "haiku-4-5":  "arn:aws:bedrock:us-east-1:123:inference-profile/h45",
        }
        cache_file.write_text(json.dumps(expected))

        # Act
        result = _load_profiles_cache("multi")

        # Assert
        assert result == expected

    def test_returns_empty_dict_for_empty_json_object(self, tmp_path, monkeypatch):
        """An empty JSON object ({}) in the cache file must return an empty dict."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cache_dir = tmp_path / ".claude-code-session"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "empty-profile-inference-profiles.json"
        cache_file.write_text("{}")

        # Act
        result = _load_profiles_cache("empty-profile")

        # Assert
        assert result == {}


# ---------------------------------------------------------------------------
# _save_profiles_cache
# ---------------------------------------------------------------------------


class TestSaveProfilesCache:
    """Tests for _save_profiles_cache()."""

    def test_writes_valid_json_to_expected_path(self, tmp_path, monkeypatch):
        """The function must serialise the dict to the correct file as JSON."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        arns = {"sonnet-4-6": "arn:aws:bedrock:us-east-1:999:inference-profile/x"}

        # Act
        _save_profiles_cache("save-test", arns)

        # Assert
        cache_file = tmp_path / ".claude-code-session" / "save-test-inference-profiles.json"
        assert cache_file.exists()
        loaded = json.loads(cache_file.read_text())
        assert loaded == arns

    def test_creates_parent_directory_if_missing(self, tmp_path, monkeypatch):
        """The .claude-code-session directory must be created automatically."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        expected_dir = tmp_path / ".claude-code-session"
        assert not expected_dir.exists()

        # Act
        _save_profiles_cache("new-profile", {"haiku-4-5": "arn:..."})

        # Assert
        assert expected_dir.is_dir()

    def test_overwrites_existing_cache(self, tmp_path, monkeypatch):
        """Calling save twice must overwrite the previous cache content."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cache_dir = tmp_path / ".claude-code-session"
        cache_dir.mkdir(parents=True)

        _save_profiles_cache("overwrite-test", {"old-key": "old-arn"})

        new_arns = {"new-key": "new-arn"}

        # Act
        _save_profiles_cache("overwrite-test", new_arns)

        # Assert
        cache_file = cache_dir / "overwrite-test-inference-profiles.json"
        loaded = json.loads(cache_file.read_text())
        assert loaded == new_arns

    def test_round_trip_save_then_load(self, tmp_path, monkeypatch):
        """Data saved by _save_profiles_cache must be recoverable by _load_profiles_cache."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        arns = {
            "sonnet-4-6": "arn:aws:bedrock:eu-west-1:123:inference-profile/s",
            "haiku-4-5":  "arn:aws:bedrock:eu-west-1:123:inference-profile/h",
        }

        # Act
        _save_profiles_cache("round-trip", arns)
        result = _load_profiles_cache("round-trip")

        # Assert
        assert result == arns

    def test_saved_file_is_valid_json(self, tmp_path, monkeypatch):
        """The written file must be parseable JSON (not, e.g., repr output)."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Act
        _save_profiles_cache("json-check", {"k": "v"})

        # Assert
        cache_file = tmp_path / ".claude-code-session" / "json-check-inference-profiles.json"
        try:
            json.loads(cache_file.read_text())
        except json.JSONDecodeError as exc:
            pytest.fail(f"Cache file is not valid JSON: {exc}")


# ---------------------------------------------------------------------------
# _get_current_claude_json_model
# ---------------------------------------------------------------------------


class TestGetCurrentClaudeJsonModel:
    """Tests for _get_current_claude_json_model()."""

    def test_returns_none_when_file_does_not_exist(self, tmp_path, monkeypatch):
        """Missing ~/.claude.json must cause the function to return None."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Act
        result = _get_current_claude_json_model()

        # Assert
        assert result is None

    def test_returns_model_field_from_file(self, tmp_path, monkeypatch):
        """The value of the 'model' key must be returned when present."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        arn = "arn:aws:bedrock:us-east-1:123456789012:inference-profile/test"
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(json.dumps({"model": arn, "other_field": "preserved"}))

        # Act
        result = _get_current_claude_json_model()

        # Assert
        assert result == arn

    def test_returns_none_when_model_key_absent(self, tmp_path, monkeypatch):
        """When the JSON file exists but has no 'model' key, return None."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(json.dumps({"some_other_key": "value"}))

        # Act
        result = _get_current_claude_json_model()

        # Assert
        assert result is None

    def test_returns_none_when_file_is_corrupted(self, tmp_path, monkeypatch):
        """Corrupted JSON must not raise; return None instead."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text("not valid json <<<")

        # Act
        result = _get_current_claude_json_model()

        # Assert
        assert result is None

    def test_returns_none_for_empty_json_object(self, tmp_path, monkeypatch):
        """An empty JSON object must yield None (no model key present)."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".claude.json").write_text("{}")

        # Act
        result = _get_current_claude_json_model()

        # Assert
        assert result is None

    def test_returns_string_value(self, tmp_path, monkeypatch):
        """The returned model value must be a string."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        (tmp_path / ".claude.json").write_text(json.dumps({"model": "some-arn"}))

        # Act
        result = _get_current_claude_json_model()

        # Assert
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _write_claude_json_model
# ---------------------------------------------------------------------------


class TestWriteClaudeJsonModel:
    """Tests for _write_claude_json_model()."""

    def test_creates_file_if_it_does_not_exist(self, tmp_path, monkeypatch):
        """When ~/.claude.json is absent it must be created with the model field."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        arn = "arn:aws:bedrock:us-east-1:123456789012:inference-profile/new"

        # Act
        _write_claude_json_model(arn)

        # Assert
        claude_json = tmp_path / ".claude.json"
        assert claude_json.exists()
        data = json.loads(claude_json.read_text())
        assert data["model"] == arn

    def test_updates_model_field_preserving_other_fields(self, tmp_path, monkeypatch):
        """Existing fields other than 'model' must be left intact after a write."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        claude_json = tmp_path / ".claude.json"
        initial = {"model": "old-arn", "theme": "dark", "apiKey": "secret"}
        claude_json.write_text(json.dumps(initial))
        new_arn = "arn:aws:bedrock:eu-west-1:999:inference-profile/updated"

        # Act
        _write_claude_json_model(new_arn)

        # Assert
        data = json.loads(claude_json.read_text())
        assert data["model"] == new_arn
        assert data["theme"] == "dark"
        assert data["apiKey"] == "secret"

    def test_overwrites_existing_model_field(self, tmp_path, monkeypatch):
        """An existing 'model' value must be replaced, not duplicated."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(json.dumps({"model": "first-arn"}))
        second_arn = "arn:aws:bedrock:us-east-1:123:inference-profile/second"

        # Act
        _write_claude_json_model(second_arn)

        # Assert
        data = json.loads(claude_json.read_text())
        assert data["model"] == second_arn
        # 'model' must appear exactly once
        text = claude_json.read_text()
        assert text.count('"model"') == 1

    def test_written_file_is_valid_json(self, tmp_path, monkeypatch):
        """The file written by the function must be parseable as JSON."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        # Act
        _write_claude_json_model("arn:aws:bedrock:us-east-1:1:inference-profile/x")

        # Assert
        text = (tmp_path / ".claude.json").read_text()
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            pytest.fail(f"Written file is not valid JSON: {exc}")

    def test_gracefully_handles_corrupted_existing_file(self, tmp_path, monkeypatch):
        """When ~/.claude.json is corrupted, write must succeed with just the new model."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text("this is not json {{{{")
        arn = "arn:aws:bedrock:us-east-1:123:inference-profile/recover"

        # Act — must not raise
        _write_claude_json_model(arn)

        # Assert
        data = json.loads(claude_json.read_text())
        assert data["model"] == arn

    def test_round_trip_write_then_read(self, tmp_path, monkeypatch):
        """A value written by _write_claude_json_model must be readable by _get_current_claude_json_model."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        arn = "arn:aws:bedrock:ap-northeast-1:42:inference-profile/rt"

        # Act
        _write_claude_json_model(arn)
        result = _get_current_claude_json_model()

        # Assert
        assert result == arn

    def test_multiple_writes_only_last_value_persists(self, tmp_path, monkeypatch):
        """Calling the function three times must leave only the final ARN in the file."""
        # Arrange
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        arns = [
            "arn:aws:bedrock:us-east-1:1:inference-profile/first",
            "arn:aws:bedrock:us-east-1:1:inference-profile/second",
            "arn:aws:bedrock:us-east-1:1:inference-profile/third",
        ]

        # Act
        for arn in arns:
            _write_claude_json_model(arn)

        # Assert
        result = _get_current_claude_json_model()
        assert result == arns[-1]
