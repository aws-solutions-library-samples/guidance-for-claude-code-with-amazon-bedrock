# ABOUTME: Static analysis tests ensuring Cognito issuer/provider URLs derive their region from
# ABOUTME: the User Pool ID, not the deployment region (AWS::Region). Prevents regression of issue #596.

"""Cognito cross-region deployment tests.

Bug this prevents:
- #596: When the Cognito User Pool lives in a different region than the stack
  (e.g. pool in eu-west-1, infra in eu-west-3), the OIDC provider / identity-pool
  provider name was built from ${AWS::Region}, pointing at the wrong region and
  failing deployment. The pool's region is encoded in its ID (<region>_<id>), so
  the templates must derive it from CognitoUserPoolId via !Split, mirroring the
  Python logic in deploy.py (pool_id.split("_")[0]).
"""

import re
from pathlib import Path

import pytest

INFRA_DIR = Path(__file__).parent.parent.parent / "deployment" / "infrastructure"

# Templates that build a cognito-idp issuer/provider URL from CognitoUserPoolId.
COGNITO_TEMPLATES = [
    "bedrock-auth-cognito-pool.yaml",
    "cognito-identity-pool.yaml",
]

# The bug: a cognito-idp host built from the deployment region instead of the pool's region.
_BAD_PATTERN = re.compile(r"cognito-idp\.\$\{AWS::Region\}\.amazonaws\.com/\$\{CognitoUserPoolId\}")

# The fix: the host's region is a ${PoolRegion} substitution derived from the pool ID.
_GOOD_PATTERN = re.compile(r"cognito-idp\.\$\{PoolRegion\}\.amazonaws\.com/\$\{CognitoUserPoolId\}")


def _read(template: str) -> str:
    path = INFRA_DIR / template
    if not path.exists():
        pytest.skip(f"{path} not found")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("template", COGNITO_TEMPLATES)
def test_no_cognito_issuer_uses_deployment_region(template):
    """No cognito-idp issuer/provider URL may be built from ${AWS::Region} (issue #596)."""
    content = _read(template)
    bad = _BAD_PATTERN.findall(content)
    assert not bad, (
        f"{template} builds a Cognito issuer URL from ${{AWS::Region}} ({len(bad)} site(s)). "
        "Derive the region from the User Pool ID instead (see issue #596)."
    )


@pytest.mark.parametrize("template", COGNITO_TEMPLATES)
def test_cognito_issuer_derives_region_from_pool_id(template):
    """Every cognito-idp issuer URL must derive its region from the pool ID via ${PoolRegion}."""
    content = _read(template)
    assert _GOOD_PATTERN.search(content), (
        f"{template} should build the Cognito issuer URL with a ${{PoolRegion}} substitution "
        "derived from CognitoUserPoolId (!Select [0, !Split ['_', !Ref CognitoUserPoolId]])."
    )
    # The PoolRegion mapping must actually split the pool ID on '_'.
    assert "!Split ['_', !Ref CognitoUserPoolId]" in content, (
        f"{template} must derive PoolRegion from !Split ['_', !Ref CognitoUserPoolId]."
    )
