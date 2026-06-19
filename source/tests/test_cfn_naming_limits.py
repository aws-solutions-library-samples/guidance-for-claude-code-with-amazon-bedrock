# ABOUTME: Static analysis tests ensuring CF templates don't use explicit resource names that exceed AWS limits
# ABOUTME: Prevents regression of issue #86 (target group name >32 chars)

"""CloudFormation resource naming limit tests.

Ensures that CF templates don't use explicit Name properties on resources
with strict AWS character limits. CloudFormation auto-generates names that
respect limits when Name is omitted.

Bug this prevents:
- #86: Target group name exceeded 32 chars because it used ${AWS::StackName}-tg
  and the monitoring stack name is {identity_pool_name}-otel-collector (already 31+ chars)
"""

from pathlib import Path

import pytest
import yaml

INFRA_DIR = Path(__file__).parent.parent.parent / "deployment" / "infrastructure"

# AWS resource types with strict naming limits
RESOURCE_NAME_LIMITS = {
    "AWS::ElasticLoadBalancingV2::TargetGroup": 32,
}

# Resources where explicit naming causes replace/AlreadyExists on stack updates.
# ALB Name: condition-dependent values trigger ALB replacement (create-and-replace semantics).
# ECS ServiceName: conditional logical IDs sharing a name cause AlreadyExists — CloudFormation
# creates the new resource before deleting the old.
RESOURCES_NO_EXPLICIT_NAME = {
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "Name",
    "AWS::ECS::Service": "ServiceName",
}

OTEL_COLLECTOR_TEMPLATE = INFRA_DIR / "otel-collector.yaml"


class CFLoader(yaml.SafeLoader):
    """YAML loader that handles CloudFormation intrinsic functions."""

    pass


# Register CF intrinsic constructors
for tag in [
    "!Ref",
    "!Sub",
    "!GetAtt",
    "!If",
    "!Equals",
    "!Not",
    "!Select",
    "!Join",
    "!Split",
    "!FindInMap",
    "!Condition",
    "!Or",
    "!And",
]:
    CFLoader.add_constructor(
        tag,
        lambda loader, node: (
            loader.construct_scalar(node)
            if isinstance(node, yaml.ScalarNode)
            else loader.construct_sequence(node)
            if isinstance(node, yaml.SequenceNode)
            else loader.construct_mapping(node)
        ),
    )


def _get_all_cf_templates():
    """Get all CloudFormation YAML templates."""
    if not INFRA_DIR.exists():
        pytest.skip("deployment/infrastructure/ not found")
    return list(INFRA_DIR.glob("*.yaml"))


