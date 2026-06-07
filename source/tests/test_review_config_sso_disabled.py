"""Regression test for PR #367: _review_configuration must not crash when SSO is disabled."""

import ast
from pathlib import Path


INIT_FILE = Path(__file__).resolve().parents[1] / "claude_code_with_bedrock" / "cli" / "commands" / "init.py"


class TestReviewConfigSSO:
    """Ensure _review_configuration handles sso_enabled=False without KeyError."""

    def _get_review_source(self):
        """Extract the _review_configuration method source."""
        content = INIT_FILE.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_review_configuration":
                start = node.lineno - 1
                end = node.end_lineno
                lines = content.split("\n")[start:end]
                return "\n".join(lines)
        return ""

    def test_identity_pool_uses_safe_access(self):
        """identity_pool_name must use .get() not direct dict access."""
        source = self._get_review_source()
        # Must NOT have config["aws"]["identity_pool_name"] (bare key access)
        assert 'config["aws"]["identity_pool_name"]' not in source, (
            "_review_configuration accesses config['aws']['identity_pool_name'] directly. "
            "This causes KeyError when SSO is disabled and no identity pool exists. "
            "Use config.get('aws', {}).get('identity_pool_name', '—') instead."
        )

    def test_monitoring_uses_safe_access(self):
        """monitoring.enabled must use .get() not direct dict access."""
        source = self._get_review_source()
        # Must NOT have config["monitoring"]["enabled"] (bare key access)
        assert 'config["monitoring"]["enabled"]' not in source, (
            "_review_configuration accesses config['monitoring']['enabled'] directly. "
            "This causes KeyError when monitoring section is absent. "
            "Use config.get('monitoring', {}).get('enabled') instead."
        )

    def test_resources_section_guards_sso(self):
        """'Resources to be created' section must not show Cognito/OIDC when SSO disabled."""
        source = self._get_review_source()
        # The federation_type / Cognito block must be inside an sso_enabled check
        assert "if sso_enabled" in source, (
            "_review_configuration 'Resources to be created' section must guard "
            "Cognito/OIDC resource listing behind sso_enabled check. "
            "Without this, non-SSO users see misleading resource list."
        )

    def test_identity_pool_row_guarded(self):
        """Identity Pool table row must only show when SSO is enabled."""
        source = self._get_review_source()
        # identity_pool_name should appear inside an if sso_enabled block
        lines = source.split("\n")
        in_sso_block = False
        pool_in_block = False
        for line in lines:
            if "if sso_enabled" in line:
                in_sso_block = True
            if in_sso_block and "identity_pool_name" in line:
                pool_in_block = True
                break
            if in_sso_block and line.strip() and not line.strip().startswith(("#", "table", "if", "else")):
                if line.strip().startswith("else") or (not line.startswith(" " * 8) and line.strip()):
                    pass  # Keep going through the block
        assert pool_in_block, (
            "identity_pool_name display must be inside an 'if sso_enabled' guard. "
            "Non-SSO deployments don't have an identity pool."
        )
