# ABOUTME: Tests for CloudFormation template cross-region configuration
# ABOUTME: Validates IAM policies support cross-region inference properly

"""Tests for CloudFormation template configuration."""

from pathlib import Path

import yaml


# Custom YAML loader for CloudFormation templates
class CloudFormationLoader(yaml.SafeLoader):
    """Custom YAML loader that handles CloudFormation intrinsic functions."""

    pass


# Define constructors for CloudFormation intrinsic functions
def ref_constructor(loader, node):
    """Handle !Ref function."""
    return {"Ref": loader.construct_scalar(node)}


def getatt_constructor(loader, node):
    """Handle !GetAtt function."""
    if isinstance(node, yaml.SequenceNode):
        return {"Fn::GetAtt": loader.construct_sequence(node)}
    else:
        # Handle dot notation
        value = loader.construct_scalar(node)
        return {"Fn::GetAtt": value.split(".", 1)}


def sub_constructor(loader, node):
    """Handle !Sub function."""
    return {"Fn::Sub": loader.construct_scalar(node)}


def if_constructor(loader, node):
    """Handle !If function."""
    return {"Fn::If": loader.construct_sequence(node)}


def join_constructor(loader, node):
    """Handle !Join function."""
    return {"Fn::Join": loader.construct_sequence(node)}


def equals_constructor(loader, node):
    """Handle !Equals function."""
    return {"Fn::Equals": loader.construct_sequence(node)}


def or_constructor(loader, node):
    """Handle !Or function."""
    return {"Fn::Or": loader.construct_sequence(node)}


def and_constructor(loader, node):
    """Handle !And function."""
    return {"Fn::And": loader.construct_sequence(node)}


def not_constructor(loader, node):
    """Handle !Not function."""
    return {"Fn::Not": loader.construct_sequence(node)}


def condition_constructor(loader, node):
    """Handle !Condition function."""
    return {"Condition": loader.construct_scalar(node)}


# Register the constructors
CloudFormationLoader.add_constructor("!Ref", ref_constructor)
CloudFormationLoader.add_constructor("!GetAtt", getatt_constructor)
CloudFormationLoader.add_constructor("!Sub", sub_constructor)
CloudFormationLoader.add_constructor("!If", if_constructor)
CloudFormationLoader.add_constructor("!Join", join_constructor)
CloudFormationLoader.add_constructor("!Equals", equals_constructor)
CloudFormationLoader.add_constructor("!Or", or_constructor)
CloudFormationLoader.add_constructor("!And", and_constructor)
CloudFormationLoader.add_constructor("!Not", not_constructor)
CloudFormationLoader.add_constructor("!Condition", condition_constructor)


