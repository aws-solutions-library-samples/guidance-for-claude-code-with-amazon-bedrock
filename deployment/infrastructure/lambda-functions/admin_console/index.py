# ABOUTME: Admin console Lambda for the IAM Identity Center landing page.
# ABOUTME: Manages group->model->permission-set mappings and generates MDM/bootstrap configs.

"""Admin console for the IAM Identity Center (IDC) landing page.

Sits behind the SAME ALB as the landing page (landing-page-distribution.yaml),
attached via a separate /admin* listener rule (see admin-console.yaml) so
authentication is handled entirely by the ALB's native `authenticate-oidc`
listener action — this Lambda never sees raw credentials or mints its own
session cookies. ALB validates the JWT and forwards the decoded claims via
the x-amzn-oidc-data header (base64 JWT payload, unverified re-decode here is
safe because the ALB has already checked the signature before invoking us).

Authorization is a SEPARATE, additional check on top of that authentication:
every request re-resolves the caller's IAM Identity Center group memberships
live (never trusted from a token claim) and requires membership in
ADMIN_GROUP. This matches the pattern used by the original CDK-based
implementation (deployment/idc-landing-page/lambda/index.py).
"""

import base64
import hashlib
import hmac
import html
import json
import os
import time
import urllib.parse
import uuid
from urllib.parse import unquote

import boto3
from shared.mdm_config import add_bootstrap_config, add_mcp_servers, add_policies, build_inference_models
from shared.mdm_generators import generate_mobileconfig, generate_reg_file

BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
IDC_INSTANCE_ARN = os.environ["IDC_INSTANCE_ARN"]
ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "Claude-Code-Admins")
BASE_URL = os.environ["BASE_URL"]
# Optional extra Origin/Referer values accepted on admin POST requests, on
# top of BASE_URL (see verify_request_origin) — needed for SSM-tunnel/VPN
# access to an internal-scheme ALB whose hostname differs from BASE_URL.
ADDITIONAL_TRUSTED_ORIGINS = [o.rstrip("/") for o in os.environ.get("ADDITIONAL_TRUSTED_ORIGINS", "").split(",") if o]
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Bootstrap OIDC (Claude Desktop's /api/bootstrap flow) — see
# landing-page-distribution.yaml's IdcBootstrapUserPoolClient. Empty when the
# distribution stack predates this feature or bootstrap is otherwise
# disabled; generated MDM files then fall back to bootstrapUrl-only (no
# bootstrapOidc), which Claude Desktop treats as "no dynamic config".
IDC_BOOTSTRAP_CLIENT_ID = os.environ.get("IDC_BOOTSTRAP_CLIENT_ID", "")
IDC_BOOTSTRAP_ISSUER = os.environ.get("IDC_BOOTSTRAP_ISSUER", "")
IDC_BOOTSTRAP_REDIRECT_PORT = os.environ.get("IDC_BOOTSTRAP_REDIRECT_PORT", "")
# IAM Identity Center data (permission sets, groups, users) is only ever
# stored in the region IDC was enabled in, regardless of where this Lambda
# itself runs. IDC_REGION defaults to this function's own region (the common
# case) but must be set explicitly when the admin console is deployed in a
# different region than IDC's home region.
IDC_REGION = os.environ.get("IDC_REGION", REGION)

# CloudFront-in-front-of-internal-ALB mode (see admin-console.yaml's
# EnableCloudFront). Requests arrive via CloudFront's forward-only HTTP
# listener with NO ALB-set x-amzn-oidc-data header, so identity comes from
# the shared session cookie the landing page's /callback set (same CloudFront
# domain, same Cognito client, same signing secret). Unauthenticated callers
# are redirected to Cognito login with redirect_uri pointing back at the
# landing page's /callback (already a registered callback URL) — the admin
# console never does its own code exchange.
ENABLE_CLOUDFRONT = os.environ.get("ENABLE_CLOUDFRONT", "false") == "true"
CLOUDFRONT_DOMAIN = os.environ.get("CLOUDFRONT_DOMAIN", "")
SELF_COGNITO_DOMAIN = os.environ.get("SELF_COGNITO_DOMAIN", "")
SELF_COGNITO_CLIENT_ID = os.environ.get("SELF_COGNITO_CLIENT_ID", "")
SESSION_SIGNING_SECRET_ARN = os.environ.get("SESSION_SIGNING_SECRET_ARN", "")

s3_client = boto3.client("s3")
_secretsmanager_client = boto3.client("secretsmanager") if ENABLE_CLOUDFRONT else None
_session_signing_secret_cache = None


def _get_session_signing_secret():
    """Fetch (and cache) the shared HMAC key used to validate the landing
    page's session cookie. Same secret the landing page signs with."""
    global _session_signing_secret_cache
    if _session_signing_secret_cache is None:
        if not SESSION_SIGNING_SECRET_ARN:
            raise RuntimeError("SESSION_SIGNING_SECRET_ARN is not configured")
        resp = _secretsmanager_client.get_secret_value(SecretId=SESSION_SIGNING_SECRET_ARN)
        secret_dict = json.loads(resp["SecretString"])
        _session_signing_secret_cache = secret_dict["key"].encode("utf-8")
    return _session_signing_secret_cache


def _sign(payload_b64: str) -> str:
    key = _get_session_signing_secret()
    digest = hmac.new(key, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _parse_cookies(cookie_header: str) -> dict:
    cookies = {}
    if cookie_header:
        for item in cookie_header.split(";"):
            if "=" in item:
                k, v = item.strip().split("=", 1)
                cookies[k] = v
    return cookies


def validate_session(session_token: str):
    """Verify the landing page's HMAC-signed session token. Returns the
    decoded payload if valid and unexpired, else None."""
    if not session_token:
        return None
    try:
        payload_b64, signature_b64 = session_token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature_b64, _sign(payload_b64)):
        return None
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        session_data = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return None
    if session_data.get("exp", 0) < time.time():
        return None
    return session_data


def redirect_to_login():
    """Redirect an unauthenticated CloudFront request to Cognito login. The
    redirect_uri is the landing page's /callback (already a registered
    callback URL); after login it sets the shared session cookie domain-wide
    and the user can return to /admin."""
    base_url = f"https://{CLOUDFRONT_DOMAIN}"
    login_url = (
        f"https://{SELF_COGNITO_DOMAIN}/login?"
        f"client_id={SELF_COGNITO_CLIENT_ID}&"
        f"response_type=code&"
        f"scope=openid+email+profile&"
        f"redirect_uri={urllib.parse.quote(base_url + '/callback')}"
    )
    return {"statusCode": 302, "headers": {"Location": login_url}, "body": ""}
bedrock_client = boto3.client("bedrock")
sso_admin_client = boto3.client("sso-admin", region_name=IDC_REGION)
identity_store_client = boto3.client("identitystore", region_name=IDC_REGION)
sts_client = boto3.client("sts")

DEPRECATED_MODEL_PATTERNS = (
    "claude-v1",
    "claude-v2",
    "claude-instant",
    "claude-2.0",
    "claude-2.1",
    "claude-3-sonnet-20240229",
    "claude-3-haiku-20240307",
    "claude-3-opus-20240229",
)


# =============================================================================
# Response / logging helpers
# =============================================================================


def json_response(data: dict, status_code: int = 200) -> dict:
    return {
        "statusCode": status_code,
        "statusDescription": f"{status_code} {'OK' if status_code < 400 else 'Error'}",
        "isBase64Encoded": False,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data),
    }


def html_response(body: str, status_code: int = 200) -> dict:
    return {
        "statusCode": status_code,
        "statusDescription": f"{status_code} {'OK' if status_code < 400 else 'Error'}",
        "isBase64Encoded": False,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": body,
    }


def internal_error_response() -> dict:
    """Never leak internal exception detail (ARNs, bucket names, IAM errors)
    to the caller — full detail belongs in CloudWatch logs via print()."""
    return json_response({"error": "An internal error occurred. Please try again later."}, 500)


def log_safe(value) -> str:
    """Strip newlines before logging attacker/user-controlled strings, so a
    crafted email/name claim can't inject fake CloudWatch log lines."""
    return str(value).replace("\n", " ").replace("\r", " ")


# =============================================================================
# Auth: identity from ALB OIDC headers, authorization via live IDC lookup
# =============================================================================


def extract_user_email(headers: dict) -> str:
    """Decode the email claim from the ALB-validated OIDC JWT payload.

    The ALB (authenticate-oidc listener action) has already verified this
    JWT's signature/expiry before invoking the Lambda — decoding the payload
    here without re-checking the signature is safe specifically because it
    arrives via the trusted x-amzn-oidc-data header set by the ALB itself,
    not from client-controlled input.
    """
    oidc_data = headers.get("x-amzn-oidc-data", headers.get("X-Amzn-Oidc-Data", ""))
    if not oidc_data:
        return ""
    try:
        parts = oidc_data.split(".")
        if len(parts) != 3:
            return ""
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.b64decode(payload_b64))
        return payload.get("email") or payload.get("preferred_username") or payload.get("upn") or ""
    except Exception:
        return ""


def verify_request_origin(headers: dict) -> bool:
    """CSRF defense-in-depth: require a state-changing request's Origin (or
    Referer fallback) header to match BASE_URL, or one of
    ADDITIONAL_TRUSTED_ORIGINS (see admin-console.yaml's
    AdditionalTrustedOrigins parameter — needed for SSM-tunnel/VPN access to
    an internal-scheme ALB). Fails closed if neither header is present.

    In CloudFront mode the admin console is reached at https://CLOUDFRONT_DOMAIN
    (not BASE_URL's custom domain), so that origin is trusted too."""
    allowed = [BASE_URL.rstrip("/")] + ADDITIONAL_TRUSTED_ORIGINS
    if ENABLE_CLOUDFRONT and CLOUDFRONT_DOMAIN:
        allowed.append(f"https://{CLOUDFRONT_DOMAIN}")
    origin = headers.get("origin", headers.get("Origin", ""))
    if not origin:
        origin = headers.get("referer", headers.get("Referer", ""))
    if not origin:
        return False
    origin = origin.rstrip("/")
    return any(origin == expected or origin.startswith(expected + "/") for expected in allowed)


