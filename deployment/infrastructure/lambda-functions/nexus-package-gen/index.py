"""Generate org-specific installer package after provisioning."""

import json
import io
import zipfile
import boto3
import os

DISTRIBUTION_BUCKET = os.environ.get("DISTRIBUTION_BUCKET", "claude-code-auth-distribution-916587687563")
REGION = os.environ.get("AWS_REGION", "us-east-1")

s3 = boto3.client("s3")
sts = boto3.client("sts")
dynamodb = boto3.resource("dynamodb")
orgs_table = dynamodb.Table("NexusOrganizations")


def generate_org_package(org_id, org_data):
    """Generate installer package for an org and upload to S3."""
    region = org_data.get("region", "us-east-1")

    # Get Cognito details from org record (stored during Setup Guide)
    user_pool_id = org_data.get("user_pool_id", "")
    client_id = org_data.get("client_id", "")
    provider_domain = org_data.get("provider_domain", "")

    if not user_pool_id or not client_id:
        print(f"Missing Cognito info for {org_id}")
        return False

    # Generate config.json for this org
    config = {
        org_id: {
            "provider_domain": provider_domain,
            "client_id": client_id,
            "aws_region": region,
            "provider_type": "cognito",
            "credential_storage": "keyring",
            "cross_region_profile": "us",
            "federation_type": "cognito",
            "cognito_user_pool_id": user_pool_id,
            "selected_model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        }
    }

    # For each platform, create a zip with the config + binary
    for platform in ["mac", "linux", "windows"]:
        create_platform_package(org_id, platform, config)

    # Update org status
    orgs_table.update_item(
        Key={"pk": f"ORG#{org_id}", "sk": "DETAILS"},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "active"},
    )
    return True


def get_customer_cognito_info(role_arn, region):
    """Assume connector role and get Cognito details from customer's stack."""
    try:
        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName="nexus-package-gen")["Credentials"]
        remote = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
        cf = remote.client("cloudformation")
        stack = cf.describe_stacks(StackName="allcode-nexus")["Stacks"][0]
        outputs = {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}
        return {
            "user_pool_id": outputs.get("UserPoolId", ""),
            "client_id": outputs.get("ClientId", ""),
            "domain": outputs.get("ProviderDomain", ""),
            "identity_pool_id": outputs.get("IdentityPoolId", ""),
        }
    except Exception as e:
        print(f"Failed to get Cognito info: {e}")
        return None


def create_platform_package(org_id, platform, config):
    """Create a zip package for a platform with config + binary from base packages."""
    try:
        # Download the base package for this platform
        base_key = f"packages/{platform}/latest.zip"
        base_obj = s3.get_object(Bucket=DISTRIBUTION_BUCKET, Key=base_key)
        base_zip_data = base_obj["Body"].read()

        # Create new zip with updated config
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(base_zip_data), "r") as base_zip:
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as new_zip:
                for item in base_zip.namelist():
                    if item.endswith("config.json"):
                        # Replace config with org-specific one
                        new_zip.writestr(item, json.dumps(config, indent=2))
                    else:
                        new_zip.writestr(item, base_zip.read(item))

        # Upload org-specific package
        output.seek(0)
        s3.put_object(
            Bucket=DISTRIBUTION_BUCKET,
            Key=f"packages/{org_id}/{platform}/latest.zip",
            Body=output.read(),
        )
        print(f"Uploaded {platform} package for {org_id}")
    except Exception as e:
        print(f"Failed to create {platform} package for {org_id}: {e}")


def lambda_handler(event, context):
    """Called after org provisioning to generate packages."""
    org_id = event.get("org_id", "")
    if not org_id:
        return {"status": "error", "message": "missing org_id"}

    # Get org data
    result = orgs_table.get_item(Key={"pk": f"ORG#{org_id}", "sk": "DETAILS"})
    org_data = result.get("Item", {})
    if not org_data:
        return {"status": "error", "message": "org not found"}

    success = generate_org_package(org_id, org_data)
    return {"status": "success" if success else "error"}
