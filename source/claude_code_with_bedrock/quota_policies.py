# ABOUTME: CRUD operations for quota policy management
# ABOUTME: Provides functions for creating, reading, updating, and deleting quota policies in DynamoDB

"""Quota policy CRUD operations for fine-grained quota management."""

from datetime import datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .models import EnforcementMode, PolicyType, QuotaPolicy


class QuotaPolicyError(Exception):
    """Base exception for quota policy operations."""

    pass


class PolicyNotFoundError(QuotaPolicyError):
    """Raised when a policy is not found."""

    pass


class PolicyAlreadyExistsError(QuotaPolicyError):
    """Raised when attempting to create a policy that already exists."""

    pass


class QuotaPolicyManager:
    """Manager for quota policy CRUD operations."""

    def __init__(self, table_name: str, region: str | None = None):
        """Initialize the quota policy manager.

        Args:
            table_name: Name of the QuotaPolicies DynamoDB table.
            region: AWS region. If None, uses default region.
        """
        self.table_name = table_name
        self.dynamodb = boto3.resource("dynamodb", region_name=region)
        self.table = self.dynamodb.Table(table_name)

    def _make_pk(self, policy_type: PolicyType, identifier: str) -> str:
        """Generate partition key for a policy.

        Args:
            policy_type: Type of policy (user, group, default).
            identifier: Policy identifier (email, group name, or "default").

        Returns:
            Formatted partition key.
        """
        return f"POLICY#{policy_type.value}#{identifier}"

    def create_policy(
        self,
        policy_type: PolicyType,
        identifier: str,
        monthly_token_limit: int,
        daily_token_limit: int | None = None,
        monthly_cost_limit: Decimal | None = None,
        warning_threshold_80: int | None = None,
        warning_threshold_90: int | None = None,
        enforcement_mode: EnforcementMode = EnforcementMode.ALERT,
        enabled: bool = True,
        created_by: str | None = None,
    ) -> QuotaPolicy:
        """Create a new quota policy.

        Args:
            policy_type: Type of policy (user, group, default).
            identifier: Policy identifier (email for user, group name for group, "default" for default).
            monthly_token_limit: Monthly token limit.
            daily_token_limit: Optional daily token limit.
            monthly_cost_limit: Optional monthly cost limit in USD.
            warning_threshold_80: Optional 80% warning threshold. Auto-calculated if not provided.
            warning_threshold_90: Optional 90% warning threshold. Auto-calculated if not provided.
            enforcement_mode: Alert or block mode (default: alert).
            enabled: Whether the policy is enabled (default: True).
            created_by: Admin email who created the policy.

        Returns:
            Created QuotaPolicy object.

        Raises:
            PolicyAlreadyExistsError: If policy already exists.
            QuotaPolicyError: For other DynamoDB errors.
        """
        # Validate identifier for default policy
        if policy_type == PolicyType.DEFAULT and identifier != "default":
            identifier = "default"

        # Auto-calculate warning thresholds if not provided
        if warning_threshold_80 is None:
            warning_threshold_80 = int(monthly_token_limit * 0.8)
        if warning_threshold_90 is None:
            warning_threshold_90 = int(monthly_token_limit * 0.9)

        now = datetime.utcnow().isoformat()
        policy = QuotaPolicy(
            policy_type=policy_type,
            identifier=identifier,
            monthly_token_limit=monthly_token_limit,
            daily_token_limit=daily_token_limit,
            monthly_cost_limit=monthly_cost_limit,
            warning_threshold_80=warning_threshold_80,
            warning_threshold_90=warning_threshold_90,
            enforcement_mode=enforcement_mode,
            enabled=enabled,
            created_at=now,
            updated_at=now,
            created_by=created_by,
        )

        item = policy.to_dynamodb_item()
        item["pk"] = self._make_pk(policy_type, identifier)
        item["sk"] = "CURRENT"

        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise PolicyAlreadyExistsError(
                    f"Policy already exists for {policy_type.value}:{identifier}"
                )
            raise QuotaPolicyError(f"Failed to create policy: {e}") from e

        return policy

    def get_policy(
        self, policy_type: PolicyType, identifier: str
    ) -> QuotaPolicy | None:
        """Get a policy by type and identifier.

        Args:
            policy_type: Type of policy (user, group, default).
            identifier: Policy identifier.

        Returns:
            QuotaPolicy object or None if not found.
        """
        pk = self._make_pk(policy_type, identifier)

        try:
            response = self.table.get_item(Key={"pk": pk, "sk": "CURRENT"})
        except ClientError as e:
            raise QuotaPolicyError(f"Failed to get policy: {e}") from e

        item = response.get("Item")
        if not item:
            return None

        return QuotaPolicy.from_dynamodb_item(item)

    def update_policy(
        self,
        policy_type: PolicyType,
        identifier: str,
        monthly_token_limit: int | None = None,
        daily_token_limit: int | None = None,
        monthly_cost_limit: Decimal | None = None,
        warning_threshold_80: int | None = None,
        warning_threshold_90: int | None = None,
        enforcement_mode: EnforcementMode | None = None,
        enabled: bool | None = None,
    ) -> QuotaPolicy:
        """Update an existing policy.

        Args:
            policy_type: Type of policy.
            identifier: Policy identifier.
            monthly_token_limit: New monthly token limit (optional).
            daily_token_limit: New daily token limit (optional).
            monthly_cost_limit: New monthly cost limit (optional).
            warning_threshold_80: New 80% threshold (optional).
            warning_threshold_90: New 90% threshold (optional).
            enforcement_mode: New enforcement mode (optional).
            enabled: New enabled status (optional).

        Returns:
            Updated QuotaPolicy object.

        Raises:
            PolicyNotFoundError: If policy doesn't exist.
            QuotaPolicyError: For other DynamoDB errors.
        """
        # First get the existing policy
        existing = self.get_policy(policy_type, identifier)
        if not existing:
            raise PolicyNotFoundError(
                f"Policy not found for {policy_type.value}:{identifier}"
            )

        # Build update expression
        update_parts = []
        expression_values: dict[str, Any] = {}
        expression_names: dict[str, str] = {}

        now = datetime.utcnow().isoformat()
        update_parts.append("#updated_at = :updated_at")
        expression_values[":updated_at"] = now
        expression_names["#updated_at"] = "updated_at"

        if monthly_token_limit is not None:
            update_parts.append("monthly_token_limit = :monthly_limit")
            expression_values[":monthly_limit"] = monthly_token_limit
            # Auto-update thresholds if not explicitly provided
            if warning_threshold_80 is None:
                warning_threshold_80 = int(monthly_token_limit * 0.8)
            if warning_threshold_90 is None:
                warning_threshold_90 = int(monthly_token_limit * 0.9)

        if daily_token_limit is not None:
            update_parts.append("daily_token_limit = :daily_limit")
            expression_values[":daily_limit"] = daily_token_limit

        if monthly_cost_limit is not None:
            update_parts.append("monthly_cost_limit = :cost_limit")
            expression_values[":cost_limit"] = monthly_cost_limit

        if warning_threshold_80 is not None:
            update_parts.append("warning_threshold_80 = :warn_80")
            expression_values[":warn_80"] = warning_threshold_80

        if warning_threshold_90 is not None:
            update_parts.append("warning_threshold_90 = :warn_90")
            expression_values[":warn_90"] = warning_threshold_90

        if enforcement_mode is not None:
            update_parts.append("enforcement_mode = :mode")
            expression_values[":mode"] = enforcement_mode.value

        if enabled is not None:
            update_parts.append("#enabled = :enabled")
            expression_values[":enabled"] = enabled
            expression_names["#enabled"] = "enabled"

        pk = self._make_pk(policy_type, identifier)

        try:
            response = self.table.update_item(
                Key={"pk": pk, "sk": "CURRENT"},
                UpdateExpression="SET " + ", ".join(update_parts),
                ExpressionAttributeValues=expression_values,
                ExpressionAttributeNames=expression_names if expression_names else None,
                ReturnValues="ALL_NEW",
                ConditionExpression="attribute_exists(pk)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise PolicyNotFoundError(
                    f"Policy not found for {policy_type.value}:{identifier}"
                )
            raise QuotaPolicyError(f"Failed to update policy: {e}") from e

        return QuotaPolicy.from_dynamodb_item(response["Attributes"])

    def delete_policy(self, policy_type: PolicyType, identifier: str) -> bool:
        """Delete a policy.

        Args:
            policy_type: Type of policy.
            identifier: Policy identifier.

        Returns:
            True if deleted, False if policy didn't exist.

        Raises:
            QuotaPolicyError: For DynamoDB errors.
        """
        pk = self._make_pk(policy_type, identifier)

        try:
            response = self.table.delete_item(
                Key={"pk": pk, "sk": "CURRENT"},
                ReturnValues="ALL_OLD",
            )
        except ClientError as e:
            raise QuotaPolicyError(f"Failed to delete policy: {e}") from e

        return "Attributes" in response

    def list_policies(
        self, policy_type: PolicyType | None = None
    ) -> list[QuotaPolicy]:
        """List all policies, optionally filtered by type.

        Args:
            policy_type: Optional filter by policy type.

        Returns:
            List of QuotaPolicy objects.

        Raises:
            QuotaPolicyError: For DynamoDB errors.
        """
        try:
            if policy_type:
                # Use GSI to query by policy type
                response = self.table.query(
                    IndexName="PolicyTypeIndex",
                    KeyConditionExpression="policy_type = :pt",
                    ExpressionAttributeValues={":pt": policy_type.value},
                )
            else:
                # Scan all policies (only CURRENT versions)
                response = self.table.scan(
                    FilterExpression="sk = :current",
                    ExpressionAttributeValues={":current": "CURRENT"},
                )
        except ClientError as e:
            raise QuotaPolicyError(f"Failed to list policies: {e}") from e

        policies = []
        for item in response.get("Items", []):
            # Skip non-CURRENT items when querying GSI
            if item.get("sk") != "CURRENT":
                continue
            policies.append(QuotaPolicy.from_dynamodb_item(item))

        return policies

    def resolve_quota_for_user(
        self, email: str, groups: list[str] | None = None
    ) -> QuotaPolicy | None:
        """Resolve the effective quota policy for a user.

        Precedence: user-specific > group (most restrictive) > default

        Args:
            email: User's email address.
            groups: List of group names from JWT claims.

        Returns:
            Effective QuotaPolicy or None if no policy applies (unlimited).
        """
        # 1. Check for user-specific policy
        user_policy = self.get_policy(PolicyType.USER, email)
        if user_policy and user_policy.enabled:
            return user_policy

        # 2. Check for group policies (apply most restrictive)
        if groups:
            group_policies = []
            for group in groups:
                group_policy = self.get_policy(PolicyType.GROUP, group)
                if group_policy and group_policy.enabled:
                    group_policies.append(group_policy)

            if group_policies:
                # Most restrictive = lowest monthly_token_limit
                return min(group_policies, key=lambda p: p.monthly_token_limit)

        # 3. Fall back to default policy
        default_policy = self.get_policy(PolicyType.DEFAULT, "default")
        if default_policy and default_policy.enabled:
            return default_policy

        # 4. No policy = unlimited (quota monitoring disabled for this user)
        return None

    def get_usage_summary(
        self,
        email: str,
        groups: list[str] | None = None,
        current_monthly_tokens: int = 0,
        current_daily_tokens: int = 0,
        current_monthly_cost: Decimal = Decimal("0"),
    ) -> dict[str, Any]:
        """Get usage summary with policy context for a user.

        Args:
            email: User's email address.
            groups: List of group names from JWT claims.
            current_monthly_tokens: Current monthly token usage.
            current_daily_tokens: Current daily token usage.
            current_monthly_cost: Current monthly cost in USD.

        Returns:
            Dictionary with policy and usage information.
        """
        policy = self.resolve_quota_for_user(email, groups)

        if policy is None:
            return {
                "email": email,
                "policy_applied": False,
                "policy_type": None,
                "policy_identifier": None,
                "unlimited": True,
                "monthly_tokens": current_monthly_tokens,
                "daily_tokens": current_daily_tokens,
                "monthly_cost": float(current_monthly_cost),
            }

        monthly_pct = (
            (current_monthly_tokens / policy.monthly_token_limit * 100)
            if policy.monthly_token_limit > 0
            else 0
        )

        daily_pct = None
        if policy.daily_token_limit:
            daily_pct = (
                (current_daily_tokens / policy.daily_token_limit * 100)
                if policy.daily_token_limit > 0
                else 0
            )

        cost_pct = None
        if policy.monthly_cost_limit:
            cost_pct = (
                (float(current_monthly_cost) / float(policy.monthly_cost_limit) * 100)
                if policy.monthly_cost_limit > 0
                else 0
            )

        return {
            "email": email,
            "policy_applied": True,
            "policy_type": policy.policy_type.value,
            "policy_identifier": policy.identifier,
            "unlimited": False,
            "enforcement_mode": policy.enforcement_mode.value,
            "monthly_tokens": current_monthly_tokens,
            "monthly_token_limit": policy.monthly_token_limit,
            "monthly_token_pct": round(monthly_pct, 1),
            "daily_tokens": current_daily_tokens,
            "daily_token_limit": policy.daily_token_limit,
            "daily_token_pct": round(daily_pct, 1) if daily_pct is not None else None,
            "monthly_cost": float(current_monthly_cost),
            "monthly_cost_limit": (
                float(policy.monthly_cost_limit) if policy.monthly_cost_limit else None
            ),
            "monthly_cost_pct": round(cost_pct, 1) if cost_pct is not None else None,
            "warning_threshold_80": policy.warning_threshold_80,
            "warning_threshold_90": policy.warning_threshold_90,
        }
