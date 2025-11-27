# ABOUTME: Lambda function for real-time quota checking before credential issuance
# ABOUTME: Returns allowed/blocked status based on user quota policy and current usage

import json
import boto3
import os
from datetime import datetime, timezone
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

# Initialize clients
dynamodb = boto3.resource("dynamodb")

# Configuration from environment
QUOTA_TABLE = os.environ.get("QUOTA_TABLE", "UserQuotaMetrics")
POLICIES_TABLE = os.environ.get("POLICIES_TABLE", "QuotaPolicies")

# DynamoDB tables
quota_table = dynamodb.Table(QUOTA_TABLE)
policies_table = dynamodb.Table(POLICIES_TABLE)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def lambda_handler(event, context):
    """
    Real-time quota check for credential issuance.

    Query parameters:
        email: User's email address (required)
        groups: Comma-separated list of group names (optional)

    Returns:
        JSON response with allowed status and usage details
    """
    try:
        # Parse query parameters
        query_params = event.get("queryStringParameters") or {}
        email = query_params.get("email")
        groups_param = query_params.get("groups", "")
        groups = [g.strip() for g in groups_param.split(",") if g.strip()]

        if not email:
            return build_response(400, {
                "error": "Missing required parameter: email",
                "allowed": True,  # Fail-open on bad request
                "reason": "invalid_request"
            })

        # 1. Resolve the effective quota policy for this user
        policy = resolve_quota_for_user(email, groups)

        if policy is None:
            # No policy = unlimited (quota monitoring disabled)
            return build_response(200, {
                "allowed": True,
                "reason": "no_policy",
                "enforcement_mode": None,
                "usage": None,
                "policy": None,
                "unblock_status": None,
                "message": "No quota policy configured - unlimited access"
            })

        # 2. Check for active unblock override
        unblock_status = get_unblock_status(email)
        if unblock_status and unblock_status.get("is_unblocked"):
            return build_response(200, {
                "allowed": True,
                "reason": "unblocked",
                "enforcement_mode": policy.get("enforcement_mode", "alert"),
                "usage": get_user_usage_summary(email, policy),
                "policy": {
                    "type": policy.get("policy_type"),
                    "identifier": policy.get("identifier")
                },
                "unblock_status": unblock_status,
                "message": f"Access granted - temporarily unblocked until {unblock_status.get('expires_at')}"
            })

        # 3. Get current usage
        usage = get_user_usage(email)
        usage_summary = build_usage_summary(usage, policy)

        # 4. Check if enforcement mode is "block"
        enforcement_mode = policy.get("enforcement_mode", "alert")

        if enforcement_mode != "block":
            # Alert-only mode - always allow
            return build_response(200, {
                "allowed": True,
                "reason": "within_quota",
                "enforcement_mode": enforcement_mode,
                "usage": usage_summary,
                "policy": {
                    "type": policy.get("policy_type"),
                    "identifier": policy.get("identifier")
                },
                "unblock_status": {"is_unblocked": False},
                "message": "Access granted - enforcement mode is alert-only"
            })

        # 5. Check limits (monthly, daily, cost)
        monthly_tokens = usage.get("total_tokens", 0)
        daily_tokens = usage.get("daily_tokens", 0)
        estimated_cost = usage.get("estimated_cost", 0)

        monthly_limit = policy.get("monthly_token_limit", 0)
        daily_limit = policy.get("daily_token_limit")
        cost_limit = policy.get("monthly_cost_limit")

        # Check monthly token limit
        if monthly_limit > 0 and monthly_tokens >= monthly_limit:
            return build_response(200, {
                "allowed": False,
                "reason": "monthly_exceeded",
                "enforcement_mode": enforcement_mode,
                "usage": usage_summary,
                "policy": {
                    "type": policy.get("policy_type"),
                    "identifier": policy.get("identifier")
                },
                "unblock_status": {"is_unblocked": False},
                "message": f"Monthly quota exceeded: {int(monthly_tokens):,} / {int(monthly_limit):,} tokens ({monthly_tokens/monthly_limit*100:.1f}%). Contact your administrator for assistance."
            })

        # Check daily token limit (if configured)
        if daily_limit and daily_limit > 0 and daily_tokens >= daily_limit:
            return build_response(200, {
                "allowed": False,
                "reason": "daily_exceeded",
                "enforcement_mode": enforcement_mode,
                "usage": usage_summary,
                "policy": {
                    "type": policy.get("policy_type"),
                    "identifier": policy.get("identifier")
                },
                "unblock_status": {"is_unblocked": False},
                "message": f"Daily quota exceeded: {int(daily_tokens):,} / {int(daily_limit):,} tokens ({daily_tokens/daily_limit*100:.1f}%). Quota resets at UTC midnight."
            })

        # Check cost limit (if configured)
        if cost_limit and cost_limit > 0 and estimated_cost >= float(cost_limit):
            return build_response(200, {
                "allowed": False,
                "reason": "cost_exceeded",
                "enforcement_mode": enforcement_mode,
                "usage": usage_summary,
                "policy": {
                    "type": policy.get("policy_type"),
                    "identifier": policy.get("identifier")
                },
                "unblock_status": {"is_unblocked": False},
                "message": f"Monthly cost limit exceeded: ${estimated_cost:.2f} / ${float(cost_limit):.2f} ({estimated_cost/float(cost_limit)*100:.1f}%). Contact your administrator for assistance."
            })

        # All checks passed - access allowed
        return build_response(200, {
            "allowed": True,
            "reason": "within_quota",
            "enforcement_mode": enforcement_mode,
            "usage": usage_summary,
            "policy": {
                "type": policy.get("policy_type"),
                "identifier": policy.get("identifier")
            },
            "unblock_status": {"is_unblocked": False},
            "message": "Access granted - within quota limits"
        })

    except Exception as e:
        print(f"Error during quota check: {str(e)}")
        import traceback
        traceback.print_exc()

        # Fail-open on errors
        return build_response(200, {
            "allowed": True,
            "reason": "check_failed",
            "enforcement_mode": None,
            "usage": None,
            "policy": None,
            "unblock_status": None,
            "message": f"Quota check failed (fail-open): {str(e)}"
        })


