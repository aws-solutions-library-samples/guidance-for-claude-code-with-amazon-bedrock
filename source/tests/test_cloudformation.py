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
    """Handle !Sub function (scalar or sequence form)."""
    if node.id == "scalar":
        return {"Fn::Sub": loader.construct_scalar(node)}
    return {"Fn::Sub": loader.construct_sequence(node)}


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


def select_constructor(loader, node):
    """Handle !Select function."""
    return {"Fn::Select": loader.construct_sequence(node)}


def split_constructor(loader, node):
    """Handle !Split function."""
    return {"Fn::Split": loader.construct_sequence(node)}


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
CloudFormationLoader.add_constructor("!Select", select_constructor)
CloudFormationLoader.add_constructor("!Split", split_constructor)


class TestCloudFormationCrossRegion:
    """Tests for CloudFormation template cross-region support."""

    def get_template(self):
        """Load the CloudFormation template."""
        template_path = (
            Path(__file__).parent.parent.parent / "deployment" / "infrastructure" / "cognito-identity-pool.yaml"
        )
        with open(template_path, encoding="utf-8") as f:
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


# Common Okta thumbprint hardcoded in bedrock-auth-okta.yaml — must NOT appear in the generic template
OKTA_HARDCODED_THUMBPRINT = "9e99a48a9960b14926bb7f3b02e22da2b0ab7280"


