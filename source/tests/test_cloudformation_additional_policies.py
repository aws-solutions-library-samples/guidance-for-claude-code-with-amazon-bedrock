# ABOUTME: Tests that all bedrock-auth templates support AdditionalManagedPolicyArns
# ABOUTME: Guards the parameter, condition, and ManagedPolicyArns wiring on federated roles

"""Every auth template must accept AdditionalManagedPolicyArns.

The parameter lets admins attach existing customer-managed policies (e.g. an
IP-restriction policy) to the federated role without manual console edits.
It must default to '' (backwards compatible) and feed the role's
ManagedPolicyArns through the HasAdditionalManagedPolicies condition.
"""

from pathlib import Path

import pytest
import yaml

from tests.test_cloudformation import CloudFormationLoader

INFRA_DIR = Path(__file__).parent.parent.parent / "deployment" / "infrastructure"

AUTH_TEMPLATES = [
    "bedrock-auth-auth0.yaml",
    "bedrock-auth-azure.yaml",
    "bedrock-auth-cognito-pool.yaml",
    "bedrock-auth-generic.yaml",
    "bedrock-auth-google.yaml",
    "bedrock-auth-idc.yaml",
    "bedrock-auth-okta.yaml",
]

# Federated roles that must honor the parameter (per template)
FEDERATED_ROLES = {
    "bedrock-auth-idc.yaml": ["BedrockIDCRole"],
    # All OIDC templates define both federation modes
    "default": ["DirectIAMRole", "CognitoAuthenticatedRole"],
}


def load_template(name: str) -> dict:
    with open(INFRA_DIR / name, encoding="utf-8") as f:
        return yaml.load(f, Loader=CloudFormationLoader)


@pytest.mark.parametrize("template_name", AUTH_TEMPLATES)
def test_parameter_exists_with_safe_default(template_name):
    """Parameter must exist and default to '' so existing stacks update cleanly."""
    template = load_template(template_name)
    params = template.get("Parameters", {})

    assert "AdditionalManagedPolicyArns" in params
    param = params["AdditionalManagedPolicyArns"]
    assert param["Type"] == "String"
    assert param["Default"] == ""
    # Empty must be allowed by the validation pattern
    assert param["AllowedPattern"].startswith("^$|")


@pytest.mark.parametrize("template_name", AUTH_TEMPLATES)
def test_condition_exists(template_name):
    template = load_template(template_name)
    conditions = template.get("Conditions", {})
    assert "HasAdditionalManagedPolicies" in conditions


@pytest.mark.parametrize("template_name", AUTH_TEMPLATES)
def test_federated_roles_append_additional_policies(template_name):
    """ManagedPolicyArns must keep BedrockAccessPolicy and append the extra ARNs."""
    template = load_template(template_name)
    resources = template.get("Resources", {})
    role_names = FEDERATED_ROLES.get(template_name, FEDERATED_ROLES["default"])

    for role_name in role_names:
        assert role_name in resources, f"{template_name}: missing {role_name}"
        policy_arns = resources[role_name]["Properties"]["ManagedPolicyArns"]

        # Wired through the condition
        assert isinstance(policy_arns, dict) and "Fn::If" in policy_arns, (
            f"{template_name}/{role_name}: ManagedPolicyArns must use Fn::If"
        )
        condition, with_extra, without_extra = policy_arns["Fn::If"]
        assert condition == "HasAdditionalManagedPolicies"

        # False branch: unchanged behavior — only the stack-created policy
        assert without_extra == [{"Ref": "BedrockAccessPolicy"}]

        # True branch: base policy joined with the parameter, then split
        rendered = str(with_extra)
        assert "Fn::Split" in rendered
        assert "BedrockAccessPolicy" in rendered
        assert "AdditionalManagedPolicyArns" in rendered


@pytest.mark.parametrize("template_name", AUTH_TEMPLATES)
def test_unauthenticated_roles_not_extended(template_name):
    """The extra policies must never reach the unauthenticated Cognito role."""
    template = load_template(template_name)
    resources = template.get("Resources", {})
    unauth = resources.get("CognitoUnauthenticatedRole")
    if unauth is None:
        return
    rendered = str(unauth["Properties"].get("ManagedPolicyArns", ""))
    assert "AdditionalManagedPolicyArns" not in rendered