def build_response(status_code: int, body: dict) -> dict:
    """Build API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        },
        "body": json.dumps(body, cls=DecimalEncoder)
    }


def resolve_quota_for_user(email: str, groups: list) -> dict | None:
    """
    Resolve the effective quota policy for a user.
    Precedence: user-specific > group (most restrictive) > default

    Returns:
        Policy dict or None if no policy applies (unlimited).
    """
    # 1. Check for user-specific policy
    user_policy = get_policy("user", email)
    if user_policy and user_policy.get("enabled", True):
        return user_policy

    # 2. Check for group policies (apply most restrictive)
    if groups:
        group_policies = []
        for group in groups:
            group_policy = get_policy("group", group)
            if group_policy and group_policy.get("enabled", True):
                group_policies.append(group_policy)

        if group_policies:
            # Most restrictive = lowest monthly_token_limit
            return min(group_policies, key=lambda p: p.get("monthly_token_limit", float("inf")))

    # 3. Fall back to default policy
    default_policy = get_policy("default", "default")
    if default_policy and default_policy.get("enabled", True):
        return default_policy

    # 4. No policy = unlimited
    return None


def get_policy(policy_type: str, identifier: str) -> dict | None:
    """Get a policy from DynamoDB."""
    pk = f"POLICY#{policy_type}#{identifier}"

    try:
        response = policies_table.get_item(Key={"pk": pk, "sk": "CURRENT"})
        item = response.get("Item")

        if not item:
            return None

        return {
            "policy_type": item.get("policy_type"),
            "identifier": item.get("identifier"),
            "monthly_token_limit": int(item.get("monthly_token_limit", 0)),
            "daily_token_limit": int(item.get("daily_token_limit", 0)) if item.get("daily_token_limit") else None,
            "monthly_cost_limit": float(item.get("monthly_cost_limit", 0)) if item.get("monthly_cost_limit") else None,
            "warning_threshold_80": int(item.get("warning_threshold_80", 0)),
            "warning_threshold_90": int(item.get("warning_threshold_90", 0)),
            "enforcement_mode": item.get("enforcement_mode", "alert"),
            "enabled": item.get("enabled", True),
        }
    except Exception as e:
        print(f"Error getting policy {policy_type}:{identifier}: {e}")
        return None


def get_unblock_status(email: str) -> dict:
    """Check if user has an active unblock override."""
    pk = f"USER#{email}"
    sk = "UNBLOCK#CURRENT"

    try:
        response = quota_table.get_item(Key={"pk": pk, "sk": sk})
        item = response.get("Item")

        if not item:
            return {"is_unblocked": False}

        # Check if unblock has expired
        expires_at = item.get("expires_at")
        if expires_at:
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_dt:
                return {"is_unblocked": False, "expired": True}

        return {
            "is_unblocked": True,
            "expires_at": expires_at,
            "unblocked_by": item.get("unblocked_by"),
            "unblocked_at": item.get("unblocked_at"),
            "reason": item.get("reason"),
            "duration_type": item.get("duration_type")
        }
    except Exception as e:
        print(f"Error checking unblock status for {email}: {e}")
        return {"is_unblocked": False, "error": str(e)}


def get_user_usage(email: str) -> dict:
    """Get current usage for a user in the current month."""
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")
    current_date = now.strftime("%Y-%m-%d")

    pk = f"USER#{email}"
    sk = f"MONTH#{month_prefix}"

    try:
        response = quota_table.get_item(Key={"pk": pk, "sk": sk})
        item = response.get("Item")

        if not item:
            return {
                "total_tokens": 0,
                "daily_tokens": 0,
                "daily_date": current_date,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_tokens": 0,
                "estimated_cost": 0
            }

        # Check if daily tokens need to be reset (different day)
        daily_date = item.get("daily_date")
        daily_tokens = float(item.get("daily_tokens", 0))

        if daily_date != current_date:
            # Day has changed, daily tokens should be 0 for the new day
            daily_tokens = 0

        return {
            "total_tokens": float(item.get("total_tokens", 0)),
            "daily_tokens": daily_tokens,
            "daily_date": daily_date,
            "input_tokens": float(item.get("input_tokens", 0)),
            "output_tokens": float(item.get("output_tokens", 0)),
            "cache_tokens": float(item.get("cache_tokens", 0)),
            "estimated_cost": float(item.get("estimated_cost", 0))
        }
    except Exception as e:
        print(f"Error getting usage for {email}: {e}")
        return {
            "total_tokens": 0,
            "daily_tokens": 0,
            "daily_date": current_date,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_tokens": 0,
            "estimated_cost": 0
        }


def build_usage_summary(usage: dict, policy: dict) -> dict:
    """Build usage summary with percentages."""
    monthly_tokens = usage.get("total_tokens", 0)
    daily_tokens = usage.get("daily_tokens", 0)
    estimated_cost = usage.get("estimated_cost", 0)

    monthly_limit = policy.get("monthly_token_limit", 0)
    daily_limit = policy.get("daily_token_limit")
    cost_limit = policy.get("monthly_cost_limit")

    summary = {
        "monthly_tokens": int(monthly_tokens),
        "monthly_limit": monthly_limit,
        "monthly_percent": round(monthly_tokens / monthly_limit * 100, 1) if monthly_limit > 0 else 0,
        "daily_tokens": int(daily_tokens),
        "estimated_cost": round(estimated_cost, 2)
    }

    if daily_limit:
        summary["daily_limit"] = daily_limit
        summary["daily_percent"] = round(daily_tokens / daily_limit * 100, 1) if daily_limit > 0 else 0

    if cost_limit:
        summary["cost_limit"] = float(cost_limit)
        summary["cost_percent"] = round(estimated_cost / float(cost_limit) * 100, 1) if cost_limit > 0 else 0

    return summary


def get_user_usage_summary(email: str, policy: dict) -> dict:
    """Get user usage and build summary in one call."""
    usage = get_user_usage(email)
    return build_usage_summary(usage, policy)
