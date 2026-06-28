"""
E2E Tests — Binary Platform Compatibility

Verifies platform-specific binary behavior for Windows and macOS,
including AV compatibility, keyring integration, and path handling.
"""

import os
import platform
import shutil
import subprocess
import tempfile

import pytest

pytestmark = [pytest.mark.e2e]


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_macos() -> bool:
    return platform.system() == "Darwin"


class TestBinaryPlatform:
    """Platform-specific binary tests — only for Windows/macOS profiles."""

    def test_binary_executes_without_av_block(self, credential_process_binary):
        """Binary starts and returns version without being blocked by AV."""
        result = subprocess.run(
            [str(credential_process_binary), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"Binary failed to execute (possible AV block)\n"
            f"exit: {result.returncode}\n"
            f"stderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )

        # Should output some version string
        output = result.stdout + result.stderr
        assert output.strip(), "No version output produced"

    @pytest.mark.skipif(not _is_windows(), reason="Windows-only test")
    def test_cmd_fallback_when_exe_missing(self, credential_process_binary):
        """On Windows, .cmd wrapper works when .exe is temporarily renamed."""
        exe_path = str(credential_process_binary)
        if not exe_path.endswith(".exe"):
            pytest.skip("Not an .exe binary")

        cmd_path = exe_path.replace(".exe", ".cmd")
        if not os.path.exists(cmd_path):
            pytest.skip(".cmd wrapper not found")

        # Temporarily rename the .exe
        backup_path = exe_path + ".bak"
        try:
            os.rename(exe_path, backup_path)

            result = subprocess.run(
                [cmd_path, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                shell=True,
            )

            assert result.returncode == 0, (
                f".cmd fallback failed: {result.stderr}"
            )
        finally:
            # Restore the .exe
            if os.path.exists(backup_path):
                os.rename(backup_path, exe_path)

    def test_keyring_store_and_retrieve(self, credential_process_binary, e2e_profile):
        """Token can be stored in and retrieved from the keyring."""
        platform_name = e2e_profile["platform"]
        if "linux" in platform_name:
            pytest.skip("Keyring tests for Windows/macOS only")

        test_token = f"e2e-test-token-{os.getpid()}"

        # Store token
        store_result = subprocess.run(
            [str(credential_process_binary), "--keyring-store", "--token", test_token],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if store_result.returncode != 0 and "keyring" in store_result.stderr.lower():
            pytest.skip(f"Keyring not available: {store_result.stderr}")

        assert store_result.returncode == 0, (
            f"Keyring store failed: {store_result.stderr}"
        )

        # Retrieve token
        retrieve_result = subprocess.run(
            [str(credential_process_binary), "--keyring-retrieve"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        assert retrieve_result.returncode == 0, (
            f"Keyring retrieve failed: {retrieve_result.stderr}"
        )
        assert test_token in retrieve_result.stdout, (
            f"Retrieved token doesn't match stored token"
        )

    def test_keyring_chunking_large_token(self, credential_process_binary, e2e_profile):
        """Large token (2400+ chars) roundtrips correctly via keyring chunking."""
        platform_name = e2e_profile["platform"]
        if "linux" in platform_name:
            pytest.skip("Keyring tests for Windows/macOS only")

        # Generate a large token (2500 chars)
        large_token = "e2e-large-" + "A" * 2490

        # Store large token
        store_result = subprocess.run(
            [str(credential_process_binary), "--keyring-store", "--token", large_token],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if store_result.returncode != 0 and "keyring" in store_result.stderr.lower():
            pytest.skip(f"Keyring not available: {store_result.stderr}")

        assert store_result.returncode == 0, (
            f"Keyring store (large) failed: {store_result.stderr}"
        )

        # Retrieve and verify
        retrieve_result = subprocess.run(
            [str(credential_process_binary), "--keyring-retrieve"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        assert retrieve_result.returncode == 0, (
            f"Keyring retrieve (large) failed: {retrieve_result.stderr}"
        )
        assert large_token in retrieve_result.stdout, (
            f"Large token not preserved after chunked keyring roundtrip. "
            f"Expected 2500 chars, got {len(retrieve_result.stdout.strip())} chars"
        )

    def test_paths_handle_spaces(self, credential_process_binary, e2e_profile):
        """Binary works when installed in a path with spaces."""
        # Create temp dir with spaces in name
        space_dir = tempfile.mkdtemp(prefix="E2E Program Files ")

        try:
            binary_name = os.path.basename(str(credential_process_binary))
            space_binary = os.path.join(space_dir, binary_name)

            # Copy binary to spaced path
            shutil.copy2(str(credential_process_binary), space_binary)

            if not _is_windows():
                os.chmod(space_binary, 0o755)

            # Execute from spaced path
            result = subprocess.run(
                [space_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, (
                f"Binary in spaced path failed (exit {result.returncode}): {result.stderr}"
            )
        finally:
            shutil.rmtree(space_dir, ignore_errors=True)