class TestBedrockAuthGenericTemplate:
    """Tests for bedrock-auth-generic.yaml — covers PingFederate/Keycloak/ForgeRock/etc.

    The template was added to fix a bug where choosing 'Okta (or generic OIDC)' for a
    non-Okta IdP silently applied the Okta template. The generic template must:
      - take the OIDC issuer URL, client ID, and JWKS thumbprint as parameters
      - NOT hardcode the Okta thumbprint
      - NOT contain Okta-specific strings in tags/descriptions
      - emit the same set of outputs as the Okta template (downstream stacks rely on these)
    """

    def get_template(self):
        template_path = (
            Path(__file__).parent.parent.parent / "deployment" / "infrastructure" / "bedrock-auth-generic.yaml"
        )
        with open(template_path, encoding="utf-8") as f:
            return yaml.load(f, Loader=CloudFormationLoader)

    def test_template_loads(self):
        """Template must parse as valid CloudFormation YAML."""
        template = self.get_template()
        assert template["AWSTemplateFormatVersion"] == "2010-09-09"
        assert "Parameters" in template
        assert "Resources" in template
        assert "Outputs" in template

    def test_required_oidc_parameters(self):
        """Must accept issuer URL, client ID, and thumbprint list as parameters."""
        params = self.get_template()["Parameters"]

        assert "OidcIssuerUrl" in params
        assert "OidcClientId" in params
        assert "OidcThumbprintList" in params
        # ThumbprintList must be a CommaDelimitedList — IAM OIDC supports rotation
        assert params["OidcThumbprintList"]["Type"] == "CommaDelimitedList"
        # Issuer URL pattern must require https://
        assert params["OidcIssuerUrl"]["AllowedPattern"].startswith("^https://")

    def test_no_okta_specific_parameters(self):
        """Must not carry over OktaDomain/OktaClientId from the okta template."""
        params = self.get_template()["Parameters"]
        assert "OktaDomain" not in params
        assert "OktaClientId" not in params

    def test_oidc_provider_resource_uses_parameter_thumbprint(self):
        """OIDC provider must reference the parameter, not hardcode a thumbprint."""
        resources = self.get_template()["Resources"]
        assert "OidcProvider" in resources
        oidc_provider = resources["OidcProvider"]
        assert oidc_provider["Type"] == "AWS::IAM::OIDCProvider"

        thumbprint_list = oidc_provider["Properties"]["ThumbprintList"]
        # Must be a !Ref to OidcThumbprintList, not a literal list of hex strings
        assert isinstance(thumbprint_list, dict), f"ThumbprintList must be a !Ref, got literal: {thumbprint_list}"
        assert thumbprint_list.get("Ref") == "OidcThumbprintList"

    def test_no_hardcoded_okta_thumbprint_anywhere(self):
        """The Okta-specific thumbprint constant must not appear anywhere in the template."""
        template = self.get_template()
        # Stringify the entire template to catch the thumbprint regardless of where it sits
        import json

        serialized = json.dumps(template, default=str)
        assert OKTA_HARDCODED_THUMBPRINT not in serialized, (
            f"Okta-specific thumbprint {OKTA_HARDCODED_THUMBPRINT} leaked into generic template"
        )

    def test_no_okta_substring_in_tags_or_descriptions(self):
        """Tags, descriptions, and resource names must not advertise Okta."""
        import json

        template = self.get_template()
        serialized = json.dumps(template, default=str).lower()
        # 'okta' should not appear anywhere — this template is provider-agnostic
        assert "okta" not in serialized, "Generic template still contains 'okta' references"

    def test_outputs_match_okta_template_contract(self):
        """Downstream stacks (monitoring, packaging) consume these outputs by name."""
        outputs = self.get_template()["Outputs"]
        for required_output in (
            "FederationType",
            "OIDCProviderArn",
            "FederatedRoleArn",
            "DirectSTSRoleArn",
            "BedrockRoleArn",
            "IdentityPoolId",
            "BedrockPolicyArn",
            "ConfigurationJson",
        ):
            assert required_output in outputs, f"Missing output: {required_output}"

    def test_configuration_json_marks_provider_type_as_generic(self):
        """The ConfigurationJson output must declare provider_type=generic so downstream
        consumers don't misclassify the deployment."""
        outputs = self.get_template()["Outputs"]
        config_json = outputs["ConfigurationJson"]["Value"]
        # Value is a !If [cond, direct-config-string, cognito-config-string].
        # Both branches are Fn::Sub strings — verify both contain provider_type=generic.
        if_branches = config_json["Fn::If"]
        assert len(if_branches) == 3, "Expected !If [condition, direct, cognito]"
        for branch in if_branches[1:]:
            assert "Fn::Sub" in branch
            sub_string = branch["Fn::Sub"]
            assert '"provider_type": "generic"' in sub_string, f"Expected provider_type=generic in: {sub_string!r}"

    def test_supports_both_federation_modes(self):
        """Template must support both direct STS and Cognito Identity Pool federation."""
        template = self.get_template()

        params = template["Parameters"]
        assert params["FederationType"]["AllowedValues"] == ["direct", "cognito"]

        # Both conditions must exist
        conditions = template["Conditions"]
        assert "UseDirectIAM" in conditions
        assert "UseCognitoIdentity" in conditions

        # Both role variants must exist
        resources = template["Resources"]
        assert "DirectIAMRole" in resources
        assert "CognitoAuthenticatedRole" in resources

    def test_govcloud_partition_aware(self):
        """Cognito service principals must select the GovCloud variant when deployed there."""
        template = self.get_template()
        conditions = template["Conditions"]
        assert "IsGovCloudWest" in conditions
        assert "IsGovCloudEast" in conditions

        # The Cognito role's principal should reference these (verified by string search —
        # the nested !If chain is awkward to traverse but the string presence is sufficient)
        import json

        cognito_role = template["Resources"]["CognitoAuthenticatedRole"]
        serialized = json.dumps(cognito_role, default=str)
        assert "cognito-identity-us-gov.amazonaws.com" in serialized
        assert "cognito-identity.us-gov-east-1.amazonaws.com" in serialized

    def test_bedrock_policy_uses_partition_pseudoparameter(self):
        """ARN construction must use ${AWS::Partition} for multi-partition support."""
        template = self.get_template()
        policy = template["Resources"]["BedrockAccessPolicy"]
        policy_doc = policy["Properties"]["PolicyDocument"]

        # Find any Resource entries — they should contain ${AWS::Partition}, not literal "aws"
        partition_found = False
        for stmt in policy_doc["Statement"]:
            if "Resource" in stmt:
                resources = stmt["Resource"] if isinstance(stmt["Resource"], list) else [stmt["Resource"]]
                for r in resources:
                    if isinstance(r, dict) and "Fn::Sub" in r and "${AWS::Partition}" in r["Fn::Sub"]:
                        partition_found = True
                        break
        assert partition_found, "Bedrock ARNs must use ${AWS::Partition} for GovCloud support"


