# ABOUTME: Unit tests for distribute.py — archive creation, platform detection, checksums
# ABOUTME: Covers DistributeCommand pure logic methods (no AWS calls)

"""Tests for claude_code_with_bedrock.cli.commands.distribute module."""

import hashlib
import zipfile
from unittest.mock import MagicMock

import pytest

from claude_code_with_bedrock.cli.commands.distribute import DistributeCommand, S3UploadProgress


@pytest.fixture
def cmd():
    """Create a DistributeCommand instance without invoking CLI machinery."""
    c = DistributeCommand.__new__(DistributeCommand)
    return c


@pytest.fixture
def package_dir(tmp_path):
    """Create a realistic package directory structure."""
    pkg = tmp_path / "dist" / "my-profile" / "2026-06-01-120000"
    pkg.mkdir(parents=True)
    # Create config
    (pkg / "config.json").write_text('{"profile": "my-profile"}')
    (pkg / "install.sh").write_text("#!/bin/bash\necho install")
    (pkg / "install.bat").write_text("@echo off\necho install")
    (pkg / "README.md").write_text("# README")
    # Create platform binaries (tiny stubs)
    for platform in [
        "credential-process-macos-arm64",
        "credential-process-macos-intel",
        "credential-process-linux-x64",
        "credential-process-linux-arm64",
        "credential-process-windows.exe",
        "otel-helper-macos-arm64",
        "otel-helper-macos-intel",
        "otel-helper-linux-x64",
        "otel-helper-linux-arm64",
        "otel-helper-windows.exe",
    ]:
        (pkg / platform).write_bytes(b"\x00" * 100)
    # Windows otel-helper launcher + AV-resilient fallback (required by install.bat)
    (pkg / "otel-helper.ps1").write_text("# otel-helper.ps1")
    (pkg / "otel-helper.cmd").write_text("@echo off\nREM otel-helper.cmd")
    return pkg


class TestS3UploadProgress:
    """Tests for S3UploadProgress callback."""

    def test_progress_tracks_bytes(self):
        progress_bar = MagicMock()
        tracker = S3UploadProgress("test.zip", 1000, progress_bar)
        tracker.set_task_id("task-1")

        tracker(250)
        progress_bar.update.assert_called_with("task-1", completed=250)

        tracker(250)
        progress_bar.update.assert_called_with("task-1", completed=500)

    def test_no_task_id_does_not_crash(self):
        progress_bar = MagicMock()
        tracker = S3UploadProgress("test.zip", 1000, progress_bar)
        # No set_task_id called
        tracker(100)  # Should not raise
        progress_bar.update.assert_not_called()


class TestCheckOldFlatStructure:
    """Tests for _check_old_flat_structure."""

    def test_old_structure_detected(self, cmd, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "credential-process-macos-arm64").write_bytes(b"\x00")
        assert cmd._check_old_flat_structure(dist) is True

    def test_new_structure_not_detected(self, cmd, tmp_path):
        dist = tmp_path / "dist"
        dist.mkdir()
        # New structure has profile/timestamp subdirs, no flat files
        (dist / "my-profile" / "2026-01-01-000000").mkdir(parents=True)
        assert cmd._check_old_flat_structure(dist) is False

    def test_nonexistent_dir(self, cmd, tmp_path):
        dist = tmp_path / "nonexistent"
        assert cmd._check_old_flat_structure(dist) is False


class TestScanDistributions:
    """Tests for _scan_distributions."""

    def test_scans_profile_timestamp_structure(self, cmd, package_dir):
        dist = package_dir.parent.parent
        builds = cmd._scan_distributions(dist)

        assert "my-profile" in builds
        assert len(builds["my-profile"]) == 1
        assert builds["my-profile"][0]["timestamp"] == "2026-06-01-120000"
        assert builds["my-profile"][0]["path"] == package_dir

    def test_detects_platforms(self, cmd, package_dir):
        dist = package_dir.parent.parent
        builds = cmd._scan_distributions(dist)

        platforms = builds["my-profile"][0]["platforms"]
        assert "macos-arm64" in platforms
        assert "windows" in platforms
        assert "linux-x64" in platforms

    def test_calculates_size(self, cmd, package_dir):
        dist = package_dir.parent.parent
        builds = cmd._scan_distributions(dist)

        assert builds["my-profile"][0]["size"] > 0

    def test_empty_dir(self, cmd, tmp_path):
        dist = tmp_path / "empty"
        dist.mkdir()
        builds = cmd._scan_distributions(dist)
        assert builds == {}

    def test_nonexistent_dir(self, cmd, tmp_path):
        builds = cmd._scan_distributions(tmp_path / "ghost")
        assert builds == {}

    def test_skips_non_package_dirs(self, cmd, tmp_path):
        """Dirs without config.json or install scripts are skipped."""
        dist = tmp_path / "dist"
        profile = dist / "my-profile" / "2026-01-01-000000"
        profile.mkdir(parents=True)
        (profile / "random.txt").write_text("not a package")

        builds = cmd._scan_distributions(dist)
        assert builds["my-profile"] == []


class TestDetectPlatforms:
    """Tests for _detect_platforms."""

    def test_all_platforms(self, cmd, package_dir):
        platforms = cmd._detect_platforms(package_dir)
        assert set(platforms) == {"macos-arm64", "macos-intel", "linux-x64", "linux-arm64", "windows"}

    def test_windows_only(self, cmd, tmp_path):
        build = tmp_path / "build"
        build.mkdir()
        (build / "credential-process-windows.exe").write_bytes(b"\x00")
        platforms = cmd._detect_platforms(build)
        assert platforms == ["windows"]

    def test_empty_dir(self, cmd, tmp_path):
        build = tmp_path / "empty"
        build.mkdir()
        assert cmd._detect_platforms(build) == []


