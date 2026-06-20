# ABOUTME: Static analysis preventing hand-built AWS ARNs that omit server-assigned parts
# ABOUTME: Enforces .claude/rules/aws-identifiers.md (Secrets Manager suffix bug class)

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "claude_code_with_bedrock"

# f-string ARNs for services whose ARNs carry an unpredictable server-assigned
# part (e.g. Secrets Manager's random suffix). Reading these from the API is the
# only correct option; constructing them is the bug. Scoped to f-strings because
# that is the only interpolation style the codebase uses for ARNs; .format()/%
# are intentionally out of scope to keep the check high-signal.
DANGEROUS = re.compile(r'f["\'][^"\']*arn:aws:(secretsmanager)[^"\']*\{[^"\']*\}[^"\']*["\']')

# Lines explicitly accepted (e.g. documented last-resort fallback after
# describe_secret fails) carry this marker. Deliberately NOT a `# noqa:` code —
# ruff parses `# noqa:` and would reject a non-standard code (and `ruff --fix`
# could strip it), so this uses a plain project-specific comment instead.
ALLOW = "# allow-handbuilt-arn"


def _py_files():
    return list(SRC.rglob("*.py"))


def test_no_handbuilt_secretsmanager_arns():
    offenders = []
    for f in _py_files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if DANGEROUS.search(line) and ALLOW not in line:
                offenders.append(f"{f.relative_to(SRC.parent)}:{i}: {line.strip()}")
    assert not offenders, (
        "Hand-built Secrets Manager ARN(s) found - read the ARN from the API "
        "response (see .claude/rules/aws-identifiers.md). If a documented "
        f"last-resort fallback, append `{ALLOW}`:\n" + "\n".join(offenders)
    )