class TestExistingOIDCProviderReuse:
    """Tests for ExistingOIDCProviderArn parameter across all bedrock-auth-* templates.

    Issue #528: All 6 bedrock-auth templates now support an optional ExistingOIDCProviderArn
    parameter so a second profile sharing an IdP issuer in one AWS account can reuse an
    existing IAM OIDC provider instead of failing with EntityAlreadyExists.

    Verifies:
    1. Parameter exists with proper Type, Default, and AllowedPattern
    2. CreateOIDCProvider condition exists and is properly structured
    3. OIDC provider resource is conditionally created (Condition: CreateOIDCProvider)
    4. All references to the provider ARN use !If [CreateOIDCProvider, !GetAtt, !Ref ExistingOIDCProviderArn]
    5. No bare !GetAtt references remain outside the !If wrapper
    """

    TEMPLATES = [
        ("bedrock-auth-okta.yaml", "OktaOIDCProvider"),
        ("bedrock-auth-azure.yaml", "AzureOIDCProvider"),
        ("bedrock-auth-auth0.yaml", "Auth0OIDCProvider"),
        ("bedrock-auth-generic.yaml", "OidcProvider"),
        ("bedrock-auth-google.yaml", "GoogleOIDCProvider"),
        ("bedrock-auth-cognito-pool.yaml", "CognitoUserPoolOIDCProvider"),
    ]

    def _load_template(self, template_file):
        """Load a CloudFormation template using the CloudFormationLoader."""
        template_path = Path(__file__).parent.parent.parent / "deployment" / "infrastructure" / template_file
        with open(template_path, encoding="utf-8") as f:
            return yaml.load(f, Loader=CloudFormationLoader)

    def _find_bare_getatt_arn(self, node, provider_id):
        """Recursively search for bare !GetAtt [provider_id, Arn] references.

        Returns True if a bare reference is found (NOT wrapped in proper !If structure).
        A proper wrapper is: !If [CreateOIDCProvider, !GetAtt [provider_id, Arn], !Ref ExistingOIDCProviderArn]
        """
        if isinstance(node, dict):
            # Check if this is a !GetAtt that references our provider's Arn
            if "Fn::GetAtt" in node:
                getatt_args = node["Fn::GetAtt"]
                if isinstance(getatt_args, list) and len(getatt_args) == 2:
                    if getatt_args[0] == provider_id and getatt_args[1] == "Arn":
                        # Found a !GetAtt reference - is it wrapped?
                        return True  # Caller needs to verify it's inside proper !If

            # Check if this is a proper !If wrapper
            if "Fn::If" in node:
                if_args = node["Fn::If"]
                if isinstance(if_args, list) and len(if_args) == 3:
                    condition_name = if_args[0]
                    true_branch = if_args[1]
                    false_branch = if_args[2]

                    # If this is the correct !If structure, don't recurse into the true branch
                    # (it's allowed to have !GetAtt there)
                    if condition_name == "CreateOIDCProvider":
                        # Verify false branch is !Ref ExistingOIDCProviderArn
                        if isinstance(false_branch, dict) and false_branch.get("Ref") == "ExistingOIDCProviderArn":
                            # This is a proper wrapper - verify true branch has the !GetAtt
                            if isinstance(true_branch, dict) and "Fn::GetAtt" in true_branch:
                                getatt_args = true_branch["Fn::GetAtt"]
                                if (
                                    isinstance(getatt_args, list)
                                    and len(getatt_args) == 2
                                    and getatt_args[0] == provider_id
                                    and getatt_args[1] == "Arn"
                                ):
                                    # This is wrapped correctly, skip recursing into this subtree
                                    return False
                        # For other !If structures, continue recursing
                        for branch in if_args[1:]:
                            if self._find_bare_getatt_arn(branch, provider_id):
                                return True
                        return False

            # Recurse into dict values
            for value in node.values():
                if self._find_bare_getatt_arn(value, provider_id):
                    return True

        elif isinstance(node, list):
            for item in node:
                if self._find_bare_getatt_arn(item, provider_id):
                    return True

        return False

    def test_existing_oidc_provider_parameter_exists(self):
        """Verify ExistingOIDCProviderArn parameter exists in all templates with correct properties."""
        for template_file, _ in self.TEMPLATES:
            template = self._load_template(template_file)
            params = template.get("Parameters", {})

            assert "ExistingOIDCProviderArn" in params, f"{template_file}: Missing ExistingOIDCProviderArn parameter"

            param = params["ExistingOIDCProviderArn"]
            assert param["Type"] == "String", f"{template_file}: ExistingOIDCProviderArn must be Type: String"
            assert param["Default"] == "", f"{template_file}: ExistingOIDCProviderArn Default must be empty string"
            assert "AllowedPattern" in param, f"{template_file}: ExistingOIDCProviderArn must have AllowedPattern"

            # Verify pattern allows empty or valid IAM OIDC provider ARN
            pattern = param["AllowedPattern"]
            assert "arn:aws" in pattern, f"{template_file}: AllowedPattern must accept ARN format"
            assert "iam" in pattern, f"{template_file}: AllowedPattern must include iam service"
            assert "oidc-provider" in pattern, f"{template_file}: AllowedPattern must include oidc-provider"

    def test_create_oidc_provider_condition_exists(self):
        """Verify CreateOIDCProvider condition exists and has correct structure."""
        for template_file, _ in self.TEMPLATES:
            template = self._load_template(template_file)
            conditions = template.get("Conditions", {})

            assert (
                "CreateOIDCProvider" in conditions
            ), f"{template_file}: Missing CreateOIDCProvider condition"

            condition = conditions["CreateOIDCProvider"]

            # For cognito-pool, condition must be !And [UseDirectIAM, !Equals [ExistingOIDCProviderArn, '']]
            if template_file == "bedrock-auth-cognito-pool.yaml":
                assert "Fn::And" in condition, (
                    f"{template_file}: CreateOIDCProvider must use !And for cognito-pool"
                )
                and_args = condition["Fn::And"]
                assert len(and_args) == 2, f"{template_file}: !And must have 2 conditions"

                # First condition should be !Condition UseDirectIAM
                assert and_args[0] == {"Condition": "UseDirectIAM"}, (
                    f"{template_file}: First condition must be UseDirectIAM"
                )

                # Second condition should be !Equals [!Ref ExistingOIDCProviderArn, '']
                assert "Fn::Equals" in and_args[1], (
                    f"{template_file}: Second condition must be !Equals"
                )
                equals_args = and_args[1]["Fn::Equals"]
                assert equals_args == [{"Ref": "ExistingOIDCProviderArn"}, ""], (
                    f"{template_file}: !Equals must check ExistingOIDCProviderArn == ''"
                )
            else:
                # For all other templates, condition must be !Equals [!Ref ExistingOIDCProviderArn, '']
                assert "Fn::Equals" in condition, f"{template_file}: CreateOIDCProvider must use !Equals"
                equals_args = condition["Fn::Equals"]
                assert equals_args == [{"Ref": "ExistingOIDCProviderArn"}, ""], (
                    f"{template_file}: Condition must check ExistingOIDCProviderArn == ''"
                )

    def test_oidc_provider_resource_has_condition(self):
        """Verify OIDC provider resource has Condition: CreateOIDCProvider."""
        for template_file, provider_id in self.TEMPLATES:
            template = self._load_template(template_file)
            resources = template.get("Resources", {})

            assert provider_id in resources, f"{template_file}: Missing OIDC provider resource {provider_id}"

            resource = resources[provider_id]
            assert resource["Type"] == "AWS::IAM::OIDCProvider", (
                f"{template_file}: {provider_id} must be AWS::IAM::OIDCProvider"
            )
            assert "Condition" in resource, f"{template_file}: {provider_id} must have Condition"
            assert resource["Condition"] == "CreateOIDCProvider", (
                f"{template_file}: {provider_id} Condition must be CreateOIDCProvider"
            )

    def test_direct_iam_role_trust_policy_uses_conditional_arn(self):
        """Verify DirectIAMRole trust policy Principal.Federated uses !If structure."""
        for template_file, provider_id in self.TEMPLATES:
            template = self._load_template(template_file)
            resources = template.get("Resources", {})

            # cognito-pool template only creates OIDC provider in direct mode, so this is especially important
            if "DirectIAMRole" not in resources:
                continue

            role = resources["DirectIAMRole"]
            assume_policy = role["Properties"]["AssumeRolePolicyDocument"]
            statements = assume_policy["Statement"]

            # Find the statement with Federated principal
            federated_stmt = None
            for stmt in statements:
                if "Principal" in stmt and "Federated" in stmt["Principal"]:
                    federated_stmt = stmt
                    break

            assert federated_stmt is not None, f"{template_file}: DirectIAMRole must have Federated principal"

            federated = federated_stmt["Principal"]["Federated"]

            # Must be !If [CreateOIDCProvider, !GetAtt provider.Arn, !Ref ExistingOIDCProviderArn]
            assert isinstance(federated, dict), f"{template_file}: Federated must be a dict (intrinsic function)"
            assert "Fn::If" in federated, f"{template_file}: Federated must use !If"

            if_args = federated["Fn::If"]
            assert len(if_args) == 3, f"{template_file}: !If must have [condition, true, false]"
            assert if_args[0] == "CreateOIDCProvider", (
                f"{template_file}: !If condition must be CreateOIDCProvider"
            )

            # True branch: !GetAtt provider.Arn
            true_branch = if_args[1]
            assert "Fn::GetAtt" in true_branch, f"{template_file}: True branch must be !GetAtt"
            assert true_branch["Fn::GetAtt"] == [provider_id, "Arn"], (
                f"{template_file}: True branch must be !GetAtt {provider_id}.Arn"
            )

            # False branch: !Ref ExistingOIDCProviderArn
            false_branch = if_args[2]
            assert "Ref" in false_branch, f"{template_file}: False branch must be !Ref"
            assert false_branch["Ref"] == "ExistingOIDCProviderArn", (
                f"{template_file}: False branch must be !Ref ExistingOIDCProviderArn"
            )

    def test_cognito_identity_pool_uses_conditional_arn(self):
        """Verify CognitoIdentityPool OpenIdConnectProviderARNs uses !If structure.

        Note: cognito-pool template does NOT have a CognitoIdentityPool resource that references
        the OIDC provider ARN (it uses the User Pool directly), so we skip it.
        """
        for template_file, provider_id in self.TEMPLATES:
            # Skip cognito-pool - it doesn't have CognitoIdentityPool with OpenIdConnectProviderARNs
            if template_file == "bedrock-auth-cognito-pool.yaml":
                continue

            template = self._load_template(template_file)
            resources = template.get("Resources", {})

            if "CognitoIdentityPool" not in resources:
                continue

            pool = resources["CognitoIdentityPool"]
            props = pool["Properties"]

            assert "OpenIdConnectProviderARNs" in props, (
                f"{template_file}: CognitoIdentityPool must have OpenIdConnectProviderARNs"
            )

            arns = props["OpenIdConnectProviderARNs"]
            assert isinstance(arns, list), f"{template_file}: OpenIdConnectProviderARNs must be a list"
            assert len(arns) >= 1, f"{template_file}: OpenIdConnectProviderARNs must have at least one entry"

            # First entry should be the !If structure
            arn_entry = arns[0]
            assert isinstance(arn_entry, dict), f"{template_file}: ARN entry must be a dict (intrinsic function)"
            assert "Fn::If" in arn_entry, f"{template_file}: ARN entry must use !If"

            if_args = arn_entry["Fn::If"]
            assert len(if_args) == 3, f"{template_file}: !If must have [condition, true, false]"
            assert if_args[0] == "CreateOIDCProvider", (
                f"{template_file}: !If condition must be CreateOIDCProvider"
            )

            # True branch: !GetAtt provider.Arn
            true_branch = if_args[1]
            assert "Fn::GetAtt" in true_branch, f"{template_file}: True branch must be !GetAtt"
            assert true_branch["Fn::GetAtt"] == [provider_id, "Arn"], (
                f"{template_file}: True branch must be !GetAtt {provider_id}.Arn"
            )

            # False branch: !Ref ExistingOIDCProviderArn
            false_branch = if_args[2]
            assert "Ref" in false_branch, f"{template_file}: False branch must be !Ref"
            assert false_branch["Ref"] == "ExistingOIDCProviderArn", (
                f"{template_file}: False branch must be !Ref ExistingOIDCProviderArn"
            )

    def test_output_oidc_provider_arn_uses_conditional(self):
        """Verify Outputs.OIDCProviderArn.Value uses !If structure."""
        for template_file, provider_id in self.TEMPLATES:
            template = self._load_template(template_file)
            outputs = template.get("Outputs", {})

            assert "OIDCProviderArn" in outputs, f"{template_file}: Missing OIDCProviderArn output"

            output = outputs["OIDCProviderArn"]
            value = output["Value"]

            # Must be !If [CreateOIDCProvider, !GetAtt provider.Arn, !Ref ExistingOIDCProviderArn]
            assert isinstance(value, dict), f"{template_file}: Output Value must be a dict (intrinsic function)"
            assert "Fn::If" in value, f"{template_file}: Output Value must use !If"

            if_args = value["Fn::If"]
            assert len(if_args) == 3, f"{template_file}: !If must have [condition, true, false]"
            assert if_args[0] == "CreateOIDCProvider", (
                f"{template_file}: !If condition must be CreateOIDCProvider"
            )

            # True branch: !GetAtt provider.Arn
            true_branch = if_args[1]
            assert "Fn::GetAtt" in true_branch, f"{template_file}: True branch must be !GetAtt"
            assert true_branch["Fn::GetAtt"] == [provider_id, "Arn"], (
                f"{template_file}: True branch must be !GetAtt {provider_id}.Arn"
            )

            # False branch: !Ref ExistingOIDCProviderArn
            false_branch = if_args[2]
            assert "Ref" in false_branch, f"{template_file}: False branch must be !Ref"
            assert false_branch["Ref"] == "ExistingOIDCProviderArn", (
                f"{template_file}: False branch must be !Ref ExistingOIDCProviderArn"
            )

    def test_no_bare_getatt_arn_references(self):
        """Verify no bare !GetAtt [provider, Arn] references exist outside proper !If wrappers.

        This is the key falsifiable assertion - ensures ALL references to the provider ARN
        are wrapped in !If [CreateOIDCProvider, !GetAtt, !Ref ExistingOIDCProviderArn].
        """
        for template_file, provider_id in self.TEMPLATES:
            template = self._load_template(template_file)

            # Check specific known locations where provider ARN should be referenced
            resources = template.get("Resources", {})
            outputs = template.get("Outputs", {})

            # Locations to check (these are the critical ones):
            # 1. DirectIAMRole trust policy - already tested above, but verify no bare reference
            # 2. CognitoIdentityPool OpenIdConnectProviderARNs - already tested above
            # 3. Outputs.OIDCProviderArn - already tested above

            # Do a comprehensive scan to ensure no bare references anywhere
            # Start with Resources (excluding the provider resource itself)
            for resource_name, resource in resources.items():
                if resource_name == provider_id:
                    continue  # Skip the provider resource itself

                # Check if this resource has bare GetAtt references
                has_bare = self._find_bare_getatt_arn(resource, provider_id)

                # If we found a GetAtt, verify it's properly wrapped
                if has_bare:
                    # This means we found a !GetAtt reference - need to verify it's wrapped
                    # Re-check with proper wrapping verification
                    import json

                    resource_json = json.dumps(resource, default=str)
                    if (
                        f'"Fn::GetAtt": ["{provider_id}", "Arn"]' in resource_json
                        or f'"Fn::GetAtt": [\\"{provider_id}\\", \\"Arn\\"]' in resource_json
                    ):
                        # Found a GetAtt reference - ensure it's inside a proper If
                        # Check if the full pattern exists
                        if (
                            '"Fn::If": ["CreateOIDCProvider"' not in resource_json
                            or '"Ref": "ExistingOIDCProviderArn"' not in resource_json
                        ):
                            raise AssertionError(
                                f"{template_file}: Found bare !GetAtt {provider_id}.Arn in {resource_name} "
                                f"without proper !If wrapper"
                            )

            # Check Outputs
            for output_name, output in outputs.items():
                has_bare = self._find_bare_getatt_arn(output, provider_id)

                if has_bare:
                    import json

                    output_json = json.dumps(output, default=str)
                    if f'"Fn::GetAtt": ["{provider_id}", "Arn"]' in output_json:
                        if (
                            '"Fn::If": ["CreateOIDCProvider"' not in output_json
                            or '"Ref": "ExistingOIDCProviderArn"' not in output_json
                        ):
                            raise AssertionError(
                                f"{template_file}: Found bare !GetAtt {provider_id}.Arn in output {output_name} "
                                f"without proper !If wrapper"
                            )

    def test_cognito_pool_condition_is_combined(self):
        """Verify bedrock-auth-cognito-pool.yaml has combined condition while others have simple condition.

        cognito-pool: CreateOIDCProvider = !And [UseDirectIAM, !Equals [ExistingOIDCProviderArn, '']]
        others: CreateOIDCProvider = !Equals [ExistingOIDCProviderArn, '']
        """
        for template_file, _ in self.TEMPLATES:
            template = self._load_template(template_file)
            conditions = template.get("Conditions", {})
            condition = conditions["CreateOIDCProvider"]

            if template_file == "bedrock-auth-cognito-pool.yaml":
                # Must be !And with two conditions
                assert "Fn::And" in condition, "cognito-pool CreateOIDCProvider must use !And"
                and_args = condition["Fn::And"]
                assert len(and_args) == 2, "cognito-pool !And must have exactly 2 conditions"

                # Verify first condition is !Condition UseDirectIAM
                assert and_args[0] == {"Condition": "UseDirectIAM"}, (
                    "cognito-pool first condition must be !Condition UseDirectIAM"
                )

                # Verify second condition is !Equals [!Ref ExistingOIDCProviderArn, '']
                assert "Fn::Equals" in and_args[1], (
                    "cognito-pool second condition must be !Equals"
                )
                assert and_args[1]["Fn::Equals"] == [{"Ref": "ExistingOIDCProviderArn"}, ""], (
                    "cognito-pool !Equals must check ExistingOIDCProviderArn == ''"
                )
            else:
                # Must be simple !Equals [!Ref ExistingOIDCProviderArn, '']
                assert "Fn::Equals" in condition, f"{template_file} CreateOIDCProvider must use !Equals"
                assert condition["Fn::Equals"] == [{"Ref": "ExistingOIDCProviderArn"}, ""], (
                    f"{template_file} Condition must check ExistingOIDCProviderArn == ''"
                )