class TestCFResourceNamingLimits:
    """Ensure CF templates don't use explicit Name on length-limited resources."""

    @pytest.fixture
    def templates(self):
        templates = _get_all_cf_templates()
        if not templates:
            pytest.skip("No CF templates found")
        return templates

    def test_no_explicit_target_group_name(self, templates):
        """Target groups must NOT have explicit Name (32-char limit too easy to exceed).

        With stack names like 'claude-code-auth-otel-collector' (31 chars),
        any suffix pushes past 32. Let CloudFormation auto-generate.
        """
        violations = []
        for template_path in templates:
            with open(template_path, encoding="utf-8") as f:
                try:
                    doc = yaml.load(f, Loader=CFLoader)
                except yaml.YAMLError:
                    continue

            if not doc or "Resources" not in doc:
                continue

            for logical_id, resource in doc["Resources"].items():
                if not isinstance(resource, dict):
                    continue
                rtype = resource.get("Type", "")
                if rtype in RESOURCE_NAME_LIMITS:
                    props = resource.get("Properties", {})
                    if isinstance(props, dict) and "Name" in props:
                        violations.append(
                            f"{template_path.name}:{logical_id} ({rtype}) has explicit Name "
                            f"— limit is {RESOURCE_NAME_LIMITS[rtype]} chars, "
                            f"remove Name to let CloudFormation auto-generate"
                        )

        assert not violations, "CF templates have explicit Name on length-limited resources:\n" + "\n".join(
            f"  • {v}" for v in violations
        )

    def test_otel_collector_no_hardcoded_names(self):
        """otel-collector.yaml must not have explicit ALB Name or ECS ServiceName.

        ALB Name with conditional values triggers ALB replacement on condition toggle.
        ECS ServiceName on conditional resources causes AlreadyExists — CloudFormation
        creates the new resource before deleting the old when logical IDs change.
        """
        if not OTEL_COLLECTOR_TEMPLATE.exists():
            pytest.skip("otel-collector.yaml not found")

        with open(OTEL_COLLECTOR_TEMPLATE, encoding="utf-8") as f:
            doc = yaml.load(f, Loader=CFLoader)

        violations = []
        for logical_id, resource in doc["Resources"].items():
            if not isinstance(resource, dict):
                continue
            rtype = resource.get("Type", "")
            if rtype in RESOURCES_NO_EXPLICIT_NAME:
                prop_name = RESOURCES_NO_EXPLICIT_NAME[rtype]
                props = resource.get("Properties", {})
                if isinstance(props, dict) and prop_name in props:
                    violations.append(f"{logical_id} ({rtype}) has explicit {prop_name}")

        assert not violations, "otel-collector.yaml has hardcoded names that break stack updates:\n" + "\n".join(
            f"  • {v}" for v in violations
        )

    def test_stack_name_suffix_inventory(self):
        """Document all ${AWS::StackName}-* patterns to track overflow risk.

        This test doesn't fail — it's a documentation/inventory test that
        surfaces all stack-name-derived resource names for review.
        """
        patterns = []
        for template_path in _get_all_cf_templates():
            with open(template_path, encoding="utf-8") as f:
                content = f.read()
            import re

            matches = re.findall(r"\$\{AWS::StackName\}([^'\"}\s]+)", content)
            for suffix in set(matches):
                patterns.append((template_path.name, suffix))

        # Just verify we found patterns (sanity check)
        assert len(patterns) > 0, "Expected to find ${AWS::StackName} patterns"


class TestIdentityPoolNameOverflow:
    """Verify identity_pool_name + stack suffixes don't overflow resource limits."""

    # All stack suffixes used in deploy.py
    STACK_SUFFIXES = {
        "auth": "-stack",
        "networking": "-networking",
        "monitoring": "-otel-collector",
        "dashboard": "-dashboard",
        "cowork-dashboard": "-cowork-dashboard",
        "analytics": "-analytics",
        "s3bucket": "-s3bucket",
        "distribution": "-distribution",
        "quota": "-quota",
        "codebuild": "-codebuild",
    }

    def test_default_name_fits_all_stacks(self):
        """The default 'claude-code-auth' must work with all stack suffixes."""
        default_name = "claude-code-auth"
        for _, suffix in self.STACK_SUFFIXES.items():
            stack_name = f"{default_name}{suffix}"
            # CF stack name limit is 128
            assert len(stack_name) <= 128, (
                f"Default name + '{suffix}' = '{stack_name}' ({len(stack_name)} chars) " f"exceeds CF stack name limit"
            )

    def test_max_validated_name_fits_all_stacks(self):
        """A 20-char name (max allowed by validation) must work with all stacks."""
        max_name = "a" * 20
        for _, suffix in self.STACK_SUFFIXES.items():
            stack_name = f"{max_name}{suffix}"
            assert len(stack_name) <= 128, f"20-char name + '{suffix}' = {len(stack_name)} chars exceeds limit"

    def test_no_target_group_overflow_with_max_name(self):
        """Even if someone re-adds a -tg suffix, 20-char name fits in 32.

        20 (name) + 15 (-otel-collector) + 3 (-tg) = 38 > 32
        This proves we MUST NOT re-add explicit target group names.
        """
        max_name = "a" * 20
        monitoring_stack = f"{max_name}-otel-collector"
        tg_name = f"{monitoring_stack}-tg"
        # This SHOULD overflow — proving the explicit Name must stay removed
        assert len(tg_name) > 32, (
            "If this passes at <=32, someone might think it's safe to re-add "
            "the explicit Name — update the max limit if this fails"
        )
