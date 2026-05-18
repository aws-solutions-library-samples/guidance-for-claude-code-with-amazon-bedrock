"""Cognito Post Confirmation trigger — auto-creates org and adds user as admin."""

import boto3

cognito = boto3.client("cognito-idp")
dynamodb = boto3.resource("dynamodb")
orgs_table = dynamodb.Table("NexusOrganizations")


def lambda_handler(event, context):
    user_pool_id = event["userPoolId"]
    username = event["userName"]
    email = event["request"]["userAttributes"].get("email", "")

    # Derive org name from email domain
    domain = email.split("@")[1] if "@" in email else ""
    org_name = domain.split(".")[0] if domain else ""

    if not org_name:
        return event

    group_name = f"org-{org_name}"

    # Create org group if it doesn't exist
    try:
        cognito.create_group(
            UserPoolId=user_pool_id,
            GroupName=group_name,
            Description=f"{org_name} organization",
        )
        print(f"Created group {group_name}")
    except cognito.exceptions.GroupExistsException:
        print(f"Group {group_name} already exists")
    except Exception as e:
        print(f"Error creating group: {e}")

    # Add user to org group
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName=group_name,
        )
        print(f"Added {email} to {group_name}")
    except Exception as e:
        print(f"Error adding to org group: {e}")

    # Add user to claude-code-admins (org admin)
    try:
        cognito.admin_add_user_to_group(
            UserPoolId=user_pool_id,
            Username=username,
            GroupName="claude-code-admins",
        )
        print(f"Added {email} to claude-code-admins")
    except Exception as e:
        print(f"Error adding to admins: {e}")

    # Create org in NexusOrganizations if it doesn't exist
    try:
        orgs_table.put_item(
            Item={
                "pk": f"ORG#{org_name}",
                "sk": "DETAILS",
                "name": org_name,
                "status": "pending_setup",
                "admin_email": email,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        print(f"Created org {org_name} in NexusOrganizations")
    except Exception:
        # Already exists
        pass

    return event
