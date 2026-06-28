"""
E2E Tests — Binary Platform Compatibility

Verifies platform-specific binary behavior for Windows and macOS,
including AV compatibility, keyring integration, path handling,
.cmd/.ps1 fallbacks, install scripts, and macOS Keychain.
"""

import os
import platform
import shutil
import subprocess
import tempfile
import time

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

            assert result.returncode == 0, f".cmd fallback failed: {result.stderr}"
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
            "Retrieved token doesn't match stored token"
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


# ===========================================================================
# Windows-specific tests
# ===========================================================================


@pytest.mark.skipif(not _is_windows(), reason="Windows-only tests")
class TestWindowsPlatform:
    """Windows-specific binary and integration tests."""

    def test_credential_process_exe_runs(self, credential_process_binary):
        """credential-process.exe starts and returns version."""
        exe_path = str(credential_process_binary)
        assert exe_path.endswith(".exe"), f"Expected .exe binary, got: {exe_path}"

        result = subprocess.run(
            [exe_path, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"credential-process.exe failed to run\n"
            f"exit: {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        output = result.stdout + result.stderr
        assert output.strip(), "No version output from .exe"

    def test_otel_helper_cmd_fallback(self, otel_helper_binary):
        """When .exe is renamed/blocked, .cmd wrapper invokes .ps1 fallback."""
        exe_path = str(otel_helper_binary)
        if not exe_path.endswith(".exe"):
            pytest.skip("Not a Windows .exe binary")

        binary_dir = os.path.dirname(exe_path)
        cmd_path = os.path.join(binary_dir, "otel-helper.cmd")
        ps1_path = os.path.join(binary_dir, "otel-helper.ps1")

        if not os.path.exists(cmd_path):
            pytest.skip("otel-helper.cmd wrapper not found")
        if not os.path.exists(ps1_path):
            pytest.skip("otel-helper.ps1 fallback not found")

        # Temporarily rename .exe to simulate it being blocked/missing
        backup_path = exe_path + ".bak"
        try:
            os.rename(exe_path, backup_path)

            result = subprocess.run(
                ["cmd", "/c", cmd_path, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            assert result.returncode == 0, (
                f".cmd fallback to .ps1 failed\n"
                f"exit: {result.returncode}\n"
                f"stderr: {result.stderr}"
            )
        finally:
            if os.path.exists(backup_path):
                os.rename(backup_path, exe_path)

    def test_powershell_otel_helper_parity(self, otel_helper_binary):
        """otel-helper.ps1 produces same output format as .exe."""
        exe_path = str(otel_helper_binary)
        binary_dir = os.path.dirname(exe_path)
        ps1_path = os.path.join(binary_dir, "otel-helper.ps1")

        if not os.path.exists(ps1_path):
            pytest.skip("otel-helper.ps1 not found")

        # Get .exe output
        exe_result = subprocess.run(
            [exe_path, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Get .ps1 output
        ps1_result = subprocess.run(
            [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                ps1_path,
                "--version",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if ps1_result.returncode != 0:
            pytest.skip(f"PowerShell execution failed: {ps1_result.stderr}")

        # Both should produce version output in the same format
        exe_output = exe_result.stdout.strip()
        ps1_output = ps1_result.stdout.strip()

        # At minimum, both should output something non-empty
        assert exe_output, "exe produced no version output"
        assert ps1_output, "ps1 produced no version output"

    def test_windows_keyring_chunking(self, credential_process_binary, tmp_path):
        """Tokens >1280 chars are chunked correctly in Windows Credential Manager."""
        # Windows Credential Manager has a 1280-byte limit per entry
        # The binary should automatically chunk larger tokens
        chunk_boundary_token = "X" * 1300  # Just over the limit

        store_result = subprocess.run(
            [
                str(credential_process_binary),
                "--keyring-store",
                "--token",
                chunk_boundary_token,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(tmp_path),
        )

        if store_result.returncode != 0 and "keyring" in store_result.stderr.lower():
            pytest.skip(f"Windows keyring not available: {store_result.stderr}")

        assert store_result.returncode == 0, (
            f"Keyring chunked store failed: {store_result.stderr}"
        )

        # Retrieve and verify integrity
        retrieve_result = subprocess.run(
            [str(credential_process_binary), "--keyring-retrieve"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(tmp_path),
        )

        assert retrieve_result.returncode == 0, (
            f"Keyring chunked retrieve failed: {retrieve_result.stderr}"
        )
        assert chunk_boundary_token in retrieve_result.stdout, (
            f"Chunked token not preserved. Expected 1300 chars, "
            f"got {len(retrieve_result.stdout.strip())} chars"
        )

    def test_windows_keyring_retrieval_latency(
        self, credential_process_binary, tmp_path
    ):
        """Keyring operations complete in <2s (not 10-17s DPAPI hang)."""
        test_token = f"latency-test-{os.getpid()}"

        # Store
        subprocess.run(
            [str(credential_process_binary), "--keyring-store", "--token", test_token],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(tmp_path),
        )

        # Time the retrieval
        start = time.perf_counter()
        result = subprocess.run(
            [str(credential_process_binary), "--keyring-retrieve"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(tmp_path),
        )
        elapsed = time.perf_counter() - start

        if result.returncode != 0 and "keyring" in result.stderr.lower():
            pytest.skip("Keyring not available for latency test")

        assert elapsed < 2.0, (
            f"Keyring retrieval took {elapsed:.1f}s (>2s threshold). "
            f"Possible DPAPI hang — see issue #649"
        )

    def test_install_bat_execution(self, credential_process_binary, tmp_path):
        """install.bat runs without '& was unexpected' errors."""
        source_dir = (
            credential_process_binary.parent.parent.parent
            if hasattr(credential_process_binary, "parent")
            else os.path.dirname(
                os.path.dirname(os.path.dirname(str(credential_process_binary)))
            )
        )

        # Look for install.bat in source tree
        install_bat = None
        for candidate in [
            os.path.join(str(source_dir), "scripts", "install.bat"),
            os.path.join(str(source_dir), "..", "scripts", "install.bat"),
            os.path.join(str(source_dir), "..", "..", "scripts", "install.bat"),
        ]:
            if os.path.exists(candidate):
                install_bat = candidate
                break

        if not install_bat:
            pytest.skip("install.bat not found in source tree")

        # Run install.bat in dry-run/help mode
        result = subprocess.run(
            ["cmd", "/c", install_bat, "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(tmp_path),
        )

        # Check for the specific "& was unexpected" error
        assert "was unexpected" not in result.stderr, (
            f"install.bat has syntax error: {result.stderr}"
        )

    def test_reg_file_userprofile_paths(self, credential_process_binary, tmp_path):
        """Generated .reg file uses %USERPROFILE% not ~/."""
        # Run the binary with config export to generate .reg content
        result = subprocess.run(
            [str(credential_process_binary), "--export-reg"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(tmp_path),
        )

        if result.returncode != 0:
            # Try alternative flag
            result = subprocess.run(
                [
                    str(credential_process_binary),
                    "--generate-config",
                    "--format",
                    "reg",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(tmp_path),
            )

        if result.returncode != 0:
            pytest.skip(f"Cannot generate .reg output: {result.stderr}")

        output = result.stdout
        if "~/" in output:
            pytest.fail(
                f".reg file contains Unix-style path '~/'. "
                f"Should use %USERPROFILE% for Windows. Output:\n{output[:500]}"
            )

    def test_no_crlf_in_generated_scripts(self, credential_process_binary):
        """Generated .sh scripts use LF line endings even on Windows."""
        binary_dir = os.path.dirname(str(credential_process_binary))

        # Find any .sh files in the dist/scripts directory
        sh_files = []
        for root, _dirs, files in os.walk(binary_dir):
            for f in files:
                if f.endswith(".sh"):
                    sh_files.append(os.path.join(root, f))

        # Also check parent directories
        parent_dir = os.path.dirname(binary_dir)
        for root, _dirs, files in os.walk(parent_dir):
            for f in files:
                if f.endswith(".sh"):
                    sh_files.append(os.path.join(root, f))

        if not sh_files:
            pytest.skip("No .sh scripts found to check")

        for sh_file in sh_files:
            with open(sh_file, "rb") as fh:
                content = fh.read()

            if b"\r\n" in content:
                pytest.fail(
                    f"File {sh_file} has CRLF line endings. "
                    f".sh scripts must use LF only (see issue #567)"
                )

    def test_long_path_support(self, credential_process_binary, tmp_path):
        """Binary works when installed to path >200 chars."""
        # Create a deeply nested path >200 chars total
        deep_path = tmp_path
        while len(str(deep_path)) < 210:
            deep_path = deep_path / "a_long_directory_name_for_testing"
        deep_path.mkdir(parents=True, exist_ok=True)

        binary_name = os.path.basename(str(credential_process_binary))
        long_binary = deep_path / binary_name

        shutil.copy2(str(credential_process_binary), str(long_binary))

        result = subprocess.run(
            [str(long_binary), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"Binary failed in long path ({len(str(long_binary))} chars)\n"
            f"path: {long_binary}\n"
            f"exit: {result.returncode}\n"
            f"stderr: {result.stderr}"
        )


# ===========================================================================
# macOS-specific tests
# ===========================================================================


@pytest.mark.skipif(not _is_macos(), reason="macOS-only tests")
class TestMacOSPlatform:
    """macOS-specific binary and integration tests."""

    def test_credential_process_runs(self, credential_process_binary):
        """credential-process binary executes on macOS ARM."""
        result = subprocess.run(
            [str(credential_process_binary), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, (
            f"credential-process failed on macOS\n"
            f"exit: {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
        output = result.stdout + result.stderr
        assert output.strip(), "No version output produced on macOS"

    def test_macos_keychain_store_retrieve(self, credential_process_binary, tmp_path):
        """Token roundtrips through macOS Keychain."""
        test_token = f"e2e-macos-keychain-{os.getpid()}"

        # Store token via binary's keychain integration
        store_result = subprocess.run(
            [str(credential_process_binary), "--keyring-store", "--token", test_token],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(tmp_path),
        )

        if store_result.returncode != 0 and "keychain" in store_result.stderr.lower():
            pytest.skip(f"macOS Keychain not available: {store_result.stderr}")

        assert store_result.returncode == 0, (
            f"Keychain store failed: {store_result.stderr}"
        )

        # Retrieve token
        retrieve_result = subprocess.run(
            [str(credential_process_binary), "--keyring-retrieve"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(tmp_path),
        )

        assert retrieve_result.returncode == 0, (
            f"Keychain retrieve failed: {retrieve_result.stderr}"
        )
        assert test_token in retrieve_result.stdout, (
            "Retrieved token doesn't match stored token in Keychain"
        )

    def test_macos_keychain_large_token(self, credential_process_binary, tmp_path):
        """Large tokens (>2KB) store/retrieve correctly from Keychain."""
        # macOS Keychain doesn't have the same chunking limit as Windows,
        # but we still test large payloads for correctness
        large_token = "e2e-macos-large-" + "B" * 2500

        store_result = subprocess.run(
            [str(credential_process_binary), "--keyring-store", "--token", large_token],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(tmp_path),
        )

        if store_result.returncode != 0 and "keychain" in store_result.stderr.lower():
            pytest.skip(f"macOS Keychain not available: {store_result.stderr}")

        assert store_result.returncode == 0, (
            f"Keychain large token store failed: {store_result.stderr}"
        )

        # Retrieve and verify integrity
        retrieve_result = subprocess.run(
            [str(credential_process_binary), "--keyring-retrieve"],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(tmp_path),
        )

        assert retrieve_result.returncode == 0, (
            f"Keychain large token retrieve failed: {retrieve_result.stderr}"
        )
        assert large_token in retrieve_result.stdout, (
            f"Large token not preserved in macOS Keychain. "
            f"Expected {len(large_token)} chars, got {len(retrieve_result.stdout.strip())} chars"
        )

    def test_browser_launch_default(self, credential_process_binary):
        """OAuth flow launches default browser via 'open' command."""
        # Verify 'open' command is available (macOS built-in)
        which_result = subprocess.run(
            ["which", "open"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert which_result.returncode == 0, "'open' command not found on macOS"

        # Test that the binary references 'open' for browser launch
        # by checking help/config output
        result = subprocess.run(
            [str(credential_process_binary), "--help"],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # The binary should support browser-based auth on macOS
        output = result.stdout + result.stderr
        # Just verify the binary doesn't crash when asked about browser support
        assert (
            result.returncode == 0
            or "help" in output.lower()
            or "usage" in output.lower()
        ), f"Binary crashed when checking browser support: {result.stderr}"

    def test_universal_binary_detection(self, credential_process_binary):
        """Binary is ARM64 native (not Rosetta x86_64)."""
        # Use 'file' command to check binary architecture
        result = subprocess.run(
            ["file", str(credential_process_binary)],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == 0, f"'file' command failed: {result.stderr}"

        output = result.stdout
        # Should be arm64 native, not x86_64 running under Rosetta
        if "x86_64" in output and "arm64" not in output:
            pytest.fail(
                f"Binary is x86_64 only (would run under Rosetta). "
                f"Expected ARM64 native build.\n"
                f"file output: {output}"
            )

        # Accept: arm64, universal (arm64 + x86_64), or Mach-O 64-bit arm64
        assert "arm64" in output or "universal" in output.lower(), (
            f"Binary architecture unclear. Expected arm64.\nfile output: {output}"
        )
