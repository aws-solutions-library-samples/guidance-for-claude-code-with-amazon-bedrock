"""Renderer for the per-persona / account AWS Budgets CloudFormation stack.

Part of persona-based access control (spec ``persona-based-access`` §3 D7, FR-6).
Budgets and their alert SNS topic do not exist in the base ``ccwb`` system
(spec F8) -- this module produces a dedicated stack, kept separate from the
quota-alerts topic (decision D7: finance vs. engineering audiences).

The renderer is a **pure function**: it takes the persona list plus the account
budget amount and returns CloudFormation YAML as a string. No file or network
IO, so it is trivially unit-testable and safe to call from ``deploy.py``.

CloudFormation intrinsics are emitted in their *full* form (``Fn::Sub``,
``Ref``) rather than the ``!Sub`` / ``!Ref`` short tags, because the template is
built as a plain ``dict`` and serialized with :func:`yaml.safe_dump`. Both forms
are equivalent and ``cfn-lint`` accepts them; the full form avoids fragile
custom YAML tag representers.

Naming follows ``cfn-naming.md``: the only fixed name is the documented topic
name pattern ``${AWS::StackName}-budget-alerts`` (via ``Fn::Sub``); everything
else is logical-id / stack-derived. ``${AWS::Partition}`` is used wherever an
ARN partition would otherwise be hardcoded (``region-availability.md``).
"""

from __future__ import annotations

from typing import Any

import yaml

# Reuse the persona stack's logical-id sanitizer so a persona's budget logical id
# and its role logical id are derived identically (single source of truth). The
# previous local implementation diverged on edge cases — it left a leading digit
# in place and upper-cased non-ASCII letters — both of which yield logical ids
# CloudFormation rejects (must match ^[A-Za-z0-9]+$). _logical_id always returns a
# valid, letter-led, ASCII-only stem.
from claude_code_with_bedrock.persona_template import _logical_id

# Logical ID of the alert topic; the physical name is rendered via Fn::Sub so it
# is unique per stack (cfn-naming.md) while staying human-recognizable.
BUDGET_ALERTS_TOPIC_LOGICAL_ID = "BudgetAlertsTopic"

# Alert thresholds (percent of budgeted amount). Each persona/account budget
# fires ACTUAL notifications at these points plus a single FORECASTED alert at
# 100% so overspend is flagged before it is incurred (FR-6).
_ACTUAL_THRESHOLDS = (50, 80, 100)
_FORECAST_THRESHOLD = 100


def _sub(template: str) -> dict[str, str]:
    """Return a CloudFormation ``Fn::Sub`` node for *template*."""
    return {"Fn::Sub": template}


def _sanitize_logical_id(name: str) -> str:
    """Turn a persona name into a CloudFormation-safe logical-id fragment.

    Delegates to :func:`persona_template._logical_id` so a persona's budget
    logical id matches the role logical id rendered in the persona stack, and so
    the result is always a valid CloudFormation logical id (``^[A-Za-z0-9]+$``,
    letter-led) regardless of the name's casing, leading digits, or non-ASCII
    characters. ``eng-team`` -> ``EngTeam``; ``1team`` -> ``P1team``.
    """
    return _logical_id(name)


def _cost_filters_for_persona(persona: dict[str, Any]) -> dict[str, list[str]]:
    """Build the ``CostFilters`` block for a persona's budget.

    AWS Budgets filters cost-allocation tags with values of the form
    ``user:<TagKey>$<TagValue>``. We emit one entry per tag in the persona's
    ``cost_tags`` map. For the common single-tag reference personas (e.g.
    ``{Team: Engineering}``) this scopes the budget precisely to that persona's
    spend. With multiple tags the entries are OR-combined by Budgets, so callers
    that need AND semantics should use a single identifying tag.
    """
    cost_tags = persona.get("cost_tags") or {}
    tag_values = [f"user:{key}${value}" for key, value in sorted(cost_tags.items())]
    if not tag_values:
        raise ValueError(
            f"persona {persona.get('name')!r} has a budget but no cost_tags to "
            "scope it; add at least one cost-allocation tag"
        )
    return {"TagKeyValue": tag_values}


def _notification(notification_type: str, threshold: int, topic_logical_id: str) -> dict[str, Any]:
    """Build one notification-with-subscribers entry routed to the alert topic.

    A fresh ``{"Ref": ...}`` dict is created per call so :func:`yaml.safe_dump`
    has no repeated node to collapse into a YAML anchor/alias; the rendered CFN
    therefore stays anchor-free for clean ``cfn-lint`` and human review.
    """
    return {
        "Notification": {
            "NotificationType": notification_type,
            "ComparisonOperator": "GREATER_THAN",
            "Threshold": threshold,
            "ThresholdType": "PERCENTAGE",
        },
        "Subscribers": [
            {"SubscriptionType": "SNS", "Address": {"Ref": topic_logical_id}},
        ],
    }


def _notifications(topic_logical_id: str) -> list[dict[str, Any]]:
    """Return the ACTUAL + FORECASTED notification subscriptions for a budget.

    Every notification routes to the shared budget-alerts SNS topic. Budgets
    publishes to the topic via the service principal, authorized by the topic
    policy rendered in :func:`_budget_alerts_topic_policy`.
    """
    notifications = [_notification("ACTUAL", threshold, topic_logical_id) for threshold in _ACTUAL_THRESHOLDS]
    notifications.append(_notification("FORECASTED", _FORECAST_THRESHOLD, topic_logical_id))
    return notifications


