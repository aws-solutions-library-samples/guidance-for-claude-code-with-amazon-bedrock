# ABOUTME: CRUD operations for quota policy management
# ABOUTME: Provides functions for creating, reading, updating, and deleting quota policies in DynamoDB

"""Quota policy CRUD operations for fine-grained quota management."""

from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .models import EnforcementMode, PolicyType, QuotaPolicy


def _format_tokens(tokens: int) -> str:
    """Format token count for export.

    Args:
        tokens: Token count.

    Returns:
        Formatted string (e.g., "300M", "1.5B", "50K").
    """
    if tokens >= 1_000_000_000:
        value = tokens / 1_000_000_000
        return f"{value:.1f}B" if value != int(value) else f"{int(value)}B"
    elif tokens >= 1_000_000:
        value = tokens / 1_000_000
        return f"{value:.1f}M" if value != int(value) else f"{int(value)}M"
    elif tokens >= 1_000:
        value = tokens / 1_000
        return f"{value:.1f}K" if value != int(value) else f"{int(value)}K"
    return str(tokens)


def _parse_tokens(value: str | int) -> int:
    """Parse token value with suffix support.

    Args:
        value: Token value string (e.g., "300M", "1.5B", "50000") or integer.

    Returns:
        Integer token count.

    Raises:
        ValueError: If value cannot be parsed.
    """
    if isinstance(value, int):
        return value

    value = str(value).strip().upper()

    multipliers = {
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }

    for suffix, multiplier in multipliers.items():
        if value.endswith(suffix):
            return int(float(value[:-1]) * multiplier)

    return int(value)


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

        now = datetime.utcnow()
        policy = QuotaPolicy(
            policy_type=policy_type,
            identifier=identifier,
            monthly_token_limit=monthly_token_limit,
            daily_token_limit=daily_token_limit,
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
    ) -> dict[str, Any]:
        """Get usage summary with policy context for a user.

        Args:
            email: User's email address.
            groups: List of group names from JWT claims.
            current_monthly_tokens: Current monthly token usage.
            current_daily_tokens: Current daily token usage.

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
            "warning_threshold_80": policy.warning_threshold_80,
            "warning_threshold_90": policy.warning_threshold_90,
        }

    def export_policies(
        self, policy_type: PolicyType | None = None
    ) -> list[dict[str, Any]]:
        """Export policies as list of dicts with human-readable token values.

        Args:
            policy_type: Optional filter by policy type.

        Returns:
            List of policy dictionaries suitable for JSON/CSV export.
        """
        policies = self.list_policies(policy_type)

        exported = []
        for policy in policies:
            item: dict[str, Any] = {
                "type": policy.policy_type.value,
                "identifier": policy.identifier,
                "monthly_token_limit": _format_tokens(policy.monthly_token_limit),
                "enforcement_mode": policy.enforcement_mode.value,
                "enabled": policy.enabled,
            }

            if policy.daily_token_limit:
                item["daily_token_limit"] = _format_tokens(policy.daily_token_limit)
            else:
                item["daily_token_limit"] = ""

            exported.append(item)

        return exported

    def bulk_import_policies(
        self,
        policies: list[dict[str, Any]],
        skip_existing: bool = False,
        update_existing: bool = False,
        auto_daily: bool = False,
        burst_buffer_percent: int = 10,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Import multiple policies with conflict handling.

        Args:
            policies: List of policy dictionaries to import.
            skip_existing: Skip policies that already exist.
            update_existing: Update existing policies (upsert).
            auto_daily: Auto-calculate daily limits for policies missing daily_token_limit.
            burst_buffer_percent: Burst buffer percentage for auto-daily calculation.
            dry_run: Preview changes without actually importing.

        Returns:
            Dictionary with import results:
            {
                "created": 5,
                "updated": 2,
                "skipped": 1,
                "errors": [{"row": 3, "error": "Invalid token format"}],
                "details": [{"action": "create", "type": "user", "identifier": "..."}]
            }
        """
        results: dict[str, Any] = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "details": [],
        }

        for i, policy_dict in enumerate(policies, start=1):
            try:
                # Validate and parse policy
                parsed = self._parse_import_policy(policy_dict, i, auto_daily, burst_buffer_percent)

                # Check if policy exists
                existing = self.get_policy(parsed["policy_type"], parsed["identifier"])

                if existing:
                    if skip_existing:
                        results["skipped"] += 1
                        results["details"].append({
                            "action": "skip",
                            "type": parsed["policy_type"].value,
                            "identifier": parsed["identifier"],
                            "reason": "already exists",
                        })
                    elif update_existing:
                        if not dry_run:
                            self.update_policy(
                                policy_type=parsed["policy_type"],
                                identifier=parsed["identifier"],
                                monthly_token_limit=parsed["monthly_token_limit"],
                                daily_token_limit=parsed.get("daily_token_limit"),
                                enforcement_mode=parsed.get("enforcement_mode", EnforcementMode.ALERT),
                                enabled=parsed.get("enabled", True),
                            )
                        results["updated"] += 1
                        results["details"].append({
                            "action": "update",
                            "type": parsed["policy_type"].value,
                            "identifier": parsed["identifier"],
                            "monthly_limit": _format_tokens(parsed["monthly_token_limit"]),
                        })
                    else:
                        # Neither skip nor update - this is a conflict
                        results["errors"].append({
                            "row": i,
                            "type": parsed["policy_type"].value,
                            "identifier": parsed["identifier"],
                            "error": "Policy already exists (use --skip-existing or --update)",
                        })
                else:
                    # Create new policy
                    if not dry_run:
                        self.create_policy(
                            policy_type=parsed["policy_type"],
                            identifier=parsed["identifier"],
                            monthly_token_limit=parsed["monthly_token_limit"],
                            daily_token_limit=parsed.get("daily_token_limit"),
                            enforcement_mode=parsed.get("enforcement_mode", EnforcementMode.ALERT),
                            enabled=parsed.get("enabled", True),
                        )
                    results["created"] += 1
                    results["details"].append({
                        "action": "create",
                        "type": parsed["policy_type"].value,
                        "identifier": parsed["identifier"],
                        "monthly_limit": _format_tokens(parsed["monthly_token_limit"]),
                    })

            except (ValueError, KeyError) as e:
                results["errors"].append({
                    "row": i,
                    "error": str(e),
                })

        return results

    def _parse_import_policy(
        self,
        policy_dict: dict[str, Any],
        row_num: int,
        auto_daily: bool,
        burst_buffer_percent: int,
    ) -> dict[str, Any]:
        """Parse and validate a policy dictionary from import.

        Args:
            policy_dict: Raw policy dictionary from file.
            row_num: Row number for error reporting.
            auto_daily: Whether to auto-calculate daily limits.
            burst_buffer_percent: Burst buffer for auto-daily calculation.

        Returns:
            Parsed policy dictionary with proper types.

        Raises:
            ValueError: If validation fails.
            KeyError: If required field is missing.
        """
        # Required fields
        if "type" not in policy_dict:
            raise KeyError(f"Row {row_num}: Missing required field 'type'")
        if "identifier" not in policy_dict:
            raise KeyError(f"Row {row_num}: Missing required field 'identifier'")
        if "monthly_token_limit" not in policy_dict:
            raise KeyError(f"Row {row_num}: Missing required field 'monthly_token_limit'")

        # Parse policy type
        type_str = str(policy_dict["type"]).lower().strip()
        try:
            policy_type = PolicyType(type_str)
        except ValueError:
            raise ValueError(f"Row {row_num}: Invalid policy type '{type_str}'. Use 'user', 'group', or 'default'.")

        # Parse identifier
        identifier = str(policy_dict["identifier"]).strip()
        if not identifier:
            raise ValueError(f"Row {row_num}: Identifier cannot be empty")
        if policy_type == PolicyType.DEFAULT:
            identifier = "default"

        # Parse monthly token limit
        try:
            monthly_token_limit = _parse_tokens(policy_dict["monthly_token_limit"])
        except (ValueError, TypeError):
            raise ValueError(f"Row {row_num}: Invalid monthly_token_limit '{policy_dict['monthly_token_limit']}'")

        result: dict[str, Any] = {
            "policy_type": policy_type,
            "identifier": identifier,
            "monthly_token_limit": monthly_token_limit,
        }

        # Parse daily token limit
        daily_str = policy_dict.get("daily_token_limit", "")
        if daily_str and str(daily_str).strip():
            try:
                result["daily_token_limit"] = _parse_tokens(daily_str)
            except (ValueError, TypeError):
                raise ValueError(f"Row {row_num}: Invalid daily_token_limit '{daily_str}'")
        elif auto_daily:
            # Auto-calculate daily limit from monthly with burst buffer
            burst_factor = 1 + (burst_buffer_percent / 100)
            result["daily_token_limit"] = int(monthly_token_limit / 30 * burst_factor)

        # Parse enforcement mode
        enforcement_str = policy_dict.get("enforcement_mode", "alert")
        if enforcement_str:
            enforcement_str = str(enforcement_str).lower().strip()
            if enforcement_str == "block":
                result["enforcement_mode"] = EnforcementMode.BLOCK
            elif enforcement_str in ("alert", ""):
                result["enforcement_mode"] = EnforcementMode.ALERT
            else:
                raise ValueError(f"Row {row_num}: Invalid enforcement_mode '{enforcement_str}'. Use 'alert' or 'block'.")

        # Parse enabled status
        enabled_val = policy_dict.get("enabled", True)
        if isinstance(enabled_val, bool):
            result["enabled"] = enabled_val
        elif isinstance(enabled_val, str):
            result["enabled"] = enabled_val.lower().strip() in ("true", "1", "yes")
        else:
            result["enabled"] = bool(enabled_val)

        return result