def get_user_idc_groups(email: str) -> list[str]:
    """Live lookup of a user's IAM Identity Center group display names.

    Never cached, never trusted from a token claim — every admin request
    re-resolves this from the Identity Store directly.
    """
    if not email:
        return []
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get("Instances"):
            print("No IDC instances found")
            return []
        identity_store_id = instances["Instances"][0]["IdentityStoreId"]

        username = email.split("@")[0] if "@" in email else email
        users = identity_store_client.list_users(
            IdentityStoreId=identity_store_id,
            Filters=[{"AttributePath": "UserName", "AttributeValue": username}],
        )
        if not users.get("Users"):
            users = identity_store_client.list_users(
                IdentityStoreId=identity_store_id,
                Filters=[{"AttributePath": "UserName", "AttributeValue": email}],
            )
        if not users.get("Users"):
            print(f"No IDC user found for {log_safe(email)}")
            return []

        user_id = users["Users"][0]["UserId"]
        memberships = identity_store_client.list_group_memberships_for_member(
            IdentityStoreId=identity_store_id, MemberId={"UserId": user_id}
        )
        groups = []
        for membership in memberships.get("GroupMemberships", []):
            try:
                group = identity_store_client.describe_group(
                    IdentityStoreId=identity_store_id, GroupId=membership["GroupId"]
                )
                groups.append(group["DisplayName"])
            except Exception:
                pass
        return groups
    except Exception as e:
        print(f"Error getting IDC groups: {e}")
        return []


def group_name_to_config_key(group_name: str) -> str:
    """ "Claude-Code-Developers" -> "developer" (matches the landing page's
    matching heuristic in list_config_groups / bootstrap lookup)."""
    config_key = (
        group_name.lower().replace("claude-code-", "").replace("claude-", "").replace(" ", "-").replace("_", "-")
    )
    if config_key.endswith("s") and len(config_key) > 3:
        config_key = config_key[:-1]
    return config_key


# =============================================================================
# Admin API: groups / models / permission sets
# =============================================================================


def api_list_groups() -> dict:
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get("Instances"):
            return json_response({"error": "No IDC instance found"}, 404)
        identity_store_id = instances["Instances"][0]["IdentityStoreId"]

        groups = []
        paginator = identity_store_client.get_paginator("list_groups")
        for page in paginator.paginate(IdentityStoreId=identity_store_id):
            for group in page.get("Groups", []):
                if "claude" in group["DisplayName"].lower():
                    groups.append(
                        {
                            "groupId": group["GroupId"],
                            "displayName": group["DisplayName"],
                            "description": group.get("Description", ""),
                        }
                    )
        return json_response({"groups": groups})
    except Exception as e:
        print(f"Error listing groups: {e}")
        return internal_error_response()


def _is_deprecated_model(model_id: str) -> bool:
    model_lower = model_id.lower()
    return any(pattern in model_lower for pattern in DEPRECATED_MODEL_PATTERNS)


def api_list_models() -> dict:
    try:
        models = []
        profiles_response = bedrock_client.list_inference_profiles()
        for profile in profiles_response.get("inferenceProfileSummaries", []):
            profile_id = profile.get("inferenceProfileId", "")
            profile_name = profile.get("inferenceProfileName", "")
            status = profile.get("status", "ACTIVE")
            if (
                ("claude" in profile_id.lower() or "anthropic" in profile_id.lower())
                and not _is_deprecated_model(profile_id)
                and status == "ACTIVE"
            ):
                models.append(
                    {"modelId": profile_id, "modelName": profile_name, "type": "inference-profile", "status": status}
                )
        models.sort(key=lambda m: m["modelName"])
        return json_response({"models": models})
    except Exception as e:
        print(f"Error listing models: {e}")
        return internal_error_response()


def api_list_permission_sets() -> dict:
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get("Instances"):
            return json_response({"error": "No IDC instance found"}, 404)
        instance_arn = instances["Instances"][0]["InstanceArn"]
        identity_store_id = instances["Instances"][0]["IdentityStoreId"]
        account_id = sts_client.get_caller_identity()["Account"]

        permission_sets = []
        paginator = sso_admin_client.get_paginator("list_permission_sets")
        for page in paginator.paginate(InstanceArn=instance_arn):
            for ps_arn in page.get("PermissionSets", []):
                try:
                    ps = sso_admin_client.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=ps_arn)
                    ps_info = ps["PermissionSet"]

                    assigned_groups = []
                    try:
                        assignments = sso_admin_client.list_account_assignments(
                            InstanceArn=instance_arn, AccountId=account_id, PermissionSetArn=ps_arn
                        )
                        for assignment in assignments.get("AccountAssignments", []):
                            if assignment.get("PrincipalType") == "GROUP":
                                group_id = assignment.get("PrincipalId")
                                try:
                                    group = identity_store_client.describe_group(
                                        IdentityStoreId=identity_store_id, GroupId=group_id
                                    )
                                    assigned_groups.append(
                                        {"groupId": group_id, "groupName": group.get("DisplayName", "")}
                                    )
                                except Exception:
                                    pass
                    except Exception as e:
                        print(f"Error getting assignments for {ps_arn}: {e}")

                    model_resources = []
                    try:
                        policy_response = sso_admin_client.get_inline_policy_for_permission_set(
                            InstanceArn=instance_arn, PermissionSetArn=ps_arn
                        )
                        if policy_response.get("InlinePolicy"):
                            policy = json.loads(policy_response["InlinePolicy"])
                            for stmt in policy.get("Statement", []):
                                if stmt.get("Sid") == "AllowBedrockModel":
                                    resources = stmt.get("Resource", [])
                                    model_resources = [resources] if isinstance(resources, str) else resources
                    except Exception:
                        pass

                    permission_sets.append(
                        {
                            "arn": ps_arn,
                            "name": ps_info.get("Name", ""),
                            "description": ps_info.get("Description", ""),
                            "sessionDuration": ps_info.get("SessionDuration", "PT1H"),
                            "assignedGroups": assigned_groups,
                            "modelResources": model_resources,
                        }
                    )
                except Exception as e:
                    print(f"Error describing permission set {ps_arn}: {e}")

        permission_sets.sort(key=lambda p: p["name"])
        return json_response({"permissionSets": permission_sets})
    except Exception as e:
        print(f"Error listing permission sets: {e}")
        return internal_error_response()


def api_get_permission_set_details(ps_name: str) -> dict:
    try:
        instances = sso_admin_client.list_instances()
        if not instances.get("Instances"):
            return json_response({"error": "No IDC instance found"}, 404)
        instance_arn = instances["Instances"][0]["InstanceArn"]

        ps_arn = None
        paginator = sso_admin_client.get_paginator("list_permission_sets")
        for page in paginator.paginate(InstanceArn=instance_arn):
            for arn in page.get("PermissionSets", []):
                ps = sso_admin_client.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=arn)
                if ps["PermissionSet"]["Name"] == ps_name:
                    ps_arn = arn
                    break
            if ps_arn:
                break

        if not ps_arn:
            return json_response({"error": f"Permission set {ps_name} not found"}, 404)

        ps = sso_admin_client.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=ps_arn)
        inline_policy = None
        try:
            policy_response = sso_admin_client.get_inline_policy_for_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=ps_arn
            )
            raw = policy_response.get("InlinePolicy", "")
            inline_policy = json.loads(raw) if raw else None
        except Exception as e:
            print(f"Error getting inline policy: {e}")

        return json_response(
            {
                "name": ps["PermissionSet"]["Name"],
                "description": ps["PermissionSet"].get("Description", ""),
                "sessionDuration": ps["PermissionSet"].get("SessionDuration", "PT1H"),
                "arn": ps_arn,
                "inlinePolicy": inline_policy,
            }
        )
    except Exception as e:
        print(f"Error getting permission set details: {e}")
        return internal_error_response()


# =============================================================================
# Admin API: config storage (S3 admin/config.json)
# =============================================================================


def load_admin_config() -> dict:
    try:
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key="admin/config.json")
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        return {"mappings": []}


def save_admin_config(config: dict) -> None:
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key="admin/config.json",
        Body=json.dumps(config, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def api_get_config() -> dict:
    try:
        return json_response(load_admin_config())
    except Exception as e:
        print(f"Error getting config: {e}")
        return internal_error_response()


def api_save_config(body: str) -> dict:
    try:
        config = json.loads(body) if body else {}
        save_admin_config(config)
        return json_response({"success": True, "message": "Configuration saved"})
    except Exception as e:
        print(f"Error saving config: {e}")
        return internal_error_response()


# =============================================================================
# Admin API: deploy (permission sets + MDM/bootstrap config generation)
# =============================================================================


def create_or_update_permission_set_no_provision(instance_arn: str, name: str, models_list: list[dict]) -> str:
    """Create or update a permission set granting access to multiple Bedrock
    models. Does NOT provision — caller provisions separately."""
    ps_arn = None
    paginator = sso_admin_client.get_paginator("list_permission_sets")
    for page in paginator.paginate(InstanceArn=instance_arn):
        for arn in page.get("PermissionSets", []):
            ps = sso_admin_client.describe_permission_set(InstanceArn=instance_arn, PermissionSetArn=arn)
            if ps["PermissionSet"]["Name"] == name:
                ps_arn = arn
                break
        if ps_arn:
            break

    if not ps_arn:
        model_names = ", ".join(m["modelName"] for m in models_list[:3])
        response = sso_admin_client.create_permission_set(
            InstanceArn=instance_arn,
            Name=name,
            Description=f"Access to {model_names}",
            SessionDuration="PT8H",
        )
        ps_arn = response["PermissionSet"]["PermissionSetArn"]

    all_resources = []
    for model in models_list:
        model_id = model["modelId"]
        base_model = model_id.replace("us.anthropic.", "").replace("global.anthropic.", "").replace("eu.anthropic.", "")
        all_resources.append(f"arn:aws:bedrock:*:*:inference-profile/{model_id}*")
        all_resources.append(f"arn:aws:bedrock:*::foundation-model/anthropic.{base_model}*")
    all_resources = list(dict.fromkeys(all_resources))

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowBedrockModel",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                "Resource": all_resources,
            },
            {
                "Sid": "AllowBedrockList",
                "Effect": "Allow",
                "Action": ["bedrock:ListFoundationModels", "bedrock:GetFoundationModel"],
                "Resource": "*",
            },
        ],
    }
    sso_admin_client.put_inline_policy_to_permission_set(
        InstanceArn=instance_arn, PermissionSetArn=ps_arn, InlinePolicy=json.dumps(policy)
    )
    return ps_arn


