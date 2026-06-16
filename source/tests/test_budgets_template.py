# ABOUTME: Unit tests for the persona/account AWS Budgets CloudFormation renderer
# ABOUTME: Asserts budget count, threshold notifications, and the SNS confused-deputy guard

"""Tests for :mod:`claude_code_with_bedrock.budgets_template`.

The renderer is a pure function, so these tests render YAML and parse it back
with ``yaml.safe_load`` (the renderer emits ``Fn::Sub``/``Ref`` full-form
intrinsics, so no custom CloudFormation YAML loader is required). They lock in
the FR-6 contract: a dedicated budget-alerts topic with an ``aws:SourceAccount``
confused-deputy guard, one budget per budgeted persona, and 50/80/100% ACTUAL
plus a FORECASTED notification on every budget.
"""

from __future__ import annotations

import pytest
import yaml

from claude_code_with_bedrock.budgets_template import (
    BUDGET_ALERTS_TOPIC_LOGICAL_ID,
    render_budgets_stack,
)

# The two reference personas from design §3, each with a budget set, plus a
# third unbudgeted persona to prove only budgeted personas produce a resource.
REFERENCE_PERSONAS = [
    {
        "name": "engineering",
        "group": "eng-team",
        "budget_amount_usd": 500,
        "cost_tags": {"Team": "Engineering"},
    },
    {
        "name": "sales",
        "group": "sales-team",
        "budget_amount_usd": 50,
        "cost_tags": {"Team": "Sales"},
    },
    {
        "name": "interns",
        "group": "intern-team",
        "budget_amount_usd": None,  # no budget -> must not render a Budget resource
        "cost_tags": {"Team": "Interns"},
    },
]


def _render_and_parse(personas, account_budget=1000):
    rendered = render_budgets_stack(personas, account_budget_amount_usd=account_budget)
    parsed = yaml.safe_load(rendered)
    return rendered, parsed


def _budget_resources(parsed):
    return {name: res for name, res in parsed["Resources"].items() if res["Type"] == "AWS::Budgets::Budget"}


