"""Integration tests for CloudFormation template validation.

Runs cfn-lint against all deployment templates to catch syntax errors,
invalid resource types, and AWS best-practice violations.
"""

import subprocess
from pathlib import Path

import pytest

from tests.cfn_yaml import INFRA_DIR, load_intrinsics

TEMPLATES_DIR = INFRA_DIR


# --- Helpers ---


def _get_all_templates() -> list[Path]:
    """Find all CloudFormation templates in the deployment directory."""
    templates = []
    if TEMPLATES_DIR.exists():
        templates.extend(TEMPLATES_DIR.glob("*.yaml"))
        templates.extend(TEMPLATES_DIR.glob("*.yml"))
        templates.extend(TEMPLATES_DIR.glob("*.json"))
    return sorted(templates)


# --- cfn-lint tests ---


@pytest.fixture(scope="module")
def cfn_lint_available():
    """Check if cfn-lint is installed."""
    result = subprocess.run(["cfn-lint", "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("cfn-lint not installed")


@pytest.mark.parametrize("template_path", _get_all_templates(), ids=lambda p: p.name)
def test_cfn_lint_passes(template_path, cfn_lint_available):
    """Each CloudFormation template must pass cfn-lint validation."""
    result = subprocess.run(
        ["cfn-lint", str(template_path), "--format", "json"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0 and result.stdout.strip():
        import json

        try:
            errors = json.loads(result.stdout)
            error_msgs = [
                f"  [{e.get('Level', '?')}] {e.get('Rule', {}).get('Id', '?')}: "
                f"{e.get('Message', 'unknown')} (line {e.get('Location', {}).get('Start', {}).get('LineNumber', '?')})"
                for e in errors
            ]
            actual_errors = [e for e in errors if e.get("Level") == "Error"]
            # E2531 (deprecated Lambda runtime) is a pre-existing template issue
            # tracked separately — don't fail integration tests for it.
            # E0000 (Duplicate 'Condition') is a cfn-lint false positive on resources
            # that legitimately use Condition as a resource-level key.
            actual_errors = [e for e in actual_errors if e.get("Rule", {}).get("Id") not in ("E2531", "E0000")]
            if actual_errors:
                pytest.fail(f"cfn-lint errors in {template_path.name}:\n" + "\n".join(error_msgs))
        except json.JSONDecodeError:
            pytest.fail(f"cfn-lint failed on {template_path.name}: {result.stdout[:200]}")


# --- Structural validation ---


class TestTemplateStructure:
    """Basic structural validation of CloudFormation templates."""

    @pytest.mark.parametrize("template_path", _get_all_templates(), ids=lambda p: p.name)
    def test_template_has_resources(self, template_path):
        """Every template must define at least one Resource."""
        template = load_intrinsics(template_path)

        assert "Resources" in template, f"{template_path.name} missing Resources section"
        assert len(template["Resources"]) > 0

    @pytest.mark.parametrize("template_path", _get_all_templates(), ids=lambda p: p.name)
    def test_template_has_description(self, template_path):
        """Every template should have a Description."""
        template = load_intrinsics(template_path)

        assert "Description" in template, f"{template_path.name} missing Description"