def assign_permission_set(instance_arn: str, ps_arn: str, group_id: str, account_id: str) -> None:
    try:
        sso_admin_client.create_account_assignment(
            InstanceArn=instance_arn,
            PermissionSetArn=ps_arn,
            PrincipalType="GROUP",
            PrincipalId=group_id,
            TargetId=account_id,
            TargetType="AWS_ACCOUNT",
        )
    except sso_admin_client.exceptions.ConflictException:
        pass


def provision_with_retry(instance_arn: str, ps_arn: str, account_id: str, name: str) -> None:
    """Provision a permission set with exponential-backoff retry on
    ConflictException, then best-effort poll for completion."""
    max_retries = 10
    request_id = None
    for attempt in range(max_retries):
        try:
            response = sso_admin_client.provision_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=ps_arn, TargetType="AWS_ACCOUNT", TargetId=account_id
            )
            request_id = response.get("PermissionSetProvisioningStatus", {}).get("RequestId")
            break
        except sso_admin_client.exceptions.ConflictException:
            if attempt < max_retries - 1:
                time.sleep(2 + attempt * 2)
            else:
                raise

    if not request_id:
        return

    for _ in range(30):
        try:
            status_response = sso_admin_client.describe_permission_set_provisioning_status(
                InstanceArn=instance_arn, ProvisionPermissionSetRequestId=request_id
            )
            status = status_response.get("PermissionSetProvisioningStatus", {}).get("Status")
            if status in ("SUCCEEDED", "FAILED"):
                return
            time.sleep(2)
        except sso_admin_client.exceptions.ResourceNotFoundException:
            return
        except Exception as e:
            if "AccessDeniedException" in str(e):
                time.sleep(5)
                return
            raise
    print(f"Provisioning {name} timed out, continuing anyway")


def generate_mdm_configs(
    config_key: str,
    idc_start_url: str,
    account_id: str,
    role_name: str,
    models_list: list[dict],
    policies: dict | None = None,
    managed_mcp_servers: list[dict] | None = None,
    mcp_server_templates: list[dict] | None = None,
) -> None:
    """Build and upload the default/bootstrap/mobileconfig/reg files for one
    group's config_key, using the shared MDM builder/generators (the single
    source of truth also used by `ccwb cowork generate` and the bootstrap
    server) instead of duplicating the format-generation logic inline.

    When IDC_BOOTSTRAP_CLIENT_ID is configured, the generated
    mobileconfig/.reg also carry a bootstrapOidc block so Claude Desktop can
    authenticate itself directly against the landing page's /api/bootstrap
    endpoint (see landing-page-distribution.yaml's IdcBootstrapUserPoolClient
    and BootstrapApiListenerRule) instead of only getting the one-time
    default.json snapshot embedded in the profile at generation time.
    """
    policies = policies or {}
    managed_mcp_servers = managed_mcp_servers or []
    mcp_server_templates = mcp_server_templates or []
    deployment_uuid = str(uuid.uuid4()).upper()

    # Bootstrap URL base — the URL Claude Desktop polls for dynamic config.
    # Priority:
    #   1. Admin's explicit "Bootstrap URL Override" (any real domain or an
    #      SSM-tunnel host like https://localhost:8443) — always wins.
    #   2. The CloudFront domain, when the stack is deployed with CloudFront
    #      in front of the internal ALB — publicly reachable by Claude
    #      Desktop over a real HTTPS cert, no tunnel needed.
    #   3. BASE_URL (the ALB's CustomDomainName) — the original behavior;
    #      only reachable if that domain actually resolves for the client.
    if ENABLE_CLOUDFRONT and CLOUDFRONT_DOMAIN:
        bootstrap_base_url = f"https://{CLOUDFRONT_DOMAIN}"
    else:
        bootstrap_base_url = BASE_URL
    if policies.get("bootstrapUrlOverrideEnabled") and policies.get("bootstrapUrlOverrideHost"):
        override_protocol = policies.get("bootstrapUrlOverrideProtocol") or "https"
        override_host = policies["bootstrapUrlOverrideHost"].strip()
        override_port = str(policies.get("bootstrapUrlOverridePort") or "").strip()
        default_port = "443" if override_protocol == "https" else "80"
        if override_port and override_port != default_port:
            bootstrap_base_url = f"{override_protocol}://{override_host}:{override_port}"
        else:
            bootstrap_base_url = f"{override_protocol}://{override_host}"

    config: dict = {
        "inferenceProvider": "bedrock",
        "inferenceCredentialKind": "interactive",
        "inferenceBedrockRegion": REGION,
        "inferenceBedrockSsoStartUrl": idc_start_url,
        # IDC's own region, NOT this Lambda's/Bedrock's region — IAM Identity
        # Center data (permission sets, SSO OIDC endpoints) only ever lives
        # in the region IDC was enabled in, which can differ from where
        # Bedrock/this stack is deployed (e.g. infra in us-west-2, IDC in
        # us-east-1). Using REGION here sends Claude Desktop's SSO OIDC
        # requests to the wrong region's endpoint, which AWS SSO rejects
        # with InvalidRequestException.
        "inferenceBedrockSsoRegion": IDC_REGION,
        "inferenceBedrockSsoAccountId": account_id,
        "inferenceBedrockSsoRoleName": role_name,
        "inferenceModels": build_inference_models(models_list),
        "deploymentOrganizationUuid": deployment_uuid,
    }

    add_mcp_servers(config, managed_servers=managed_mcp_servers or None, local_templates=mcp_server_templates or None)

    # Policy / feature-control layer — the admin UI's "Tool Restrictions" +
    # "Feature Controls" (disabled tools, per-tool ask/allow, allowed folders,
    # egress allowlist, and the feature toggles incl. coworkTabEnabled).
    #
    # These are applied to a SEPARATE copy that feeds only the dynamic
    # bootstrap config and the static default.json fallback — deliberately NOT
    # the mobileconfig/.reg MDM profile. MDM keys are highest-precedence and
    # cannot be overridden, so baking a policy into the profile pins it and
    # forces an MDM re-push to change it (this is exactly why toggling cowork
    # in the console had no effect on already-provisioned devices). Keeping the
    # policy layer out of MDM lets the bootstrap server own it: toggle in the
    # admin console -> next sign-in / bootstrap refresh picks it up, no re-push.
    #
    # Known tradeoff (accepted): for cowork, the MDM profile governs TAB
    # VISIBILITY while bootstrap governs functional ACCESS. Because the profile
    # omits coworkTabEnabled, the tab renders by default and bootstrap gates
    # whether requests are accepted. So an enable->disable change takes effect
    # functionally right away (tab still shown, requests blocked); only tab
    # visibility would lag until an MDM re-push. This is preferred over
    # re-pushing MDM on every policy change.
    policy_config = dict(config)
    add_policies(
        policy_config,
        disabled_tools=policies.get("disabledBuiltinTools"),
        tool_policies=policies.get("builtinToolPolicy"),
        allowed_folders=policies.get("allowedWorkspaceFolders"),
        egress_hosts=policies.get("coworkEgressAllowedHosts"),
        feature_toggles={
            "isLocalDevMcpEnabled": policies.get("isLocalDevMcpEnabled", True),
            "isDesktopExtensionEnabled": policies.get("isDesktopExtensionEnabled", True),
            "isDesktopExtensionSignatureRequired": policies.get("isDesktopExtensionSignatureRequired", False),
            "coworkTabEnabled": policies.get("coworkTabEnabled", True),
            "disableBundledSkills": policies.get("disableBundledSkills", False),
            "disableDeploymentModeChooser": policies.get("disableDeploymentModeChooser", True),
        },
    )

    # Static download (default.json): full config INCLUDING policies — this is
    # the standalone fallback for orgs that install a static config without the
    # bootstrap mechanism, so it still carries the policy layer.
    json_content = json.dumps(policy_config, indent=2)
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/default.json",
        Body=json_content.encode("utf-8"),
        ContentType="application/json",
    )

    # Bootstrap config (dynamic, served by the landing page's /api/bootstrap):
    # base + policy layer. Every feature toggle must be explicit here — Claude
    # Desktop treats a bootstrap-settable key the response omits as unset, not
    # inherited from MDM. This is now the authoritative source for the policy
    # layer on bootstrap-enabled devices.
    bootstrap_config = dict(policy_config)
    add_bootstrap_config(bootstrap_config, bootstrap_url=f"{bootstrap_base_url}/api/bootstrap")
    bootstrap_config["_configKey"] = config_key
    bootstrap_config["_version"] = deployment_uuid
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/bootstrap.json",
        Body=json.dumps(bootstrap_config, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    # The MDM profile only needs the trust anchor (bootstrapUrl +
    # bootstrapOidc) — Claude Desktop fetches the actual config live from
    # /api/bootstrap using this OIDC client, so bootstrap_oidc is embedded
    # in mobileconfig/.reg but NOT in default.json above (that file is the
    # static/no-bootstrap fallback for orgs installing profiles without MDM
    # bootstrap wiring).
    bootstrap_oidc = None
    if IDC_BOOTSTRAP_CLIENT_ID and IDC_BOOTSTRAP_ISSUER:
        bootstrap_oidc = {
            "clientId": IDC_BOOTSTRAP_CLIENT_ID,
            "issuer": IDC_BOOTSTRAP_ISSUER,
            "scopes": "openid email profile",
        }
        if IDC_BOOTSTRAP_REDIRECT_PORT:
            bootstrap_oidc["redirectPort"] = int(IDC_BOOTSTRAP_REDIRECT_PORT)

    # Derives from `config` (base connection settings + MCP), NOT
    # `policy_config` — the mobileconfig/.reg profile intentionally omits the
    # Tool Restrictions / Feature Controls layer so those stay bootstrap-
    # controlled (see the policy_config comment above). It carries only what
    # the device needs to connect and to reach /api/bootstrap.
    mdm_config = dict(config)
    add_bootstrap_config(mdm_config, bootstrap_url=f"{bootstrap_base_url}/api/bootstrap", oidc_config=bootstrap_oidc)

    mobileconfig = generate_mobileconfig(
        mdm_config,
        profile_identifier=config_key,
        profile_display_name=f"Claude Desktop - {config_key.replace('-', ' ').title()}",
    )
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/Claude.mobileconfig",
        Body=mobileconfig.encode("utf-8"),
        ContentType="application/x-apple-aspen-config",
    )

    reg_content = generate_reg_file(mdm_config, profile_identifier=config_key)
    s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=f"config/{config_key}/Claude.reg",
        Body=reg_content.encode("utf-16-le"),
        ContentType="text/plain; charset=utf-16le",
    )

    if mcp_server_templates:
        mcp_config = {"mcpServers": {}}
        for server in mcp_server_templates:
            mcp_config["mcpServers"][server.get("name", "unnamed")] = {
                "command": server.get("command", ""),
                "args": server.get("args", []),
                "env": server.get("env", {}),
            }
        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=f"config/{config_key}/claude_desktop_config.json",
            Body=json.dumps(mcp_config, indent=2).encode("utf-8"),
            ContentType="application/json",
        )


