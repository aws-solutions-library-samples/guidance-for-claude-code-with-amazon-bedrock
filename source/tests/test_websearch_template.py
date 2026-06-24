# ABOUTME: Contract tests for the AgentCore web-search CloudFormation template (Story A, T2).
# ABOUTME: Verifies AC1 (gateway/target/role shapes), AC3 (per-provider CUSTOM_JWT params), AC9 (cfn-lint).

"""Tests for deployment/infrastructure/agentcore-websearch.yaml.

Source contract: websearch-feature/spec.md AC1 / AC3 / AC9.

- AC1: Gateway (CUSTOM_JWT, MCP) + web-search connector target + service role
  with bedrock-agentcore:InvokeWebSearch.
- AC3: the CUSTOM_JWT authorizer config (discoveryUrl + allowedAudience == client_id)
  is parameterized (values produced per-provider by deploy.py in T4).
- AC9: the template passes the repo's cfn-lint gate (CI ignore-check list).
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


# CloudFormation intrinsic-function-aware YAML loader (mirrors test_cloudformation.py).
class CloudFormationLoader(yaml.SafeLoader):
    """YAML loader that tolerates CloudFormation short-form intrinsics."""

    pass


def _scalar(tag):
    def ctor(loader, node):
        return {tag: loader.construct_scalar(node)}

    return ctor


def _sequence(tag):
    def ctor(loader, node):
        return {tag: loader.construct_sequence(node)}

    return ctor


def _getatt(loader, node):
    if isinstance(node, yaml.SequenceNode):
        return {"Fn::GetAtt": loader.construct_sequence(node)}
    return {"Fn::GetAtt": loader.construct_scalar(node).split(".", 1)}


CloudFormationLoader.add_constructor("!Ref", _scalar("Ref"))
CloudFormationLoader.add_constructor("!Sub", _scalar("Fn::Sub"))
CloudFormationLoader.add_constructor("!GetAtt", _getatt)
CloudFormationLoader.add_constructor("!Join", _sequence("Fn::Join"))
CloudFormationLoader.add_constructor("!Equals", _sequence("Fn::Equals"))
CloudFormationLoader.add_constructor("!If", _sequence("Fn::If"))
CloudFormationLoader.add_constructor("!Not", _sequence("Fn::Not"))
CloudFormationLoader.add_constructor("!And", _sequence("Fn::And"))
CloudFormationLoader.add_constructor("!Or", _sequence("Fn::Or"))
CloudFormationLoader.add_constructor("!Select", _sequence("Fn::Select"))
CloudFormationLoader.add_constructor("!Split", _sequence("Fn::Split"))
CloudFormationLoader.add_constructor("!Condition", _scalar("Condition"))


TEMPLATE_PATH = (
    Path(__file__).parent.parent.parent / "deployment" / "infrastructure" / "agentcore-websearch.yaml"
)

# Mirror the cfn-lint ignore-check list from .github/workflows/pytest-ci.yml so the
# offline gate matches CI exactly (AC9).
CI_IGNORE_CHECKS = [
    "W3002", "W2001", "E3012", "E3005", "E0000", "W1001", "W1028", "W1030",
    "W2010", "W2531", "W3005", "W3011", "W3037", "W8001",
]


def _walk_strings(obj):
    """Yield every string anywhere in a nested dict/list — keys included.

    Dict keys matter for IAM: condition operators carry their condition key as a
    dict key (e.g. {"StringEquals": {"aws:SourceAccount": ...}}).
    """
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


@pytest.fixture(scope="module")
def template():
    assert TEMPLATE_PATH.exists(), f"template missing: {TEMPLATE_PATH}"
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        return yaml.load(f, Loader=CloudFormationLoader)


@pytest.fixture(scope="module")
def resources(template):
    return template.get("Resources", {})


def _resource_of_type(resources, cfn_type):
    return {k: v for k, v in resources.items() if v.get("Type") == cfn_type}


class TestParameters:
    """AC3: per-provider CUSTOM_JWT config is supplied as parameters (deploy.py fills values)."""

    def test_discovery_url_param(self, template):
        params = template.get("Parameters", {})
        assert "DiscoveryUrl" in params, "DiscoveryUrl param required (per-provider OIDC discovery)"

    def test_client_id_param(self, template):
        params = template.get("Parameters", {})
        assert "ClientId" in params, "ClientId param required (becomes allowedAudience)"

    def test_domain_exclude_list_param_optional(self, template):
        # Optional domain filter — present and defaulted so the stack deploys without it.
        params = template.get("Parameters", {})
        assert "DomainExcludeList" in params


class TestGateway:
    """AC1: AgentCore Gateway with CUSTOM_JWT authorizer + MCP protocol."""

    def test_gateway_resource_exists(self, resources):
        gws = _resource_of_type(resources, "AWS::BedrockAgentCore::Gateway")
        assert len(gws) == 1, "exactly one Gateway resource expected"

    def test_gateway_protocol_mcp(self, resources):
        gw = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::Gateway").values()))
        assert gw["Properties"].get("ProtocolType") == "MCP"

    def test_gateway_custom_jwt_authorizer(self, resources):
        gw = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::Gateway").values()))
        props = gw["Properties"]
        assert props.get("AuthorizerType") == "CUSTOM_JWT"
        cfg = props.get("AuthorizerConfiguration", {})
        jwt = cfg.get("CustomJWTAuthorizer", cfg.get("customJWTAuthorizer", {}))
        assert jwt, "AuthorizerConfiguration must carry a customJWTAuthorizer block"
        # discoveryUrl wired from the DiscoveryUrl param
        assert any("DiscoveryUrl" in s for s in _walk_strings(jwt)), "discoveryUrl must reference DiscoveryUrl param"
        # Audience match (NOT client match): the uniform OIDC id_token carries the
        # client_id in aud, not in a client_id claim, so the authorizer must match
        # on AllowedAudience. AllowedClients would 403 the id_token (Phase 0
        # experiment A; websearch-feature/research/idtoken-experiment.md).
        aud = jwt.get("AllowedAudience", jwt.get("allowedAudience"))
        assert aud, "authorizer must match on AllowedAudience (the id_token's aud), not AllowedClients"
        assert "AllowedClients" not in jwt and "allowedClients" not in jwt, (
            "AllowedClients matches the client_id claim, which the id_token lacks — would 403"
        )
        # allowedAudience wired from the ClientId param
        assert any("ClientId" in s for s in _walk_strings(aud)), "allowedAudience must reference ClientId param"

    def test_gateway_name_uses_stack_name(self, resources):
        # cfn-naming rule: no hardcoded names.
        gw = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::Gateway").values()))
        name = gw["Properties"].get("Name")
        assert isinstance(name, dict) and "Fn::Sub" in name
        assert "${AWS::StackName}" in name["Fn::Sub"]


class TestGatewayTarget:
    """AC1: web-search connector target."""

    def test_target_resource_exists(self, resources):
        tgts = _resource_of_type(resources, "AWS::BedrockAgentCore::GatewayTarget")
        assert len(tgts) == 1, "exactly one GatewayTarget resource expected"

    def test_target_connector_shape_exact(self, resources):
        # Pin the exact nesting the AgentCore control plane requires:
        # TargetConfiguration.Mcp.Connector.Source.ConnectorId == "web-search".
        # A live deploy proved the service rejects TargetConfiguration.Mcp.
        # ConnectorTargetConfiguration (the cfn-lint definition name) — the real
        # key is "Connector". This asserts the path, not just a loose substring.
        tgt = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::GatewayTarget").values()))
        connector = tgt["Properties"]["TargetConfiguration"]["Mcp"]["Connector"]
        assert connector["Source"]["ConnectorId"] == "web-search"

    def test_target_parameter_values_present(self, resources):
        # The service rejects a config entry without ParameterValues
        # ("Connector configurations must not be empty"). Empty {} is the
        # minimal valid form; here it's an Fn::If carrying {} on the no-filter branch.
        tgt = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::GatewayTarget").values()))
        configs = tgt["Properties"]["TargetConfiguration"]["Mcp"]["Connector"]["Configurations"]
        assert configs and "ParameterValues" in configs[0]

    def test_target_credential_provider_is_gateway_iam_role(self, resources):
        tgt = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::GatewayTarget").values()))
        cpc = tgt["Properties"].get("CredentialProviderConfigurations")
        assert isinstance(cpc, list) and len(cpc) == 1, "exactly one credential provider config (max 1)"
        assert any("GATEWAY_IAM_ROLE" in s for s in _walk_strings(cpc))

    def test_target_references_gateway(self, resources):
        tgt = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::GatewayTarget").values()))
        gw_name = next(iter(_resource_of_type(resources, "AWS::BedrockAgentCore::Gateway").keys()))
        assert gw_name in list(_walk_strings(tgt["Properties"])), "target must reference the gateway"


class TestServiceRole:
    """AC1: service role trusts bedrock-agentcore + grants InvokeWebSearch."""

    def _role(self, resources):
        roles = _resource_of_type(resources, "AWS::IAM::Role")
        assert roles, "a service role is required"
        return next(iter(roles.values()))

    def test_role_trusts_agentcore(self, resources):
        role = self._role(resources)
        trust = role["Properties"]["AssumeRolePolicyDocument"]
        assert any("bedrock-agentcore.amazonaws.com" in s for s in _walk_strings(trust))

    def test_role_trust_scoped_by_source_account(self, resources):
        # Confused-deputy guard (findings 6m): SourceAccount / SourceArn condition.
        role = self._role(resources)
        trust = role["Properties"]["AssumeRolePolicyDocument"]
        strings = list(_walk_strings(trust))
        assert any("aws:SourceAccount" in s or "aws:SourceArn" in s for s in strings)

    def test_role_grants_invoke_web_search(self, resources):
        role = self._role(resources)
        actions = list(_walk_strings(role["Properties"].get("Policies", [])))
        assert any("bedrock-agentcore:InvokeWebSearch" in a for a in actions)


class TestOutputs:
    """AC8 plumbing: GatewayUrl (exported) + GatewayArn outputs for deploy.py to read."""

    def test_gateway_url_output_exported(self, template):
        outputs = template.get("Outputs", {})
        assert "GatewayUrl" in outputs
        assert "Export" in outputs["GatewayUrl"], "GatewayUrl must be exported"

    def test_gateway_arn_output(self, template):
        outputs = template.get("Outputs", {})
        assert "GatewayArn" in outputs


class TestCfnLint:
    """AC9: template passes the repo's cfn-lint gate (same ignore list as CI)."""

    def test_cfn_lint_passes(self):
        if shutil.which("cfn-lint") is None:
            pytest.skip("cfn-lint not installed")
        args = ["cfn-lint", str(TEMPLATE_PATH)]
        for chk in CI_IGNORE_CHECKS:
            args += ["--ignore-checks", chk]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 0, f"cfn-lint failed:\n{result.stdout}\n{result.stderr}"
