"""Regression test for issue #346: ALB JWT aud claim format.

The OTEL collector's ALB listener rule validates JWT tokens. The `aud`
claim must use `single-string` format because most OIDC providers (Okta,
Azure AD, Auth0, Cognito) emit `aud` as a plain string, not a JSON array.

Using `string-array` causes valid tokens to be rejected.
"""

from pathlib import Path

import pytest


OTEL_TEMPLATE = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure" / "otel-collector.yaml"


@pytest.mark.skipif(not OTEL_TEMPLATE.exists(), reason="otel-collector.yaml not found")
class TestAlbJwtAudFormat:
    """Pin the ALB JWT aud claim format to prevent regression."""

    @pytest.fixture
    def template_content(self):
        with open(OTEL_TEMPLATE, encoding="utf-8") as f:
            return f.read()

    def test_aud_claim_uses_single_string_format(self, template_content):
        """The aud claim must use 'single-string' format, not 'string-array'.

        Most OIDC providers return aud as a plain string (the client_id).
        ALB's string-array format expects a JSON array, which causes valid
        tokens to fail validation. See issue #346.
        """
        # Find the aud claim section and verify its format
        lines = template_content.splitlines()
        for i, line in enumerate(lines):
            if "Name: aud" in line:
                # Check the next line for the Format field
                for j in range(i + 1, min(i + 3, len(lines))):
                    if "Format:" in lines[j]:
                        assert "single-string" in lines[j], (
                            f"Line {j+1}: aud claim uses wrong format.\n"
                            f"  Found:    {lines[j].strip()}\n"
                            f"  Expected: Format: single-string\n"
                            f"  Reason:   Most OIDC providers emit aud as a plain string, "
                            f"not a JSON array. See issue #346."
                        )
                        return

        pytest.fail(
            "Could not find 'Name: aud' with a Format field in otel-collector.yaml. "
            "Template structure may have changed."
        )

    def test_no_string_array_format_for_aud(self, template_content):
        """Ensure 'string-array' is never used for the aud claim validation.

        This is a broader catch: even if the template is restructured,
        string-array for aud should never appear.
        """
        lines = template_content.splitlines()
        for i, line in enumerate(lines):
            if "Name: aud" in line:
                # Check surrounding lines for string-array
                context = lines[max(0, i-1):min(len(lines), i+4)]
                for ctx_line in context:
                    assert "string-array" not in ctx_line, (
                        f"Found 'string-array' near aud claim definition (line {i+1}). "
                        f"Must be 'single-string'. See issue #346."
                    )