def api_deploy_config(body: str) -> dict:
    """Publish action: for each group mapping, create/update the permission
    set, assign + provision it, then regenerate that group's MDM/bootstrap
    config files. Best-effort per-mapping — one group's failure doesn't
    roll back others."""
    try:
        config = json.loads(body) if body else load_admin_config()
        mappings = config.get("mappings", [])
        if not mappings:
            return json_response({"error": "No group-model mappings configured"}, 400)

        policies = config.get("policies", {})
        managed_mcp_servers = config.get("managedMcpServers", [])
        mcp_server_templates = config.get("mcpServerTemplates", [])

        results = []
        account_id = sts_client.get_caller_identity()["Account"]

        instances = sso_admin_client.list_instances()
        if not instances.get("Instances"):
            return json_response({"error": "No IDC instance found"}, 404)
        instance_arn = instances["Instances"][0]["InstanceArn"]
        identity_store_id = instances["Instances"][0]["IdentityStoreId"]
        idc_start_url = f"https://{identity_store_id}.awsapps.com/start"

        for mapping in mappings:
            group_name = mapping.get("groupName", "")
            group_id = mapping.get("groupId", "")
            role_name = mapping.get("roleName", f"ClaudeCode-{group_name}")
            models_list = mapping.get("models", [])
            if not group_id or not models_list:
                continue

            try:
                ps_arn = create_or_update_permission_set_no_provision(instance_arn, role_name, models_list)
                assign_permission_set(instance_arn, ps_arn, group_id, account_id)
                provision_with_retry(instance_arn, ps_arn, account_id, role_name)

                config_key = group_name_to_config_key(group_name)
                generate_mdm_configs(
                    config_key,
                    idc_start_url,
                    account_id,
                    role_name,
                    models_list,
                    policies=policies,
                    managed_mcp_servers=managed_mcp_servers,
                    mcp_server_templates=mcp_server_templates,
                )
                results.append(
                    {
                        "group": group_name,
                        "model": ", ".join(m["modelName"] for m in models_list),
                        "status": "success",
                        "permissionSet": role_name,
                    }
                )
                time.sleep(1)  # avoid IDC API conflicts between groups
            except Exception as e:
                print(f"Error deploying for group {log_safe(group_name)}: {e}")
                results.append({"group": group_name, "model": "", "status": "error", "error": str(e)})

        save_admin_config(config)
        return json_response({"success": True, "results": results})
    except Exception as e:
        print(f"Error deploying config: {e}")
        return internal_error_response()


# =============================================================================
# Admin page (HTML SPA shell — calls the /admin/api/* endpoints above)
# =============================================================================


