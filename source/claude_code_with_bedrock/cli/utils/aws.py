# ABOUTME: AWS utility functions for Claude Code with Bedrock
# ABOUTME: Handles AWS API interactions, stack management, and service checks

"""AWS utilities for CLI commands."""

from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def get_current_region() -> str | None:
    """Get the current AWS region from configuration."""
    try:
        session = boto3.Session()
        return session.region_name or "us-east-1"
    except Exception:
        return "us-east-1"


def check_bedrock_access(region: str) -> bool:
    """Check if Bedrock is accessible in the given region."""
    try:
        client = boto3.client("bedrock", region_name=region)
        # Try to list foundation models
        response = client.list_foundation_models()

        # Check if Claude models are available
        claude_models = [
            model for model in response.get("modelSummaries", []) if "claude" in model.get("modelId", "").lower()
        ]

        return len(claude_models) > 0
    except ClientError as e:
        if e.response["Error"]["Code"] == "AccessDeniedException":
            return False
        return False
    except NoCredentialsError:
        return False
    except Exception:
        return False


def get_bedrock_models(region: str) -> list[dict[str, Any]]:
    """Get available Bedrock models in a region."""
    try:
        client = boto3.client("bedrock", region_name=region)
        response = client.list_foundation_models()

        # Filter for Claude models
        claude_models = [
            {
                "id": model["modelId"],
                "name": model.get("modelName", model["modelId"]),
                "provider": model.get("providerName", "Anthropic"),
            }
            for model in response.get("modelSummaries", [])
            if "claude" in model.get("modelId", "").lower()
        ]

        return claude_models
    except Exception:
        return []


def check_stack_exists(stack_name: str, region: str) -> bool:
    """Check if a CloudFormation stack exists."""
    try:
        client = boto3.client("cloudformation", region_name=region)
        response = client.describe_stacks(StackName=stack_name)

        # Check if stack is in a valid state
        stack = response["Stacks"][0]
        status = stack["StackStatus"]

        # These statuses indicate the stack exists and is usable
        valid_statuses = ["CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"]

        return status in valid_statuses
    except ClientError as e:
        if e.response["Error"]["Code"] == "ValidationError":
            # Stack doesn't exist
            return False
        raise
    except Exception:
        return False


def get_stack_outputs(stack_name: str, region: str) -> dict[str, str]:
    """Get outputs from a CloudFormation stack."""
    try:
        client = boto3.client("cloudformation", region_name=region)
        response = client.describe_stacks(StackName=stack_name)

        stack = response["Stacks"][0]
        outputs = {}

        for output in stack.get("Outputs", []):
            outputs[output["OutputKey"]] = output["OutputValue"]

        return outputs
    except Exception as e:
        print(f"Error getting stack outputs: {e}")
        return {}


def get_account_id() -> str | None:
    """Get the current AWS account ID."""
    try:
        client = boto3.client("sts")
        response = client.get_caller_identity()
        return response["Account"]
    except Exception:
        return None


def validate_iam_permissions() -> dict[str, bool]:
    """Validate required IAM permissions."""
    permissions = {}

    # Check CloudFormation permissions
    try:
        client = boto3.client("cloudformation")
        client.list_stacks(StackStatusFilter=["CREATE_COMPLETE"])
        permissions["cloudformation"] = True
    except Exception:
        permissions["cloudformation"] = False

    # Check IAM permissions
    try:
        client = boto3.client("iam")
        client.list_roles(MaxItems=1)
        permissions["iam"] = True
    except Exception:
        permissions["iam"] = False

    # Check Cognito permissions
    try:
        client = boto3.client("cognito-identity")
        client.list_identity_pools(MaxResults=1)
        permissions["cognito"] = True
    except Exception:
        permissions["cognito"] = False

    return permissions


def get_vpcs(region: str) -> list[dict[str, Any]]:
    """Get list of VPCs in a region."""
    try:
        client = boto3.client("ec2", region_name=region)
        response = client.describe_vpcs()

        vpcs = []
        for vpc in response.get("Vpcs", []):
            vpc_info = {
                "id": vpc["VpcId"],
                "cidr": vpc["CidrBlock"],
                "is_default": vpc.get("IsDefault", False),
                "name": "",
                "state": vpc["State"],
            }

            # Get VPC name from tags
            for tag in vpc.get("Tags", []):
                if tag["Key"] == "Name":
                    vpc_info["name"] = tag["Value"]
                    break

            vpcs.append(vpc_info)

        # Sort by name, with default VPC first
        vpcs.sort(key=lambda x: (not x["is_default"], x["name"]))
        return vpcs

    except Exception:
        return []