def _budget_resource(
    *,
    budget_name: str,
    amount_usd: float,
    topic_logical_id: str,
    cost_filters: dict[str, list[str]] | None,
) -> dict[str, Any]:
    """Build a single ``AWS::Budgets::Budget`` resource (monthly, COST type)."""
    budget_data: dict[str, Any] = {
        "BudgetName": _sub("${AWS::StackName}-" + budget_name),
        "BudgetType": "COST",
        "TimeUnit": "MONTHLY",
        "BudgetLimit": {"Amount": amount_usd, "Unit": "USD"},
    }
    if cost_filters is not None:
        budget_data["CostFilters"] = cost_filters

    return {
        "Type": "AWS::Budgets::Budget",
        "Properties": {
            "Budget": budget_data,
            "NotificationsWithSubscribers": _notifications(topic_logical_id),
        },
    }


def _budget_alerts_topic() -> dict[str, Any]:
    """The dedicated budget-alerts SNS topic (separate from quota alerts, D7)."""
    return {
        "Type": "AWS::SNS::Topic",
        "Properties": {
            "TopicName": _sub("${AWS::StackName}-budget-alerts"),
            "DisplayName": "Claude Code Persona Budget Alerts",
            "Tags": [
                {"Key": "Name", "Value": _sub("${AWS::StackName}-budget-alerts")},
                {"Key": "Purpose", "Value": "Persona budget notifications"},
            ],
        },
    }


def _budget_alerts_topic_policy(topic_logical_id: str) -> dict[str, Any]:
    """Topic policy letting AWS Budgets publish, with a confused-deputy guard.

    ``budgets.amazonaws.com`` is granted ``sns:Publish`` only when the call
    originates from this account (``aws:SourceAccount == ${AWS::AccountId}``),
    closing the confused-deputy hole flagged in spec §5 / region-availability.md.
    """
    return {
        "Type": "AWS::SNS::TopicPolicy",
        "Properties": {
            "Topics": [{"Ref": topic_logical_id}],
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "AllowBudgetsPublish",
                        "Effect": "Allow",
                        "Principal": {"Service": "budgets.amazonaws.com"},
                        "Action": "sns:Publish",
                        "Resource": {"Ref": topic_logical_id},
                        "Condition": {
                            "StringEquals": {"aws:SourceAccount": _sub("${AWS::AccountId}")},
                        },
                    }
                ],
            },
        },
    }


def render_budgets_stack(
    personas: list[dict[str, Any]],
    account_budget_amount_usd: float | int | None = None,
) -> str:
    """Render the persona/account AWS Budgets CloudFormation stack as YAML.

    Args:
        personas: persona dicts in the §4.1 shape. A budget is rendered only for
            personas whose ``budget_amount_usd`` is set (non-``None``); each such
            persona must carry at least one ``cost_tags`` entry to scope it.
        account_budget_amount_usd: when set, an additional account-wide budget
            (no cost filter) is rendered at the same thresholds.

    Returns:
        CloudFormation template as a YAML string. Always includes the
        budget-alerts SNS topic and its confused-deputy-guarded topic policy;
        adds one ``AWS::Budgets::Budget`` per budgeted persona plus an optional
        account-total budget.

    Raises:
        ValueError: if two personas resolve to the same logical id, or a
            budgeted persona has no ``cost_tags``.
    """
    topic_id = BUDGET_ALERTS_TOPIC_LOGICAL_ID

    resources: dict[str, Any] = {
        topic_id: _budget_alerts_topic(),
        f"{topic_id}Policy": _budget_alerts_topic_policy(topic_id),
    }

    # A persona's budget is scoped by its cost-allocation tag, which is only ever
    # attached to the Application Inference Profiles deploy creates per ENTITLED
    # tier. A persona entitled to no tier (everything denied) gets no AIP, so no
    # spend ever carries its tag and the budget could never trigger — skip it
    # rather than render an inert budget. Mirrors deploy's "entitled to no model
    # tier; skipping inference profiles" behavior (single source: entitled_tiers).
    from claude_code_with_bedrock.persona_models import entitled_tiers

    seen_logical_ids: set[str] = set()
    for persona in personas:
        amount = persona.get("budget_amount_usd")
        if amount is None:
            continue
        if not entitled_tiers(persona):
            continue
        logical_fragment = _sanitize_logical_id(persona["name"])
        budget_logical_id = f"{logical_fragment}Budget"
        if budget_logical_id in seen_logical_ids:
            raise ValueError(
                f"persona name {persona['name']!r} collides with another persona on logical id {budget_logical_id!r}"
            )
        seen_logical_ids.add(budget_logical_id)
        resources[budget_logical_id] = _budget_resource(
            budget_name=f"{logical_fragment}-budget",
            amount_usd=amount,
            topic_logical_id=topic_id,
            cost_filters=_cost_filters_for_persona(persona),
        )

    if account_budget_amount_usd is not None:
        resources["AccountBudget"] = _budget_resource(
            budget_name="account-budget",
            amount_usd=account_budget_amount_usd,
            topic_logical_id=topic_id,
            cost_filters=None,
        )

    template: dict[str, Any] = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": (
            "Claude Code persona-based cost governance: per-persona and account "
            "AWS Budgets with a dedicated alert SNS topic (persona-based-access "
            "FR-6)."
        ),
        "Resources": resources,
        "Outputs": {
            "BudgetAlertsTopicArn": {
                "Description": "ARN of the persona budget-alerts SNS topic.",
                "Value": {"Ref": topic_id},
                "Export": {"Name": _sub("${AWS::StackName}-BudgetAlertsTopicArn")},
            },
        },
    }

    # default_flow_style=False -> block style; sort_keys=False keeps the
    # template sections in the intentional order above for human review.
    return yaml.safe_dump(template, default_flow_style=False, sort_keys=False)
