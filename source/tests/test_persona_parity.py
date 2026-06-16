# ABOUTME: Cross-impl parity — Go and Python persona resolvers must agree, byte for byte
# ABOUTME: Drives both over the SAME shared fixtures; also guards buildSessionName from drift

"""Go ↔ Python persona-resolution parity (spec §4.3, credential-helper-parity.md).

The §4.3 resolution algorithm is duplicated across the Go credential-process /
otel-helper (`internal/persona`) and the Python `persona_resolution.py`. A drift
between them splits a user's identity (wrong role, wrong cost attribution), so
this test proves they agree:

1. **Python side** — run :func:`resolve_persona` over every case in the shared
   fixture file and assert it yields each case's ``expected`` name.
2. **Go side** — shell out to ``go test ./internal/persona/ -run
   TestResolveAgainstSharedFixtures``; that Go test loads the *same* fixture file
   and asserts the Go resolver yields the same ``expected`` names. Exit 0 ⇒ Go
   agrees with the fixtures.

Since both implementations are pinned to the *same* fixture oracle, agreement on
the fixtures is agreement with each other (the fixtures are the contract).

3. **buildSessionName guard** — persona work must not have touched the STS
   session-name logic, so we shell ``go test ./internal/federation/ -run
   SessionName`` and require exit 0 (credential-helper-parity.md).

If the Go toolchain is unavailable the Go-dependent tests *fail* (not skip): a
silent skip would let real drift through unnoticed in CI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_with_bedrock.persona_resolution import resolve_persona

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GO_DIR = _REPO_ROOT / "source" / "go"
_FIXTURES = _REPO_ROOT / "source" / "tests" / "fixtures" / "persona_resolution_cases.json"


def _load_cases() -> list[dict]:
    with open(_FIXTURES, encoding="utf-8") as fh:
        cases = json.load(fh)
    assert isinstance(cases, list) and len(cases) >= 5, "expected >=5 shared fixture cases"
    return cases


def _go_binary() -> str:
    """Locate the `go` binary.

    pytest may run with a minimal PATH, so fall back to the Homebrew location
    before giving up. Returns the executable path; raises if none is runnable.
    """
    found = shutil.which("go")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/go", "/usr/local/bin/go", "/usr/local/go/bin/go"):
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("go toolchain not found on PATH or known locations")


def _run_go_test(run_filter: str, package: str) -> subprocess.CompletedProcess:
    """Run `go test <package> -run <run_filter>` from the Go module dir."""
    go = _go_binary()
    env = dict(os.environ)
    # Warm module cache; fall back to direct fetch if a proxy stalls (per task note).
    env.setdefault("GOPROXY", "direct")
    env.setdefault("GOFLAGS", "-mod=mod")
    return subprocess.run(
        [go, "test", package, "-run", run_filter, "-count=1"],
        cwd=str(_GO_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _python_resolved_name(case: dict) -> str | None:
    persona = resolve_persona(case["groups"], case["personas"], case.get("fallback"))
    return persona["name"] if persona else None


class TestPythonSideMatchesFixtures:
    """The Python resolver agrees with every shared-fixture expectation."""

    def test_all_fixture_cases(self):
        cases = _load_cases()
        mismatches = []
        for case in cases:
            got = _python_resolved_name(case)
            want = case.get("expected")
            if got != want:
                mismatches.append(f"{case.get('name')}: Python got {got!r}, fixture wants {want!r}")
        assert not mismatches, "Python resolver disagrees with fixtures:\n" + "\n".join(mismatches)

    @pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c.get("name", "case"))
    def test_each_case(self, case):
        assert _python_resolved_name(case) == case.get("expected")


class TestGoSideMatchesFixtures:
    """The Go resolver agrees with the same shared fixtures (shell-out)."""

    def test_go_resolver_against_shared_fixtures(self):
        result = _run_go_test("TestResolveAgainstSharedFixtures", "./internal/persona/")
        assert result.returncode == 0, (
            "Go persona resolver disagrees with shared fixtures (or build failed):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


class TestParityCrossCheck:
    """Both implementations are pinned to the same fixture oracle => they agree.

    This makes the transitive argument explicit: every fixture has a single
    ``expected`` value; the Python test asserts Python==expected and the Go test
    asserts Go==expected, therefore Python==Go for all cases.
    """

    def test_fixtures_define_a_single_expected_per_case(self):
        cases = _load_cases()
        # Each case must carry an explicit expected (name or null) — otherwise the
        # parity oracle is ambiguous and the cross-check below is meaningless.
        for case in cases:
            assert "expected" in case, f"fixture case {case.get('name')!r} missing 'expected'"

    def test_python_and_go_both_green_on_same_fixtures(self):
        # Python side.
        cases = _load_cases()
        for case in cases:
            assert _python_resolved_name(case) == case.get("expected")
        # Go side (same file).
        result = _run_go_test("TestResolveAgainstSharedFixtures", "./internal/persona/")
        assert result.returncode == 0, f"Go side failed:\n{result.stdout}\n{result.stderr}"


class TestBuildSessionNameUnchanged:
    """Persona work must not perturb the STS session-name parity (issue #204)."""

    def test_session_name_tests_still_pass(self):
        result = _run_go_test("SessionName", "./internal/federation/")
        assert result.returncode == 0, (
            "buildSessionName parity tests regressed — persona work must not touch "
            f"session-name logic:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
