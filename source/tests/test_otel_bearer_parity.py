# ABOUTME: Parity + single-choke-point guard for the otel-helper Bearer literal.
# ABOUTME: Pins Go attachBearer ↔ Python _attach_bearer to one definition each.

"""Bearer-attach parity and single-occurrence guard.

The `Authorization: Bearer <jwt>` header is what the OTEL collector's ALB
jwt-validation action checks. A wrong or missing value yields a 401, the
telemetry batch is dropped, and per-user cost attribution goes dark. That
literal was historically hand-written at 8 sites (4 Go, 4 Python); a single
setter per language makes the contract impossible to half-break and gives the
Go↔Python parity check one assertion point.

Two layers, mirroring the repo's existing parity convention
(test_credential_process_contract.py — static analysis, no binary spawned):

  * behavioral — call _attach_bearer directly; mirror of Go's TestAttachBearer.
  * static guard — the Bearer literal appears exactly once per language in
    non-test source, so the dedup cannot silently regress.
"""

from pathlib import Path

import pytest

from otel_helper.__main__ import _attach_bearer

SOURCE_ROOT = Path(__file__).parent.parent
GO_HELPER = SOURCE_ROOT / "go" / "cmd" / "otel-helper" / "main.go"
PY_HELPER = SOURCE_ROOT / "otel_helper" / "__main__.py"


class TestAttachBearer:
    """Behavioral half of parity — the Python side of the contract Go's
    TestAttachBearer pins on its side."""

    def test_non_empty_token_sets_bearer_header(self):
        headers = {}
        _attach_bearer(headers, "abc.def.ghi")
        assert headers["authorization"] == "Bearer abc.def.ghi"

    @pytest.mark.parametrize("empty", ["", None])
    def test_empty_token_omits_key(self, empty):
        # Sending "Bearer " with no JWT is worse than omitting the header — the
        # ALB would 401 on it. Matches Go attachBearer's token != "" guard.
        headers = {}
        _attach_bearer(headers, empty)
        assert "authorization" not in headers

    def test_existing_attribution_preserved(self):
        headers = {"x-user-email": "a@b.com"}
        _attach_bearer(headers, "tok")
        assert headers["x-user-email"] == "a@b.com"
        assert headers["authorization"] == "Bearer tok"


class TestBearerSingleChokePoint:
    """Static guard: the Bearer literal must live at exactly one site per
    language, so a future edit cannot reintroduce a hand-rolled copy that
    drifts from the other implementation."""

    def test_go_has_single_bearer_literal(self):
        # The Go literal is the byte sequence `"Bearer "` (with the trailing
        # space + quote), only ever inside attachBearer.
        go_code = GO_HELPER.read_text(encoding="utf-8")
        count = go_code.count('"Bearer "')
        assert count == 1, (
            f'Go helper must contain the `"Bearer "` literal exactly once '
            f"(inside attachBearer); found {count}. A new hand-rolled copy "
            f"would split the Go↔Python parity contract."
        )

    def test_python_has_single_bearer_literal(self):
        # The Python literal is the f-string `f"Bearer {`, only ever inside
        # _attach_bearer.
        py_code = PY_HELPER.read_text(encoding="utf-8")
        count = py_code.count('f"Bearer {')
        assert count == 1, (
            f'Python helper must contain the `f"Bearer {{` literal exactly once '
            f"(inside _attach_bearer); found {count}. A new hand-rolled copy "
            f"would split the Go↔Python parity contract."
        )

    def test_both_helpers_emit_identical_format(self):
        """Cross-language parity: both choke points emit the same wire format
        under the same lowercase 'authorization' key."""
        go_code = GO_HELPER.read_text(encoding="utf-8")
        py_code = PY_HELPER.read_text(encoding="utf-8")

        # Same prefix literal.
        assert '"Bearer "' in go_code
        assert 'f"Bearer {' in py_code
        # Same (lowercase) header key on both sides — the OTEL collector matches
        # headers case-sensitively in lowercase.
        assert 'headers["authorization"]' in go_code
        assert 'headers["authorization"]' in py_code