class TestFormatSize:
    """Tests for _format_size."""

    def test_bytes(self, cmd):
        assert "B" in cmd._format_size(500)

    def test_kilobytes(self, cmd):
        assert "KB" in cmd._format_size(1500)

    def test_megabytes(self, cmd):
        assert "MB" in cmd._format_size(1500000)

    def test_gigabytes(self, cmd):
        assert "GB" in cmd._format_size(1500000000)


class TestCreateArchive:
    """Tests for _create_archive."""

    def test_creates_zip(self, cmd, package_dir):
        archive = cmd._create_archive(package_dir)
        assert archive.exists()
        assert archive.name == "claude-code-package.zip"

    def test_zip_contains_expected_files(self, cmd, package_dir):
        archive = cmd._create_archive(package_dir)
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert "claude-code-package/config.json" in names
            assert "claude-code-package/install.sh" in names
            assert "claude-code-package/credential-process-macos-arm64" in names

    def test_zip_contains_windows_otel_helper_scripts(self, cmd, package_dir):
        """otel-helper.cmd/.ps1 are required by install.bat and must ship in the zip."""
        archive = cmd._create_archive(package_dir)
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert "claude-code-package/otel-helper.ps1" in names
            assert "claude-code-package/otel-helper.cmd" in names

    def test_zip_includes_settings_dir(self, cmd, package_dir):
        settings = package_dir / "claude-settings"
        settings.mkdir()
        (settings / "settings.json").write_text('{"key": "val"}')

        archive = cmd._create_archive(package_dir)
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert "claude-code-package/claude-settings/settings.json" in names

    def test_skips_missing_files(self, cmd, tmp_path):
        """Only config.json present — zip still creates fine."""
        pkg = tmp_path / "sparse"
        pkg.mkdir()
        (pkg / "config.json").write_text("{}")

        archive = cmd._create_archive(pkg)
        assert archive.exists()
        with zipfile.ZipFile(archive, "r") as zf:
            names = zf.namelist()
            assert "claude-code-package/config.json" in names
            assert len(names) == 1


class TestCreatePerOsArchives:
    """Tests for _create_per_os_archives."""

    def test_creates_separate_archives(self, cmd, package_dir):
        archives = cmd._create_per_os_archives(package_dir)
        # Should have 5 platform archives (all binaries present)
        assert len(archives) == 5
        labels = [label for _, label, _ in archives]
        assert "Windows" in labels
        assert "macOS ARM64" in labels
        assert "Linux x64" in labels

    def test_each_archive_contains_platform_binary(self, cmd, package_dir):
        archives = cmd._create_per_os_archives(package_dir)
        for _platform, _label, archive_path in archives:
            with zipfile.ZipFile(archive_path, "r") as zf:
                names = zf.namelist()
                # Should have config.json in every platform archive
                assert "claude-code-package/config.json" in names

    def test_windows_archive_has_bat_and_ps1(self, cmd, package_dir):
        (package_dir / "ccwb-install.ps1").write_text("# ps1")
        archives = cmd._create_per_os_archives(package_dir)
        win_archives = [(p, l, a) for p, l, a in archives if p == "windows"]
        assert len(win_archives) == 1
        _, _, win_path = win_archives[0]
        with zipfile.ZipFile(win_path, "r") as zf:
            names = zf.namelist()
            assert "claude-code-package/install.bat" in names
            assert "claude-code-package/ccwb-install.ps1" in names
            # AV-resilient otel-helper launcher + fallback (required by install.bat)
            assert "claude-code-package/otel-helper.ps1" in names
            assert "claude-code-package/otel-helper.cmd" in names

    def test_skips_platform_without_binary(self, cmd, tmp_path):
        """Only Linux x64 binary present → only 1 archive."""
        pkg = tmp_path / "linux-only"
        pkg.mkdir()
        (pkg / "config.json").write_text("{}")
        (pkg / "credential-process-linux-x64").write_bytes(b"\x00")

        archives = cmd._create_per_os_archives(pkg)
        assert len(archives) == 1
        assert archives[0][0] == "linux-x64"


class TestCalculateChecksum:
    """Tests for _calculate_checksum."""

    def test_produces_sha256(self, cmd, tmp_path):
        f = tmp_path / "test.bin"
        content = b"hello world"
        f.write_bytes(content)

        result = cmd._calculate_checksum(f)
        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_empty_file(self, cmd, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")

        result = cmd._calculate_checksum(f)
        expected = hashlib.sha256(b"").hexdigest()
        assert result == expected


class TestGenerateRestrictedUrl:
    """Tests for _generate_restricted_url."""

    def test_generates_presigned_url(self, cmd):
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://bucket.s3.amazonaws.com/key?sig=abc"

        url = cmd._generate_restricted_url(mock_s3, "my-bucket", "packages/x.zip", "10.0.0.1,10.0.0.2", 48)
        assert "https://" in url
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "packages/x.zip"},
            ExpiresIn=48 * 3600,
        )

    def test_custom_expiry(self, cmd):
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://url"

        cmd._generate_restricted_url(mock_s3, "b", "k", "1.1.1.1", 24)
        call_args = mock_s3.generate_presigned_url.call_args
        assert (
            call_args[1]["ExpiresIn"] == 24 * 3600
            if "ExpiresIn" in call_args[1]
            else call_args[0][1]["ExpiresIn"] == 24 * 3600
        )