class TestCloudFormationCrossRegion:
    """Tests for CloudFormation template cross-region support."""

    def get_template(self):
        """Load the CloudFormation template."""
        template_path = (
            Path(__file__).parent.parent.parent / "deployment" / "infrastructure" / "cognito-identity-pool.yaml"
        )
        with open(template_path) as f:
            return yaml.load(f, Loader=CloudFormationLoader)

    def test_allowed_bedrock_regions_default(self):
        """Test that default AllowedBedrockRegions includes all US cross-region regions."""
        template = self.get_template()

        # Check parameters
        params = template.get("Parameters", {})
        assert "AllowedBedrockRegions" in params

        bedrock_regions_param = params["AllowedBedrockRegions"]
        assert bedrock_regions_param["Type"] == "CommaDelimitedList"

        # Check default value includes all US regions for cross-region
        default_regions = bedrock_regions_param.get("Default", "")
        assert "us-east-1" in default_regions
        assert "us-east-2" in default_regions
        assert "us-west-2" in default_regions

    def test_iam_policy_allows_cross_region_resources(self):
        """Test that IAM policy allows cross-region inference resources."""
        template = self.get_template()

        # Find the BedrockAccessPolicy
        resources = template.get("Resources", {})
        assert "BedrockAccessPolicy" in resources

        policy = resources["BedrockAccessPolicy"]
        assert policy["Type"] == "AWS::IAM::ManagedPolicy"

        # Check policy document
        policy_doc = policy["Properties"]["PolicyDocument"]
        statements = policy_doc["Statement"]

        # Find the AllowBedrockInvoke statement
        invoke_statement = None
        for stmt in statements:
            if stmt.get("Sid") == "AllowBedrockInvoke":
                invoke_statement = stmt
                break

        assert invoke_statement is not None

        # Check resources include cross-region patterns
        resources_allowed = invoke_statement["Resource"]
        assert isinstance(resources_allowed, list)

        # Extract actual resource strings from Fn::Sub or plain strings
        resource_strings = []
        for r in resources_allowed:
            if isinstance(r, dict) and "Fn::Sub" in r:
                resource_strings.append(r["Fn::Sub"])
            elif isinstance(r, str):
                resource_strings.append(r)

        # Should allow foundation models (cross-region)
        assert any("foundation-model" in r for r in resource_strings)

        # Should allow inference profiles
        assert any("inference-profile" in r for r in resource_strings)

        # Check ARN patterns for cross-region (double colon between region and account)
        assert any("*::foundation-model" in r for r in resource_strings)

    def test_iam_policy_has_region_condition(self):
        """Test that IAM policy has region condition for security."""
        template = self.get_template()

        resources = template.get("Resources", {})
        policy = resources["BedrockAccessPolicy"]
        policy_doc = policy["Properties"]["PolicyDocument"]
        statements = policy_doc["Statement"]

        # Find the AllowBedrockInvoke statement
        for stmt in statements:
            if stmt.get("Sid") == "AllowBedrockInvoke":
                # Should have a condition
                assert "Condition" in stmt

                condition = stmt["Condition"]
                assert "StringEquals" in condition

                # Should check aws:RequestedRegion
                string_equals = condition["StringEquals"]
                assert "aws:RequestedRegion" in string_equals

                # The value should reference the AllowedBedrockRegions parameter
                region_ref = string_equals["aws:RequestedRegion"]
                # Check if it's a Ref to AllowedBedrockRegions
                assert isinstance(region_ref, dict)
                assert "Ref" in region_ref
                assert region_ref["Ref"] == "AllowedBedrockRegions"
                break

    def test_bedrock_access_role_configuration(self):
        """Test that the BedrockAccessRole is properly configured."""
        template = self.get_template()

        resources = template.get("Resources", {})
        assert "BedrockAccessRole" in resources

        role = resources["BedrockAccessRole"]
        assert role["Type"] == "AWS::IAM::Role"

        # Check it references the BedrockAccessPolicy
        policy_arns = role["Properties"]["ManagedPolicyArns"]
        # Look for the reference to BedrockAccessPolicy
        found_policy_ref = False
        for arn in policy_arns:
            if isinstance(arn, dict) and "Ref" in arn and arn["Ref"] == "BedrockAccessPolicy":
                found_policy_ref = True
                break
        assert found_policy_ref, "BedrockAccessPolicy not referenced in ManagedPolicyArns"

        # Check assume role policy for Cognito
        assume_policy = role["Properties"]["AssumeRolePolicyDocument"]
        statements = assume_policy["Statement"]

        assert len(statements) > 0
        assume_stmt = statements[0]

        # Should allow Cognito Identity to assume
        # The federated principal may be a string or a conditional (Fn::If) for GovCloud
        federated = assume_stmt["Principal"]["Federated"]
        if isinstance(federated, dict) and "Fn::If" in federated:
            # It's a conditional - verify it includes cognito-identity endpoints
            assert "cognito-identity" in str(federated)
        else:
            # It's a plain string
            assert federated == "cognito-identity.amazonaws.com"

        assert "sts:AssumeRoleWithWebIdentity" in assume_stmt["Action"]

    def test_template_description_mentions_cross_region(self):
        """Test that template description or comments mention cross-region inference."""
        template = self.get_template()

        # Check if Parameters description mentions cross-region
        params = template.get("Parameters", {})
        bedrock_param = params.get("AllowedBedrockRegions", {})
        description = bedrock_param.get("Description", "")

        # Should mention cross-region or multiple regions
        assert "cross-region" in description.lower() or "regions" in description.lower()

    def test_outputs_include_identity_pool(self):
        """Test that outputs include the Identity Pool ID."""
        template = self.get_template()

        outputs = template.get("Outputs", {})
        assert "IdentityPoolId" in outputs

        pool_output = outputs["IdentityPoolId"]
        # Check if Value is a Ref to BedrockIdentityPool
        value = pool_output["Value"]
        assert isinstance(value, dict)
        assert "Ref" in value
        assert value["Ref"] == "BedrockIdentityPool"