def esc(value) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def serve_admin_page(user_email: str) -> dict:
    """Generate the admin console HTML page — sidebar navigation with Models &
    Groups, Policies, and MCP Servers config pages, plus a Deploy page. Ported
    from the original CDK-based implementation
    (backup/idc-landing-page-cdk-working:deployment/idc-landing-page/lambda/index.py)
    with its JS wired to this Lambda's existing /admin/api/* endpoints, which
    already match the same request/response shapes the original UI expects.
    """
    # The default bootstrap URL base shown in the "Bootstrap URL Override"
    # hint — the CloudFront domain when this deployment is fronted by
    # CloudFront, otherwise the ALB's custom domain (BASE_URL).
    bootstrap_default_hint = f"https://{CLOUDFRONT_DOMAIN}" if (ENABLE_CLOUDFRONT and CLOUDFRONT_DOMAIN) else BASE_URL
    return html_response(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Desktop Admin</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f7fa;
            min-height: 100vh;
        }}
        .layout {{
            display: flex;
            min-height: 100vh;
        }}
        .sidebar {{
            width: 260px;
            background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            padding: 0;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
        }}
        .sidebar-header {{
            padding: 24px 20px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }}
        .sidebar-header h1 {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 4px;
        }}
        .sidebar-header .subtitle {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
        }}
        .sidebar-nav {{
            padding: 16px 0;
        }}
        .nav-section {{
            padding: 8px 20px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: rgba(255,255,255,0.4);
            margin-top: 8px;
        }}
        .nav-item {{
            display: flex;
            align-items: center;
            padding: 12px 20px;
            color: rgba(255,255,255,0.8);
            text-decoration: none;
            cursor: pointer;
            transition: all 0.2s;
            border-left: 3px solid transparent;
        }}
        .nav-item:hover {{
            background: rgba(255,255,255,0.05);
            color: white;
        }}
        .nav-item.active {{
            background: rgba(102, 126, 234, 0.2);
            color: white;
            border-left-color: #667eea;
        }}
        .nav-item svg {{
            width: 18px;
            height: 18px;
            margin-right: 12px;
            opacity: 0.7;
        }}
        .nav-item.active svg {{
            opacity: 1;
        }}
        .sidebar-footer {{
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            padding: 16px 20px;
            border-top: 1px solid rgba(255,255,255,0.1);
            background: rgba(0,0,0,0.2);
        }}
        .user-info {{
            display: flex;
            align-items: center;
            margin-bottom: 12px;
        }}
        .user-avatar {{
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: 600;
            margin-right: 10px;
        }}
        .user-email {{
            font-size: 12px;
            color: rgba(255,255,255,0.8);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 160px;
        }}
        .sidebar-links {{
            display: flex;
            gap: 12px;
        }}
        .sidebar-links a {{
            font-size: 12px;
            color: rgba(255,255,255,0.6);
            text-decoration: none;
        }}
        .sidebar-links a:hover {{
            color: white;
        }}
        .main-content {{
            flex: 1;
            margin-left: 260px;
            padding: 24px 32px;
            max-width: calc(100% - 260px);
        }}
        .page-header {{
            margin-bottom: 24px;
        }}
        .page-header h2 {{
            font-size: 24px;
            color: #1a1a2e;
            margin-bottom: 4px;
        }}
        .page-header p {{
            color: #666;
            font-size: 14px;
        }}
        .section {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .section h3 {{
            font-size: 16px;
            color: #333;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid #eee;
        }}
        .section h4 {{
            font-size: 14px;
            color: #555;
            margin: 20px 0 12px;
        }}
        .section-description {{
            color: #666;
            font-size: 13px;
            margin-bottom: 16px;
        }}
        .page-content {{ display: none; }}
        .page-content.active {{ display: block; }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
            font-size: 13px;
        }}
        select, input[type="text"], input[type="url"], input[type="number"], textarea {{
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 14px;
            width: 100%;
            transition: border-color 0.2s;
        }}
        select:focus, input:focus, textarea:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }}
        textarea {{
            min-height: 80px;
            font-family: monospace;
            resize: vertical;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 10px 20px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            font-size: 14px;
            transition: all 0.2s;
            gap: 8px;
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .btn-primary:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
        }}
        .btn-success {{
            background: linear-gradient(135deg, #28a745 0%, #20c997 100%);
            color: white;
        }}
        .btn-success:hover {{
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(40, 167, 69, 0.3);
        }}
        .btn-danger {{
            background: #dc3545;
            color: white;
        }}
        .btn-danger:hover {{
            background: #c82333;
        }}
        .btn-secondary {{
            background: #6c757d;
            color: white;
        }}
        .btn-sm {{
            padding: 6px 12px;
            font-size: 12px;
        }}
        .btn-outline {{
            background: white;
            border: 1px solid #ddd;
            color: #333;
        }}
        .btn-outline:hover {{
            background: #f8f9fa;
        }}
        .actions {{
            display: flex;
            gap: 12px;
            margin-top: 20px;
        }}
        .status {{
            padding: 16px;
            border-radius: 8px;
            margin-top: 20px;
            display: none;
        }}
        .status.success {{
            background: #d4edda;
            color: #155724;
            display: block;
        }}
        .status.error {{
            background: #f8d7da;
            color: #721c24;
            display: block;
        }}
        .status.info {{
            background: #d1ecf1;
            color: #0c5460;
            display: block;
        }}
        .loading {{
            opacity: 0.6;
            pointer-events: none;
        }}
        .badge {{
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 12px;
            font-weight: 500;
        }}
        .badge-success {{
            background: #e8f5e9;
            color: #2e7d32;
        }}
        .badge-warning {{
            background: #fff3e0;
            color: #e65100;
        }}
        .badge-danger {{
            background: #ffebee;
            color: #c62828;
        }}
        .badge-info {{
            background: #e3f2fd;
            color: #1565c0;
        }}
        .model-tags, .tool-tags {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .model-tag, .tool-tag {{
            display: inline-flex;
            align-items: center;
            background: #e3f2fd;
            color: #1565c0;
            padding: 4px 10px;
            border-radius: 16px;
            font-size: 13px;
        }}
        .tool-tag.blocked {{
            background: #ffebee;
            color: #c62828;
        }}
        .tool-tag.ask {{
            background: #fff3e0;
            color: #e65100;
        }}
        .model-tag .remove, .tool-tag .remove {{
            margin-left: 6px;
            cursor: pointer;
            opacity: 0.6;
            font-weight: bold;
        }}
        .model-tag .remove:hover, .tool-tag .remove:hover {{
            opacity: 1;
        }}
        .add-row {{
            display: flex;
            gap: 8px;
            align-items: center;
            margin-top: 12px;
        }}
        .add-row select, .add-row input {{
            flex: 1;
        }}
        .toggle-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 0;
            border-bottom: 1px solid #eee;
        }}
        .toggle-row:last-child {{
            border-bottom: none;
        }}
        .toggle-label {{
            font-weight: 500;
            color: #333;
        }}
        .toggle-description {{
            font-size: 12px;
            color: #888;
            margin-top: 4px;
        }}
        .toggle-switch {{
            position: relative;
            width: 48px;
            height: 24px;
            flex-shrink: 0;
        }}
        .toggle-switch input {{
            opacity: 0;
            width: 0;
            height: 0;
        }}
        .toggle-slider {{
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: 0.3s;
            border-radius: 24px;
        }}
        .toggle-slider:before {{
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: 0.3s;
            border-radius: 50%;
        }}
        input:checked + .toggle-slider {{
            background-color: #667eea;
        }}
        input:checked + .toggle-slider:before {{
            transform: translateX(24px);
        }}
        .card {{
            border: 1px solid #e0e0e0;
            border-radius: 10px;
            padding: 16px;
            margin-bottom: 12px;
            background: #fafafa;
        }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        .card-header h5 {{
            font-size: 14px;
            font-weight: 600;
            margin: 0;
        }}
        .card-body {{
            font-size: 13px;
            color: #666;
        }}
        .card-body code {{
            background: #e9ecef;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 12px;
        }}
        .form-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        .form-grid .full-width {{
            grid-column: 1 / -1;
        }}
        .form-group {{
            margin-bottom: 16px;
        }}
        .form-group label {{
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: #555;
            margin-bottom: 6px;
        }}
        .collapsible-btn {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            padding: 12px 16px;
            background: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 500;
            color: #333;
            margin-bottom: 12px;
            transition: all 0.2s;
        }}
        .collapsible-btn:hover {{
            background: #e9ecef;
        }}
        .collapsible-btn.active {{
            border-color: #667eea;
            background: #f0f4ff;
        }}
        .collapsible-content {{
            display: none;
            padding: 16px;
            background: #fafafa;
            border-radius: 8px;
            margin-bottom: 16px;
        }}
        .collapsible-content.show {{
            display: block;
        }}
        .grid-2 {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }}
        @media (max-width: 1200px) {{
            .grid-2 {{
                grid-template-columns: 1fr;
            }}
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }}
        .summary-card {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
        }}
        .summary-card .number {{
            font-size: 28px;
            font-weight: 700;
            color: #667eea;
        }}
        .summary-card .label {{
            font-size: 12px;
            color: #666;
            margin-top: 4px;
        }}
        pre {{
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 16px;
            border-radius: 8px;
            overflow: auto;
            max-height: 400px;
            font-size: 12px;
        }}
        .save-status {{
            font-size: 13px;
            padding: 8px 12px;
            border-radius: 6px;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .save-status.saving {{
            background: #fff3e0;
            color: #e65100;
        }}
        .save-status.saved {{
            background: #e8f5e9;
            color: #2e7d32;
        }}
        .save-status.error {{
            background: #ffebee;
            color: #c62828;
        }}
        .save-status.unsaved {{
            background: #fff8e1;
            color: #ff8f00;
        }}
        @keyframes spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="layout">
        <aside class="sidebar">
            <div class="sidebar-header">
                <h1>Claude Admin</h1>
                <div class="subtitle">Enterprise Configuration</div>
            </div>
            <nav class="sidebar-nav">
                <div class="nav-section">Configuration</div>
                <a class="nav-item active" onclick="switchPage('models')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
                    Models &amp; Groups
                </a>
                <a class="nav-item" onclick="switchPage('policies')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                    Policies
                </a>
                <a class="nav-item" onclick="switchPage('mcp')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                    MCP Servers
                </a>
                <div class="nav-section">Actions</div>
                <a class="nav-item" onclick="switchPage('deploy')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                    Deploy
                </a>
            </nav>
            <div class="sidebar-footer">
                <div class="user-info">
                    <div class="user-avatar">{esc(user_email[0].upper()) if user_email else 'A'}</div>
                    <div class="user-email" title="{esc(user_email)}">{esc(user_email)}</div>
                </div>
                <div class="sidebar-links">
                    <a href="/">Landing Page</a>
                    <a href="/logout">Logout</a>
                </div>
            </div>
        </aside>

        <main class="main-content">
            <!-- Models & Groups Page -->
            <div id="page-models" class="page-content active">
                <div class="page-header">
                    <h2>Models &amp; Groups</h2>
                    <p>Assign Bedrock inference profiles to IAM Identity Center groups</p>
                </div>

                <div class="section">
                    <h3>Group to Model Mappings</h3>
                    <p class="section-description">Each group will get a permission set with access to the assigned models.</p>
                    <table id="mappings-table">
                        <thead>
                            <tr>
                                <th>IDC Group</th>
                                <th>Assigned Models</th>
                                <th>Add Model</th>
                                <th>Permission Set</th>
                            </tr>
                        </thead>
                        <tbody id="mappings-body">
                            <tr><td colspan="4" style="text-align: center; color: #888; padding: 40px;">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>

                <div class="section">
                    <h3>Available Models</h3>
                    <table id="models-table">
                        <thead>
                            <tr>
                                <th>Model Name</th>
                                <th>Model ID</th>
                                <th>Type</th>
                            </tr>
                        </thead>
                        <tbody id="models-body">
                            <tr><td colspan="3" style="text-align: center; color: #888; padding: 40px;">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>

                <div class="section" style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div id="models-save-status" class="save-status"></div>
                        <button class="btn btn-primary" onclick="saveDraft('models')">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                            Save Draft
                        </button>
                    </div>
                </div>
            </div>

            <!-- Policies Page -->
            <div id="page-policies" class="page-content">
                <div class="page-header">
                    <h2>Policies</h2>
                    <p>Control which tools and features are available to users</p>
                </div>

                <div class="grid-2">
                    <div class="section">
                        <h3>Tool Restrictions</h3>
                        <p class="section-description">Blocked tools are completely removed from Claude.</p>

                        <h4>Disabled Tools</h4>
                        <div id="disabled-tools-list" class="tool-tags">
                            <span style="color:#888;font-size:13px;">None - all tools enabled</span>
                        </div>
                        <div class="add-row">
                            <select id="add-disabled-tool">
                                <option value="">Select tool to disable...</option>
                                <option value="WebSearch">WebSearch</option>
                                <option value="WebFetch">WebFetch</option>
                                <option value="Bash">Bash (Shell commands)</option>
                                <option value="Edit">Edit (File editing)</option>
                                <option value="Write">Write (File writing)</option>
                                <option value="NotebookEdit">NotebookEdit</option>
                            </select>
                            <button class="btn btn-primary btn-sm" onclick="addDisabledTool()">Block</button>
                        </div>

                        <h4>Tool Policies</h4>
                        <p class="section-description">Set approval requirements for specific tools.</p>
                        <div id="tool-policies-list"></div>
                        <div class="add-row">
                            <select id="add-tool-policy-name" style="flex: 2;">
                                <option value="">Select tool...</option>
                                <option value="Bash">Bash</option>
                                <option value="Edit">Edit</option>
                                <option value="Write">Write</option>
                                <option value="WebFetch">WebFetch</option>
                                <option value="WebSearch">WebSearch</option>
                            </select>
                            <select id="add-tool-policy-value" style="flex: 1;">
                                <option value="allow">Allow</option>
                                <option value="ask">Ask</option>
                                <option value="blocked">Block</option>
                            </select>
                            <button class="btn btn-primary btn-sm" onclick="addToolPolicy()">Add</button>
                        </div>
                    </div>

                    <div class="section">
                        <h3>Feature Controls</h3>
                        <p class="section-description">Enable or disable Claude Desktop features.</p>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Allow Local MCP Servers</div>
                                <div class="toggle-description">Let users add their own MCP servers</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-isLocalDevMcpEnabled" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Allow Desktop Extensions</div>
                                <div class="toggle-description">Let users install .dxt and .mcpb extensions</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-isDesktopExtensionEnabled" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Require Signed Extensions</div>
                                <div class="toggle-description">Only allow signed extensions</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-isDesktopExtensionSignatureRequired">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Enable Cowork Tab</div>
                                <div class="toggle-description">Allow access to Cowork/agentic features</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-coworkTabEnabled" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Disable Bundled Skills</div>
                                <div class="toggle-description">Turn off built-in skills and workflows</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-disableBundledSkills">
                                <span class="toggle-slider"></span>
                            </label>
                        </div>

                        <div class="toggle-row">
                            <div>
                                <div class="toggle-label">Lock to Bedrock Provider</div>
                                <div class="toggle-description">Prevent switching to Anthropic direct</div>
                            </div>
                            <label class="toggle-switch">
                                <input type="checkbox" id="policy-disableDeploymentModeChooser" checked>
                                <span class="toggle-slider"></span>
                            </label>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h3>Workspace &amp; Network Restrictions</h3>
                    <div class="grid-2">
                        <div>
                            <h4>Allowed Workspace Folders</h4>
                            <p class="section-description">Restrict which directories users can attach. Leave empty for no restrictions.</p>
                            <div id="allowed-folders-list" style="margin-bottom: 12px;"></div>
                            <div class="add-row">
                                <input type="text" id="add-folder-path" placeholder="e.g., ~/Projects">
                                <button class="btn btn-primary btn-sm" onclick="addAllowedFolder()">Add</button>
                            </div>
                        </div>
                        <div>
                            <h4>Network Egress Allowlist</h4>
                            <p class="section-description">Restrict which hosts tools can connect to. Use * for unrestricted.</p>
                            <div id="egress-hosts-list" style="margin-bottom: 12px;"></div>
                            <div class="add-row">
                                <input type="text" id="add-egress-host" placeholder="e.g., *.corp.com">
                                <button class="btn btn-primary btn-sm" onclick="addEgressHost()">Add</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h3>Bootstrap URL Override</h3>
                    <p class="section-description">
                        The bootstrap config URL embedded in generated MDM profiles defaults to
                        <code>{html.escape(bootstrap_default_hint)}</code>. Override it here with
                        any protocol/host/port when you want Claude Desktop to reach a different
                        address — for example a real custom domain once you point one at this
                        deployment via Route 53 (e.g. <code>https://claude.example.com</code>),
                        or an SSM-tunnel/VPN host for testing (e.g. <code>https://localhost:8443</code>).
                        Only affects newly generated configs; click Deploy again on Models &amp;
                        Groups to regenerate existing ones.
                    </p>
                    <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                        <input type="checkbox" id="policy-bootstrapUrlOverrideEnabled">
                        <span>Override bootstrap URL</span>
                    </label>
                    <div id="bootstrap-url-override-fields" style="display: none; gap: 12px;" class="add-row">
                        <select id="bootstrap-url-override-protocol" style="flex: 0 0 100px;">
                            <option value="https">https</option>
                            <option value="http">http</option>
                        </select>
                        <input type="text" id="bootstrap-url-override-host" placeholder="claude.example.com" style="flex: 2;">
                        <input type="number" id="bootstrap-url-override-port" placeholder="443" min="1" max="65535" style="flex: 1;">
                    </div>
                </div>

                <div class="section" style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div id="policies-save-status" class="save-status"></div>
                        <button class="btn btn-primary" onclick="saveDraft('policies')">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                            Save Draft
                        </button>
                    </div>
                </div>
            </div>

            <!-- MCP Servers Page -->
            <div id="page-mcp" class="page-content">
                <div class="page-header">
                    <h2>MCP Servers</h2>
                    <p>Pre-configure MCP servers for your users</p>
                </div>

                <div class="section">
                    <h3>Managed MCP Servers (Remote)</h3>
                    <p class="section-description">Remote HTTPS MCP servers that users connect to via OAuth.</p>
                    <div id="managed-mcp-servers"></div>

                    <button class="collapsible-btn" onclick="toggleCollapsible(this)">
                        <span>+ Add Remote MCP Server</span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                    <div class="collapsible-content">
                        <div class="form-grid">
                            <div class="form-group">
                                <label>Server Name</label>
                                <input type="text" id="new-mcp-name" placeholder="e.g., corporate-tools">
                            </div>
                            <div class="form-group">
                                <label>Server URL</label>
                                <input type="url" id="new-mcp-url" placeholder="https://mcp.your-corp.com/api">
                            </div>
                            <div class="form-group full-width">
                                <label>Description (optional)</label>
                                <input type="text" id="new-mcp-description" placeholder="Corporate tools gateway">
                            </div>
                            <div class="full-width">
                                <button class="btn btn-primary" onclick="addManagedMcpServer()">Add Server</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h3>MCP Server Templates (Local)</h3>
                    <p class="section-description">Pre-configured local MCP servers. Users may need to provide credentials.</p>
                    <div id="mcp-templates"></div>

                    <button class="collapsible-btn" onclick="toggleCollapsible(this)">
                        <span>+ Add from Template</span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                    <div class="collapsible-content">
                        <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px;">
                            <button class="btn btn-outline" onclick="addMcpTemplate('github')">GitHub</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('slack')">Slack</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('filesystem')">Filesystem</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('brave-search')">Brave Search</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('postgres')">PostgreSQL</button>
                            <button class="btn btn-outline" onclick="addMcpTemplate('custom')">Custom</button>
                        </div>
                    </div>

                    <button class="collapsible-btn" onclick="toggleCollapsible(this)">
                        <span>+ Add Custom Local Server</span>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                    </button>
                    <div class="collapsible-content">
                        <div class="form-grid">
                            <div class="form-group">
                                <label>Server Name</label>
                                <input type="text" id="new-local-mcp-name" placeholder="e.g., my-server">
                            </div>
                            <div class="form-group">
                                <label>Command</label>
                                <input type="text" id="new-local-mcp-command" placeholder="/usr/local/bin/npx">
                            </div>
                            <div class="form-group full-width">
                                <label>Arguments (one per line)</label>
                                <textarea id="new-local-mcp-args" placeholder="-y&#10;@modelcontextprotocol/server-github"></textarea>
                            </div>
                            <div class="form-group full-width">
                                <label>Environment Variables (KEY=value, one per line)</label>
                                <textarea id="new-local-mcp-env" placeholder="GITHUB_TOKEN=&lt;user-provided&gt;&#10;PATH=/usr/local/bin:/usr/bin"></textarea>
                            </div>
                            <div class="full-width">
                                <button class="btn btn-primary" onclick="addLocalMcpServer()">Add Server</button>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="section" style="background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div id="mcp-save-status" class="save-status"></div>
                        <button class="btn btn-primary" onclick="saveDraft('mcp')">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                            Save Draft
                        </button>
                    </div>
                </div>
            </div>

            <!-- Deploy Page -->
            <div id="page-deploy" class="page-content">
                <div class="page-header">
                    <h2>Deploy Configuration</h2>
                    <p>Generate MDM configuration files for your groups</p>
                </div>

                <div class="section">
                    <h3>Configuration Summary</h3>
                    <div class="summary-grid" id="deploy-summary">
                        <div class="summary-card">
                            <div class="number" id="summary-groups">0</div>
                            <div class="label">Groups with Models</div>
                        </div>
                        <div class="summary-card">
                            <div class="number" id="summary-policies">0</div>
                            <div class="label">Policy Settings</div>
                        </div>
                        <div class="summary-card">
                            <div class="number" id="summary-mcp">0</div>
                            <div class="label">MCP Servers</div>
                        </div>
                    </div>
                    <p class="section-description">
                        Deploying will update IAM Identity Center permission sets and generate MDM configuration files
                        (mobileconfig for macOS, .reg for Windows, JSON for manual setup) for each group.
                    </p>
                    <div style="background: #e8f5e9; border: 1px solid #a5d6a7; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                        <div style="display: flex; align-items: flex-start; gap: 12px;">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2e7d32" stroke-width="2" style="flex-shrink: 0; margin-top: 2px;"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                            <div>
                                <div style="font-weight: 600; color: #1b5e20; margin-bottom: 4px;">Dynamic Config Updates via OIDC Bootstrap</div>
                                <div style="color: #2e7d32; font-size: 13px; line-height: 1.5;">
                                    MDM profiles include OIDC bootstrap configuration. Claude Desktop will authenticate via Cognito (federated with IAM Identity Center) and automatically fetch the latest configuration every 30 minutes.
                                    <strong>After the initial profile installation, users will receive policy and model updates automatically</strong> — no need to re-download profiles.
                                </div>
                                <div style="color: #558b2f; font-size: 12px; margin-top: 8px; padding-top: 8px; border-top: 1px solid #c5e1a5;">
                                    <strong>Note:</strong> The 30-minute refresh interval is controlled by Claude Desktop and cannot be changed server-side. For urgent updates (e.g., security policy changes), ask users to restart Claude Desktop to fetch changes immediately.
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="actions">
                        <button class="btn btn-success" onclick="deployConfig()">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                            Save Configuration
                        </button>
                        <button class="btn btn-outline" onclick="previewConfig()">Preview JSON</button>
                    </div>
                    <div id="status" class="status"></div>
                </div>

                <div class="section">
                    <h3>Generated Configuration Preview</h3>
                    <pre id="config-preview" style="display: none;">Select "Preview JSON" to see the configuration</pre>
                </div>
            </div>
        </main>
    </div>

    <script>
        function escapeHtml(value) {{
            const div = document.createElement('div');
            div.textContent = value === null || value === undefined ? '' : String(value);
            return div.innerHTML;
        }}

        let groups = [];
        let models = [];
        let permissionSets = [];
        let groupConfig = {{}};

        let policies = {{
            disabledBuiltinTools: [],
            builtinToolPolicy: {{}},
            isLocalDevMcpEnabled: true,
            isDesktopExtensionEnabled: true,
            isDesktopExtensionSignatureRequired: false,
            coworkTabEnabled: true,
            disableBundledSkills: false,
            disableDeploymentModeChooser: true,
            allowedWorkspaceFolders: [],
            coworkEgressAllowedHosts: [],
            bootstrapUrlOverrideEnabled: false,
            bootstrapUrlOverrideProtocol: 'https',
            bootstrapUrlOverrideHost: '',
            bootstrapUrlOverridePort: ''
        }};

        let managedMcpServers = [];
        let mcpServerTemplates = [];

        function switchPage(pageId) {{
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.querySelectorAll('.page-content').forEach(p => p.classList.remove('active'));
            document.querySelector(`.nav-item[onclick="switchPage('${{pageId}}')"]`).classList.add('active');
            document.getElementById('page-' + pageId).classList.add('active');
            if (pageId === 'deploy') updateDeploySummary();
        }}

        function toggleCollapsible(el) {{
            el.classList.toggle('active');
            el.nextElementSibling.classList.toggle('show');
        }}

        async function init() {{
            await Promise.all([loadGroups(), loadModels(), loadPermissionSets(), loadAdminConfig()]);
            buildGroupConfig();
            renderMappings();
            renderModels();
            renderPolicies();
            renderMcpServers();
        }}

        async function loadGroups() {{
            try {{
                const res = await fetch('/admin/api/groups');
                const data = await res.json();
                groups = (data.groups || []).filter(g => g.displayName && g.displayName.toLowerCase().includes('claude'));
            }} catch (e) {{ groups = []; }}
        }}

        async function loadModels() {{
            try {{
                const res = await fetch('/admin/api/models');
                const data = await res.json();
                models = data.models || [];
            }} catch (e) {{ models = []; }}
        }}

        async function loadPermissionSets() {{
            try {{
                const res = await fetch('/admin/api/permission-sets');
                const data = await res.json();
                permissionSets = data.permissionSets || [];
            }} catch (e) {{ permissionSets = []; }}
        }}

        async function loadAdminConfig() {{
            try {{
                const res = await fetch('/admin/api/config');
                const data = await res.json();
                if (data.policies) policies = {{ ...policies, ...data.policies }};
                if (data.managedMcpServers) managedMcpServers = data.managedMcpServers;
                if (data.mcpServerTemplates) mcpServerTemplates = data.mcpServerTemplates;
            }} catch (e) {{}}
        }}

        function buildGroupConfig() {{
            groupConfig = {{}};
            for (const group of groups) {{
                groupConfig[group.groupId] = {{ groupName: group.displayName, permissionSetName: null, models: [] }};
            }}
            for (const ps of permissionSets) {{
                if (!ps.assignedGroups) continue;
                for (const ag of ps.assignedGroups) {{
                    if (!groupConfig[ag.groupId]) continue;
                    groupConfig[ag.groupId].permissionSetName = ps.name;
                    if (ps.modelResources && ps.modelResources.length > 0) {{
                        const seenProfiles = new Set();
                        for (const resource of ps.modelResources) {{
                            const match = resource.match(/inference-profile\\/((?:us|global)\\.anthropic\\.[^*]+)/);
                            if (!match) continue;
                            const profileId = match[1];
                            if (seenProfiles.has(profileId)) continue;
                            seenProfiles.add(profileId);
                            let foundModel = models.find(m => m.modelId === profileId);
                            if (!foundModel) {{
                                const profileBase = profileId.replace(/-v\\d+:.*$/, '').replace(/:\\d+$/, '');
                                foundModel = models.find(m => m.modelId.replace(/-v\\d+:.*$/, '').replace(/:\\d+$/, '') === profileBase);
                            }}
                            const modelName = foundModel ? foundModel.modelName : profileId;
                            const modelId = foundModel ? foundModel.modelId : profileId;
                            if (!groupConfig[ag.groupId].models.find(m => m.modelId === modelId)) {{
                                groupConfig[ag.groupId].models.push({{ modelId, modelName }});
                            }}
                        }}
                    }}
                }}
            }}
        }}

        function renderMappings() {{
            const tbody = document.getElementById('mappings-body');
            if (groups.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#888;padding:40px;">No Claude groups found. Create groups with "Claude" in the name in IAM Identity Center.</td></tr>';
                return;
            }}
            let html = '';
            for (const group of groups) {{
                const gc = groupConfig[group.groupId] || {{ models: [], permissionSetName: null }};
                let modelTagsHtml = '<div class="model-tags">';
                if (gc.models.length === 0) modelTagsHtml += '<span style="color:#888;">None</span>';
                else gc.models.forEach((m, mi) => {{ modelTagsHtml += '<span class="model-tag">' + m.modelName + ' <span class="remove" data-group="' + group.groupId + '" data-idx="' + mi + '" onclick="removeModelByIdx(this)">&times;</span></span>'; }});
                modelTagsHtml += '</div>';
                let addHtml = '<div class="add-row"><select id="add-model-' + group.groupId + '" style="font-size:13px;"><option value="">Select model...</option>';
                models.filter(m => !gc.models.find(gm => gm.modelId === m.modelId)).forEach(m => {{ addHtml += '<option value="' + encodeURIComponent(m.modelId) + '|' + encodeURIComponent(m.modelName) + '">' + m.modelName + '</option>'; }});
                addHtml += '</select><button class="btn btn-primary btn-sm" data-group="' + group.groupId + '" onclick="addModelFromBtn(this)">+</button></div>';
                let psHtml = gc.permissionSetName ? escapeHtml(gc.permissionSetName) + ' <a href="#" onclick="viewPolicy(' + escapeHtml(JSON.stringify(gc.permissionSetName)) + ');return false;" style="font-size:11px;color:#667eea;">[view]</a>' : '-';
                html += '<tr><td><strong>' + escapeHtml(group.displayName) + '</strong></td><td>' + modelTagsHtml + '</td><td>' + addHtml + '</td><td>' + psHtml + '</td></tr>';
            }}
            tbody.innerHTML = html;
        }}

        function addModelFromBtn(btn) {{
            const groupId = btn.getAttribute('data-group');
            const select = document.getElementById('add-model-' + groupId);
            if (!select.value) return;
            const [modelId, modelName] = select.value.split('|').map(decodeURIComponent);
            if (!groupConfig[groupId].models.find(m => m.modelId === modelId)) groupConfig[groupId].models.push({{ modelId, modelName }});
            renderMappings();
        }}

        function removeModelByIdx(el) {{
            const groupId = el.getAttribute('data-group'), idx = parseInt(el.getAttribute('data-idx'), 10);
            if (groupConfig[groupId]) {{ groupConfig[groupId].models.splice(idx, 1); renderMappings(); }}
        }}

        function renderModels() {{
            const tbody = document.getElementById('models-body');
            if (models.length === 0) {{ tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:#888;padding:40px;">No models available</td></tr>'; return; }}
            tbody.innerHTML = models.map(m => '<tr><td>' + m.modelName + '</td><td><code style="font-size:12px;">' + m.modelId + '</code></td><td><span class="badge badge-success">' + m.type + '</span></td></tr>').join('');
        }}

        function renderPolicies() {{
            const dtl = document.getElementById('disabled-tools-list');
            dtl.innerHTML = policies.disabledBuiltinTools.length === 0 ? '<span style="color:#888;">None - all tools enabled</span>' : policies.disabledBuiltinTools.map((t, i) => '<span class="tool-tag blocked">' + escapeHtml(t) + ' <span class="remove" onclick="removeDisabledTool(' + i + ')">&times;</span></span>').join('');

            const tpl = document.getElementById('tool-policies-list');
            const pe = Object.entries(policies.builtinToolPolicy);
            tpl.innerHTML = pe.length === 0 ? '<p style="color:#888;font-size:13px;">No custom tool policies.</p>' : pe.map(([t, p]) => '<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid #eee;"><span>' + escapeHtml(t) + '</span><span class="tool-tag ' + escapeHtml(p) + '">' + escapeHtml(p) + ' <span class="remove" onclick="removeToolPolicy(' + escapeHtml(JSON.stringify(t)) + ')">&times;</span></span></div>').join('');

            ['isLocalDevMcpEnabled', 'isDesktopExtensionEnabled', 'isDesktopExtensionSignatureRequired', 'coworkTabEnabled', 'disableBundledSkills', 'disableDeploymentModeChooser'].forEach(key => {{
                const el = document.getElementById('policy-' + key);
                el.checked = policies[key];
                el.onchange = function() {{ policies[key] = this.checked; }};
            }});

            const fl = document.getElementById('allowed-folders-list');
            fl.innerHTML = policies.allowedWorkspaceFolders.length === 0 ? '<span style="color:#888;">No restrictions</span>' : policies.allowedWorkspaceFolders.map((f, i) => '<span class="tool-tag">' + (f.path || f) + ' <span class="remove" onclick="removeAllowedFolder(' + i + ')">&times;</span></span>').join(' ');

            const el = document.getElementById('egress-hosts-list');
            el.innerHTML = policies.coworkEgressAllowedHosts.length === 0 ? '<span style="color:#888;">No restrictions</span>' : policies.coworkEgressAllowedHosts.map((h, i) => '<span class="tool-tag">' + h + ' <span class="remove" onclick="removeEgressHost(' + i + ')">&times;</span></span>').join(' ');

            const bootstrapCheckbox = document.getElementById('policy-bootstrapUrlOverrideEnabled');
            const bootstrapFields = document.getElementById('bootstrap-url-override-fields');
            const bootstrapProtocol = document.getElementById('bootstrap-url-override-protocol');
            const bootstrapHost = document.getElementById('bootstrap-url-override-host');
            const bootstrapPort = document.getElementById('bootstrap-url-override-port');
            bootstrapCheckbox.checked = policies.bootstrapUrlOverrideEnabled;
            bootstrapFields.style.display = policies.bootstrapUrlOverrideEnabled ? 'flex' : 'none';
            bootstrapProtocol.value = policies.bootstrapUrlOverrideProtocol || 'https';
            bootstrapHost.value = policies.bootstrapUrlOverrideHost || '';
            bootstrapPort.value = policies.bootstrapUrlOverridePort || '';
            bootstrapCheckbox.onchange = function() {{ policies.bootstrapUrlOverrideEnabled = this.checked; bootstrapFields.style.display = this.checked ? 'flex' : 'none'; }};
            bootstrapProtocol.onchange = function() {{ policies.bootstrapUrlOverrideProtocol = this.value; }};
            bootstrapHost.onchange = function() {{ policies.bootstrapUrlOverrideHost = this.value.trim(); }};
            bootstrapPort.onchange = function() {{ policies.bootstrapUrlOverridePort = this.value.trim(); }};
        }}

        function addDisabledTool() {{ const s = document.getElementById('add-disabled-tool'); if (s.value && !policies.disabledBuiltinTools.includes(s.value)) {{ policies.disabledBuiltinTools.push(s.value); s.value = ''; renderPolicies(); }} }}
        function removeDisabledTool(i) {{ policies.disabledBuiltinTools.splice(i, 1); renderPolicies(); }}
        function addToolPolicy() {{ const t = document.getElementById('add-tool-policy-name').value, p = document.getElementById('add-tool-policy-value').value; if (t) {{ policies.builtinToolPolicy[t] = p; document.getElementById('add-tool-policy-name').value = ''; renderPolicies(); }} }}
        function removeToolPolicy(t) {{ delete policies.builtinToolPolicy[t]; renderPolicies(); }}
        function addAllowedFolder() {{ const v = document.getElementById('add-folder-path').value.trim(); if (v) {{ policies.allowedWorkspaceFolders.push({{ path: v }}); document.getElementById('add-folder-path').value = ''; renderPolicies(); }} }}
        function removeAllowedFolder(i) {{ policies.allowedWorkspaceFolders.splice(i, 1); renderPolicies(); }}
        function addEgressHost() {{ const v = document.getElementById('add-egress-host').value.trim(); if (v && !policies.coworkEgressAllowedHosts.includes(v)) {{ policies.coworkEgressAllowedHosts.push(v); document.getElementById('add-egress-host').value = ''; renderPolicies(); }} }}
        function removeEgressHost(i) {{ policies.coworkEgressAllowedHosts.splice(i, 1); renderPolicies(); }}

        function renderMcpServers() {{
            const md = document.getElementById('managed-mcp-servers');
            md.innerHTML = managedMcpServers.length === 0 ? '<p style="color:#888;">No remote MCP servers configured.</p>' : managedMcpServers.map((s, i) => '<div class="card"><div class="card-header"><h5>' + s.name + '</h5><div><span class="badge badge-success">Remote</span> <button class="btn btn-danger btn-sm" onclick="removeManagedMcp(' + i + ')">Remove</button></div></div><div class="card-body"><strong>URL:</strong> <code>' + s.url + '</code>' + (s.description ? '<br>' + s.description : '') + '</div></div>').join('');

            const td = document.getElementById('mcp-templates');
            td.innerHTML = mcpServerTemplates.length === 0 ? '<p style="color:#888;">No local MCP templates configured.</p>' : mcpServerTemplates.map((s, i) => '<div class="card"><div class="card-header"><h5>' + s.name + '</h5><div><span class="badge badge-warning">Local</span> <button class="btn btn-danger btn-sm" onclick="removeMcpTemplate(' + i + ')">Remove</button></div></div><div class="card-body"><strong>Command:</strong> <code>' + s.command + ' ' + (s.args || []).join(' ') + '</code></div></div>').join('');
        }}

        function addManagedMcpServer() {{
            const n = document.getElementById('new-mcp-name').value.trim(), u = document.getElementById('new-mcp-url').value.trim(), d = document.getElementById('new-mcp-description').value.trim();
            if (!n || !u) {{ alert('Name and URL required'); return; }}
            managedMcpServers.push({{ name: n, transport: 'http', url: u, description: d, toolPolicy: {{ '*': 'allow' }} }});
            document.getElementById('new-mcp-name').value = ''; document.getElementById('new-mcp-url').value = ''; document.getElementById('new-mcp-description').value = '';
            renderMcpServers();
        }}
        function removeManagedMcp(i) {{ managedMcpServers.splice(i, 1); renderMcpServers(); }}

        const MCP_TEMPLATES = {{
            'github': {{ name: 'github', command: '/usr/local/bin/npx', args: ['-y', '@modelcontextprotocol/server-github'], env: {{ 'PATH': '/usr/local/bin:/usr/bin', 'GITHUB_PERSONAL_ACCESS_TOKEN': '<user-provided>' }} }},
            'slack': {{ name: 'slack', command: '/usr/local/bin/npx', args: ['-y', '@anthropic/mcp-slack-server'], env: {{ 'PATH': '/usr/local/bin:/usr/bin', 'SLACK_BOT_TOKEN': '<user-provided>', 'SLACK_TEAM_ID': '<user-provided>' }} }},
            'filesystem': {{ name: 'filesystem', command: '/usr/local/bin/npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '~/Projects'], env: {{ 'PATH': '/usr/local/bin:/usr/bin' }} }},
            'brave-search': {{ name: 'brave-search', command: '/usr/local/bin/npx', args: ['-y', '@anthropic/mcp-brave-search'], env: {{ 'PATH': '/usr/local/bin:/usr/bin', 'BRAVE_API_KEY': '<user-provided>' }} }},
            'postgres': {{ name: 'postgres', command: '/usr/local/bin/npx', args: ['-y', '@modelcontextprotocol/server-postgres', 'postgresql://localhost/mydb'], env: {{ 'PATH': '/usr/local/bin:/usr/bin' }} }},
            'custom': {{ name: 'custom-server', command: '/path/to/server', args: [], env: {{ 'PATH': '/usr/local/bin:/usr/bin' }} }}
        }};
        function addMcpTemplate(t) {{ if (MCP_TEMPLATES[t]) {{ mcpServerTemplates.push({{ ...MCP_TEMPLATES[t] }}); renderMcpServers(); }} }}

        function addLocalMcpServer() {{
            const n = document.getElementById('new-local-mcp-name').value.trim(), c = document.getElementById('new-local-mcp-command').value.trim();
            if (!n || !c) {{ alert('Name and command required'); return; }}
            const args = document.getElementById('new-local-mcp-args').value.trim().split('\\n').map(a => a.trim()).filter(Boolean);
            const env = {{}};
            document.getElementById('new-local-mcp-env').value.trim().split('\\n').forEach(l => {{ const [k, ...v] = l.split('='); if (k && v.length) env[k.trim()] = v.join('=').trim(); }});
            mcpServerTemplates.push({{ name: n, command: c, args, env }});
            document.getElementById('new-local-mcp-name').value = ''; document.getElementById('new-local-mcp-command').value = ''; document.getElementById('new-local-mcp-args').value = ''; document.getElementById('new-local-mcp-env').value = '';
            renderMcpServers();
        }}
        function removeMcpTemplate(i) {{ mcpServerTemplates.splice(i, 1); renderMcpServers(); }}

        function updateDeploySummary() {{
            const gc = Object.values(groupConfig).filter(g => g.models.length > 0).length;
            const pc = policies.disabledBuiltinTools.length + Object.keys(policies.builtinToolPolicy).length + policies.allowedWorkspaceFolders.length + policies.coworkEgressAllowedHosts.length;
            const mc = managedMcpServers.length + mcpServerTemplates.length;
            document.getElementById('summary-groups').textContent = gc;
            document.getElementById('summary-policies').textContent = pc;
            document.getElementById('summary-mcp').textContent = mc;
        }}

        function previewConfig() {{
            const preview = document.getElementById('config-preview');
            if (preview.style.display === 'block') {{
                preview.style.display = 'none';
            }} else {{
                const config = buildFullConfig();
                preview.textContent = JSON.stringify(config, null, 2);
                preview.style.display = 'block';
            }}
        }}

        function buildFullConfig() {{
            const mappings = [];
            for (const [groupId, gc] of Object.entries(groupConfig)) {{
                if (gc.models.length === 0) continue;
                mappings.push({{ groupId, groupName: gc.groupName, roleName: gc.permissionSetName || gc.groupName.replace(/-/g, ''), models: gc.models, createNew: !gc.permissionSetName }});
            }}
            return {{ mappings, policies, managedMcpServers, mcpServerTemplates }};
        }}

        async function deployConfig() {{
            const config = buildFullConfig();
            if (config.mappings.length === 0) {{ showStatus('Please add at least one model to a group', 'error'); return; }}
            showStatus('Deploying configuration... This may take a minute.', 'info');
            document.querySelector('.main-content').classList.add('loading');
            try {{
                const res = await fetch('/admin/api/deploy', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(config) }});
                const data = await res.json();
                if (data.success) {{
                    let msg = 'Deployment complete!<br><br>';
                    (data.results || []).forEach(r => {{ msg += (r.status === 'success' ? '&#10003;' : '&#10007;') + ' ' + r.group + ': ' + (r.model || '') + '<br>'; if (r.error) msg += '&nbsp;&nbsp;Error: ' + r.error + '<br>'; }});
                    showStatus(msg, 'success');
                    setTimeout(() => location.reload(), 2000);
                }} else showStatus('Error: ' + (data.error || 'Unknown error'), 'error');
            }} catch (e) {{ showStatus('Error: ' + e.message, 'error'); }}
            finally {{ document.querySelector('.main-content').classList.remove('loading'); }}
        }}

        function showStatus(msg, type) {{ const s = document.getElementById('status'); s.innerHTML = msg; s.className = 'status ' + type; }}

        async function viewPolicy(psName) {{
            try {{
                const res = await fetch('/admin/api/permission-set/' + encodeURIComponent(psName));
                const data = await res.json();
                if (data.error) {{ alert('Error: ' + data.error); return; }}
                const policy = data.inlinePolicy ? JSON.stringify(data.inlinePolicy, null, 2) : 'No inline policy';
                const modal = document.createElement('div');
                modal.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);display:flex;justify-content:center;align-items:center;z-index:1000;';
                modal.innerHTML = '<div style="background:white;padding:30px;border-radius:12px;max-width:800px;max-height:80vh;overflow:auto;"><h3 style="margin-bottom:15px;">Permission Set: ' + escapeHtml(psName) + '</h3><p><strong>Description:</strong> ' + escapeHtml(data.description || 'N/A') + '</p><p><strong>Session Duration:</strong> ' + escapeHtml(data.sessionDuration) + '</p><h4 style="margin-top:15px;">Inline Policy:</h4><pre style="background:#1a1a2e;color:#e0e0e0;padding:15px;border-radius:8px;overflow:auto;font-size:12px;">' + escapeHtml(policy) + '</pre><button class="btn btn-primary" style="margin-top:15px;" onclick="this.parentElement.parentElement.remove()">Close</button></div>';
                document.body.appendChild(modal);
                modal.onclick = function(e) {{ if (e.target === modal) modal.remove(); }};
            }} catch (e) {{ alert('Error: ' + e.message); }}
        }}

        async function saveDraft(page) {{
            const statusEl = document.getElementById(page + '-save-status');
            statusEl.className = 'save-status saving';
            statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg> Saving...';

            const config = buildFullConfig();
            try {{
                const res = await fetch('/admin/api/config', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(config)
                }});
                const data = await res.json();
                if (data.success) {{
                    statusEl.className = 'save-status saved';
                    statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Draft saved';
                    setTimeout(() => {{ statusEl.innerHTML = ''; statusEl.className = 'save-status'; }}, 3000);
                }} else {{
                    statusEl.className = 'save-status error';
                    statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Error: ' + (data.error || 'Failed to save');
                }}
            }} catch (e) {{
                statusEl.className = 'save-status error';
                statusEl.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg> Error: ' + e.message;
            }}
        }}

        init();
    </script>
</body>
</html>"""
    )


# =============================================================================
# Lambda entry point (invoked via ALB target group, /admin* path only)
# =============================================================================


def lambda_handler(event, context):
    try:
        path = event.get("path", "/admin")
        http_method = event.get("httpMethod", "GET")
        headers = event.get("headers", {}) or {}
        body = event.get("body", "") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8")

        # CloudFront mode: no ALB auth header — resolve identity from the
        # shared session cookie, and redirect unauthenticated callers into
        # the Cognito login flow. ALB mode is unchanged (trusts the header).
        if ENABLE_CLOUDFRONT:
            cookie_header = headers.get("cookie", headers.get("Cookie", ""))
            session_info = validate_session(_parse_cookies(cookie_header).get("session", ""))
            if not session_info:
                return redirect_to_login()
            user_email = session_info.get("email", "")
        else:
            user_email = extract_user_email(headers)
        if not user_email:
            return html_response("<html><body><h1>Authentication required</h1></body></html>", 401)

        user_groups = get_user_idc_groups(user_email)
        is_admin = any(ADMIN_GROUP.lower() == g.lower() for g in user_groups)
        if not is_admin:
            return html_response(
                f"<html><body><h1>Access Denied</h1><p>Admin access required.</p>"
                f"<p>Email: {esc(user_email)}</p><p>Groups: {esc(user_groups)}</p></body></html>",
                403,
            )

        if http_method == "POST" and not verify_request_origin(headers):
            return json_response({"error": "Invalid request origin"}, 403)

        if path == "/admin" or path == "/admin/":
            return serve_admin_page(user_email)
        elif path == "/admin/api/groups":
            return api_list_groups()
        elif path == "/admin/api/models":
            return api_list_models()
        elif path == "/admin/api/config":
            return api_get_config() if http_method == "GET" else api_save_config(body)
        elif path == "/admin/api/permission-sets":
            return api_list_permission_sets()
        elif path.startswith("/admin/api/permission-set/"):
            ps_name = unquote(path.split("/admin/api/permission-set/", 1)[-1])
            return api_get_permission_set_details(ps_name)
        elif path == "/admin/api/deploy" and http_method == "POST":
            return api_deploy_config(body)

        return html_response("<html><body><h1>404 Not Found</h1></body></html>", 404)

    except Exception:
        import traceback

        print(f"Error: {traceback.format_exc()}")
        return html_response(
            "<html><body><h1>Internal Server Error</h1><p>Something went wrong. Please try again later.</p></body></html>",
            500,
        )