def get_subnets(region: str, vpc_id: str) -> list[dict[str, Any]]:
    """Get list of subnets in a VPC."""
    try:
        client = boto3.client("ec2", region_name=region)
        response = client.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])

        subnets = []
        for subnet in response.get("Subnets", []):
            subnet_info = {
                "id": subnet["SubnetId"],
                "cidr": subnet["CidrBlock"],
                "availability_zone": subnet["AvailabilityZone"],
                "available_ips": subnet["AvailableIpAddressCount"],
                "name": "",
                "is_public": subnet.get("MapPublicIpOnLaunch", False),
            }

            # Get subnet name from tags
            for tag in subnet.get("Tags", []):
                if tag["Key"] == "Name":
                    subnet_info["name"] = tag["Value"]
                    break

            subnets.append(subnet_info)

        # Sort by availability zone
        subnets.sort(key=lambda x: x["availability_zone"])
        return subnets

    except Exception:
        return []


def detect_cognito_stack(region: str) -> dict[str, Any] | None:
    """
    Detect if cognito-user-pool-setup stack is deployed.
    Returns stack info with outputs if found, None otherwise.

    Searches for CloudFormation stacks matching common Cognito naming patterns
    and validates they have distribution support (DistributionWebClientId output).
    """
    try:
        client = boto3.client("cloudformation", region_name=region)

        # Search for stacks with known naming patterns
        response = client.list_stacks(StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"])

        cognito_stacks = []
        for stack in response.get("StackSummaries", []):
            stack_name = stack["StackName"]
            # Look for Cognito User Pool stacks (flexible naming: "userpool" or "cognito")
            stack_lower = stack_name.lower()
            if "userpool" in stack_lower or "cognito" in stack_lower:
                cognito_stacks.append(stack_name)

        if not cognito_stacks:
            return None

        # Check which stack has DistributionWebClient output
        for stack_name in cognito_stacks:
            outputs = get_stack_outputs(stack_name, region)
            if "DistributionWebClientId" in outputs and "DistributionWebClientSecretArn" in outputs:
                return {"stack_name": stack_name, "outputs": outputs}

        return None

    except ClientError as e:
        # Gracefully handle permission errors
        if e.response["Error"]["Code"] == "AccessDenied":
            return None
        return None
    except Exception:
        return None


def validate_cognito_stack_for_distribution(stack_name: str, region: str) -> tuple[bool, str]:
    """
    Validate that Cognito stack has required resources for distribution.
    Returns (is_valid, message).

    Checks for presence of all required CloudFormation outputs:
    - UserPoolId
    - DistributionWebClientId
    - UserPoolDomain
    - DistributionWebClientSecretArn
    """
    try:
        outputs = get_stack_outputs(stack_name, region)

        required_outputs = [
            "UserPoolId",
            "DistributionWebClientId",
            "UserPoolDomain",
            "DistributionWebClientSecretArn",
        ]

        missing = [out for out in required_outputs if out not in outputs]

        if missing:
            return (
                False,
                f"Stack is missing outputs: {', '.join(missing)}. Please update to latest cognito-user-pool-setup.yaml \
                template.",
            )

        return True, "Stack has all required outputs for distribution"

    except ClientError as e:
        return False, f"Error accessing stack: {e.response['Error']['Message']}"
    except Exception as e:
        return False, f"Error validating stack: {str(e)}"


def detect_all_cognito_stacks(region: str) -> list[dict[str, Any]]:
    """
    Detect all Cognito User Pool stacks in the region.
    Returns list of stack info dicts with stack_name and outputs.

    Useful when multiple Cognito stacks exist and user needs to choose.
    """
    try:
        client = boto3.client("cloudformation", region_name=region)

        # Search for stacks with known naming patterns
        response = client.list_stacks(StackStatusFilter=["CREATE_COMPLETE", "UPDATE_COMPLETE"])

        cognito_stacks = []
        for stack in response.get("StackSummaries", []):
            stack_name = stack["StackName"]
            # Look for Cognito User Pool stacks (flexible naming: "userpool" or "cognito")
            stack_lower = stack_name.lower()
            if "userpool" in stack_lower or "cognito" in stack_lower:
                try:
                    outputs = get_stack_outputs(stack_name, region)
                    cognito_stacks.append({"stack_name": stack_name, "outputs": outputs})
                except Exception:
                    # Skip stacks we can't access
                    continue

        return cognito_stacks

    except ClientError:
        return []
    except Exception:
        return []
