# ABOUTME: Lambda function that provisions per-user Bedrock Application Inference Profiles
# ABOUTME: Sole principal with bedrock:CreateInferenceProfile — users invoke this instead of calling Bedrock directly
# ABOUTME: Caller identity is verified by IAM (SigV4); email is passed in the payload and used as the profile owner

import json
import logging
import re
import hashlib

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Regions that map to the 'eu' cross-region inference profile geo prefix
_EU_REGIONS = {
    "eu-west-1", "eu-west-2", "eu-west-3",
    "eu-central-1", "eu-central-2",
    "eu-north-1", "eu-south-1", "eu-south-2",
}

# Inference profile model definitions — must stay in sync with models.py
INFERENCE_PROFILE_MODELS = {
    "opus-4-6": {
        "cross_region_profile_id": "{geo}.anthropic.claude-opus-4-6-v1",
        "enabled": True,
    },
    "sonnet-4-6": {
        "cross_region_profile_id": "{geo}.anthropic.claude-sonnet-4-6",
        "enabled": True,
    },
    "haiku-4-5": {
        "cross_region_profile_id": "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0",
        "enabled": True,
    },
}

_MAX_TAG_VALUE = 256

# Basic email validation — rejects obviously malformed inputs
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get_geo(region: str) -> str:
    return "eu" if region in _EU_REGIONS else "us"


def _get_source_arn(model_key: str, region: str) -> str:
    entry = INFERENCE_PROFILE_MODELS[model_key]
    geo = _get_geo(region)
    profile_id = entry["cross_region_profile_id"].format(geo=geo)
    return f"arn:aws:bedrock:{region}::inference-profile/{profile_id}"


def _get_profile_name(email: str, model_key: str) -> str:
    email_hash = hashlib.sha256(email.encode()).hexdigest()[:8]
    sanitized = re.sub(r"[^a-z0-9-]", "-", email.lower())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    suffix = f"-{email_hash}-{model_key}"
    max_email_len = 64 - len("claude-code-") - len(suffix)
    sanitized = sanitized[:max_email_len]
    return f"claude-code-{sanitized}{suffix}"


def _build_tags(email: str, claims: dict) -> list[dict]:
    tags = [{"key": "user.email", "value": email[:_MAX_TAG_VALUE]}]
    claim_map = {
        "custom:cost_center": "cost_center",
        "custom:department": "department",
        "custom:organization": "organization",
        "custom:team": "team",
    }
    for claim_key, tag_key in claim_map.items():
        value = claims.get(claim_key)
        if value:
            tags.append({"key": tag_key, "value": str(value)[:_MAX_TAG_VALUE]})
    return tags


def handler(event, context):
    """Provision Bedrock Application Inference Profiles for the authenticated caller.

    The function creates one Application Inference Profile per enabled model in
    INFERENCE_PROFILE_MODELS. Creation is idempotent: if a profile already exists
    it returns the existing ARN without error.

    Security model:
    - The Lambda is invoked via SDK using IAM-signed (SigV4) credentials that were
      issued only after the caller's OIDC token was validated. IAM authentication
      is the trust boundary — only users with lambda:InvokeFunction on this function
      ARN can reach this code.
    - This Lambda is the sole principal with bedrock:CreateInferenceProfile and
      bedrock:TagResource, removing those permissions from the user role entirely.
    - The email is passed in the event payload and is basic-format validated here.
      It is used exclusively to derive the deterministic profile name and tags.
    - Per-model failures are non-fatal: the function returns whatever ARNs it
      managed to create so the caller is never completely blocked.

    Expected event payload:
        { "email": "user@example.com", "claims": { ... } }

    Returns:
        { "profile_arns": { "opus-4-6": "arn:...", "sonnet-4-6": "arn:...", ... } }
    """
    region = boto3.session.Session().region_name
    bedrock = boto3.client("bedrock", region_name=region)

    # --- Input validation ---
    email = (event.get("email") or "").strip()
    if not email or not _EMAIL_RE.match(email):
        logger.error("Invalid or missing email in event payload: %r", email)
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid or missing email in payload"}),
        }

    claims = event.get("claims") or {}
    tags = _build_tags(email, claims)
    profile_arns: dict[str, str] = {}

    enabled_models = {k: v for k, v in INFERENCE_PROFILE_MODELS.items() if v.get("enabled")}

    # Build expected profile names for this user so we can match against existing ones
    expected_names: dict[str, str] = {}  # profile_name → model_key
    for model_key in enabled_models:
        expected_names[_get_profile_name(email, model_key)] = model_key

    # List all existing APPLICATION profiles and resolve any that already belong to this user
    try:
        paginator = bedrock.get_paginator("list_inference_profiles")
        for page in paginator.paginate(typeEquals="APPLICATION"):
            for p in page.get("inferenceProfileSummaries", []):
                pname = p.get("inferenceProfileName", "")
                if pname in expected_names:
                    mk = expected_names[pname]
                    profile_arns[mk] = p["inferenceProfileArn"]
                    logger.info("Found existing profile for '%s': %s", mk, p["inferenceProfileArn"])
    except Exception as e:
        logger.warning("Could not list existing inference profiles: %s", e)

    # If all profiles already exist, return immediately — no create calls needed
    if all(mk in profile_arns for mk in enabled_models):
        logger.info("All %d profiles already exist for %s — skipping creation", len(profile_arns), email)
        return {
            "statusCode": 200,
            "body": json.dumps({"profile_arns": profile_arns}),
        }

    # Create only the missing profiles
    for model_key in enabled_models:
        if model_key in profile_arns:
            continue

        profile_name = _get_profile_name(email, model_key)
        logger.info("Creating inference profile '%s' for model '%s'", profile_name, model_key)

        try:
            source_arn = _get_source_arn(model_key, region)
            response = bedrock.create_inference_profile(
                inferenceProfileName=profile_name,
                description="Claude Code inference profile",
                modelSource={"copyFrom": source_arn},
                tags=tags,
            )
            arn = response["inferenceProfileArn"]
            profile_arns[model_key] = arn
            logger.info("Created inference profile '%s': %s", model_key, arn)

        except ClientError as e:
            # Non-fatal — log and continue so other models are not blocked
            logger.warning("Could not create profile for '%s': %s", model_key, e)

        except Exception as e:
            logger.warning("Unexpected error creating profile for '%s': %s", model_key, e)

    logger.info("Returning %d profile ARN(s) for %s", len(profile_arns), email)
    return {
        "statusCode": 200,
        "body": json.dumps({"profile_arns": profile_arns}),
    }