class TestRenderBudgetsStack:
    """Core rendering contract."""

    def test_output_is_valid_yaml_with_template_version(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        assert parsed["AWSTemplateFormatVersion"] == "2010-09-09"
        assert "Resources" in parsed

    def test_three_budgets_rendered(self):
        """eng (500) + sales (50) + account (1000) == 3 budgets; interns excluded."""
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        budgets = _budget_resources(parsed)
        assert len(budgets) == 3, f"expected 3 budgets, got {sorted(budgets)}"

    def test_unbudgeted_persona_has_no_resource(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        budgets = _budget_resources(parsed)
        assert not any("Interns" in name for name in budgets)

    def test_account_budget_has_no_cost_filter(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        account = parsed["Resources"]["AccountBudget"]
        assert "CostFilters" not in account["Properties"]["Budget"]
        assert account["Properties"]["Budget"]["BudgetLimit"]["Amount"] == 1000

    def test_account_budget_omitted_when_amount_none(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS, account_budget=None)
        assert "AccountBudget" not in parsed["Resources"]
        # Persona budgets still render.
        assert len(_budget_resources(parsed)) == 2

    def test_persona_budget_cost_filter_uses_user_tag_form(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        eng = parsed["Resources"]["EngineeringBudget"]
        cost_filters = eng["Properties"]["Budget"]["CostFilters"]
        assert cost_filters == {"TagKeyValue": ["user:Team$Engineering"]}

    def test_persona_budget_is_monthly_cost_type(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        eng = parsed["Resources"]["EngineeringBudget"]["Properties"]["Budget"]
        assert eng["BudgetType"] == "COST"
        assert eng["TimeUnit"] == "MONTHLY"
        assert eng["BudgetLimit"] == {"Amount": 500, "Unit": "USD"}


class TestNotifications:
    """Each budget must alert at 50/80/100% ACTUAL plus a FORECASTED 100%."""

    def _notifications(self, budget_resource):
        return budget_resource["Properties"]["NotificationsWithSubscribers"]

    def test_three_actual_plus_one_forecast_per_budget(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        for name, budget in _budget_resources(parsed).items():
            notifs = self._notifications(budget)
            types = [n["Notification"]["NotificationType"] for n in notifs]
            assert types.count("ACTUAL") == 3, f"{name}: {types}"
            assert types.count("FORECASTED") == 1, f"{name}: {types}"

    def test_actual_thresholds_are_50_80_100(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        eng = parsed["Resources"]["EngineeringBudget"]
        actual = [
            n["Notification"]["Threshold"]
            for n in self._notifications(eng)
            if n["Notification"]["NotificationType"] == "ACTUAL"
        ]
        assert sorted(actual) == [50, 80, 100]

    def test_all_notifications_target_the_budget_topic(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        for budget in _budget_resources(parsed).values():
            for notif in self._notifications(budget):
                subs = notif["Subscribers"]
                assert len(subs) == 1
                assert subs[0]["SubscriptionType"] == "SNS"
                assert subs[0]["Address"] == {"Ref": BUDGET_ALERTS_TOPIC_LOGICAL_ID}


class TestAlertTopic:
    """Dedicated SNS topic + confused-deputy guard (D7, spec §5)."""

    def test_topic_name_is_stackname_scoped(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        topic = parsed["Resources"][BUDGET_ALERTS_TOPIC_LOGICAL_ID]
        assert topic["Type"] == "AWS::SNS::Topic"
        # cfn-naming.md: no hardcoded name; rendered via Fn::Sub on StackName.
        assert topic["Properties"]["TopicName"] == {"Fn::Sub": "${AWS::StackName}-budget-alerts"}

    def test_topic_policy_present(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        policy_id = f"{BUDGET_ALERTS_TOPIC_LOGICAL_ID}Policy"
        assert parsed["Resources"][policy_id]["Type"] == "AWS::SNS::TopicPolicy"

    def test_topic_policy_has_source_account_condition(self):
        """The confused-deputy guard MUST be present (spec §5)."""
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        policy_id = f"{BUDGET_ALERTS_TOPIC_LOGICAL_ID}Policy"
        statement = parsed["Resources"][policy_id]["Properties"]["PolicyDocument"]["Statement"][0]
        assert statement["Principal"] == {"Service": "budgets.amazonaws.com"}
        assert statement["Action"] == "sns:Publish"
        condition = statement["Condition"]["StringEquals"]
        assert condition["aws:SourceAccount"] == {"Fn::Sub": "${AWS::AccountId}"}

    def test_topic_arn_exported(self):
        _, parsed = _render_and_parse(REFERENCE_PERSONAS)
        export = parsed["Outputs"]["BudgetAlertsTopicArn"]["Export"]["Name"]
        assert export == {"Fn::Sub": "${AWS::StackName}-BudgetAlertsTopicArn"}


class TestEdgeCases:
    def test_no_personas_still_renders_topic_only(self):
        _, parsed = _render_and_parse([], account_budget=None)
        # Topic + policy, no budgets.
        assert BUDGET_ALERTS_TOPIC_LOGICAL_ID in parsed["Resources"]
        assert not _budget_resources(parsed)

    def test_budgeted_persona_without_cost_tags_raises(self):
        bad = [{"name": "eng", "group": "eng", "budget_amount_usd": 100, "cost_tags": {}}]
        with pytest.raises(ValueError, match="cost_tags"):
            render_budgets_stack(bad)

    def test_colliding_logical_ids_raise(self):
        # "eng-team" and "eng.team" both sanitize to "EngTeam".
        colliding = [
            {"name": "eng-team", "group": "a", "budget_amount_usd": 1, "cost_tags": {"T": "a"}},
            {"name": "eng.team", "group": "b", "budget_amount_usd": 1, "cost_tags": {"T": "b"}},
        ]
        with pytest.raises(ValueError, match="collides"):
            render_budgets_stack(colliding)

    def test_persona_name_sanitized_into_logical_id(self):
        personas = [{"name": "data-science", "group": "ds", "budget_amount_usd": 10, "cost_tags": {"T": "x"}}]
        _, parsed = _render_and_parse(personas, account_budget=None)
        assert "DataScienceBudget" in parsed["Resources"]
