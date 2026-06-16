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

import re

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

    def test_zero_entitled_tier_persona_gets_no_budget(self):
        """L5: a persona entitled to NO model tier (everything denied) gets no AIP,
        so nothing ever carries its cost tag — rendering a budget for it would be
        inert. The renderer must skip it (mirrors deploy skipping AIP creation),
        while still rendering budgets for entitled personas in the same list.
        """
        personas = [
            # Everything denied -> entitled_tiers == [] -> no budget.
            {
                "name": "locked-out",
                "group": "lo",
                "allowed_models": ["anthropic.*"],
                "denied_models": ["anthropic.*"],
                "budget_amount_usd": 100,
                "cost_tags": {"Team": "LockedOut"},
            },
            # Normal persona -> still budgeted.
            {
                "name": "eng",
                "group": "eng",
                "allowed_models": ["anthropic.*"],
                "budget_amount_usd": 500,
                "cost_tags": {"Team": "Eng"},
            },
        ]
        _, parsed = _render_and_parse(personas, account_budget=None)
        budget_ids = {k for k in parsed["Resources"] if k.endswith("Budget") and k != "AccountBudget"}
        assert budget_ids == {"EngBudget"}, (
            f"only the entitled persona should get a budget; got {budget_ids}"
        )

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

    def test_digit_leading_name_produces_valid_logical_id(self):
        # Regression: a digit-leading persona name must not emit an invalid
        # CloudFormation logical id (must match ^[A-Za-z0-9]+$ AND start with a
        # letter). The shared _logical_id prepends 'P' -> 'P1team'.
        personas = [{"name": "1team", "group": "g", "budget_amount_usd": 10, "cost_tags": {"T": "x"}}]
        _, parsed = _render_and_parse(personas, account_budget=None)
        budget_ids = [k for k in parsed["Resources"] if k.endswith("Budget") and k != "AccountBudget"]
        assert budget_ids == ["P1teamBudget"]
        assert re.match(r"^[A-Za-z][A-Za-z0-9]*$", budget_ids[0])

    def test_non_ascii_name_produces_valid_logical_id(self):
        # Regression: a non-ASCII persona name previously rendered a logical id
        # CloudFormation rejects (E3001). The shared _logical_id strips it to ASCII.
        personas = [{"name": "écran", "group": "g", "budget_amount_usd": 10, "cost_tags": {"T": "x"}}]
        _, parsed = _render_and_parse(personas, account_budget=None)
        budget_ids = [k for k in parsed["Resources"] if k.endswith("Budget") and k != "AccountBudget"]
        assert len(budget_ids) == 1
        assert re.match(r"^[A-Za-z0-9]+$", budget_ids[0]), budget_ids[0]

    def test_budget_logical_id_matches_persona_role_stem(self):
        # The budget logical-id stem must match the persona stack's role stem so
        # the two rendered stacks refer to the same persona by the same id (single
        # source of truth — both derive from persona_template._logical_id).
        from claude_code_with_bedrock.persona_template import _logical_id

        for name in ("data-science", "eng.team", "1team", "écran", "Sales"):
            personas = [{"name": name, "group": "g", "budget_amount_usd": 10, "cost_tags": {"T": "x"}}]
            _, parsed = _render_and_parse(personas, account_budget=None)
            budget_ids = [k for k in parsed["Resources"] if k.endswith("Budget") and k != "AccountBudget"]
            assert budget_ids == [f"{_logical_id(name)}Budget"], name


# Canonical recipe for the committed CI fixture (bedrock-budgets.example.yaml).
# Kept here as the single source of truth: the drift test below and the fixture
# file must agree. Regenerate the file from this recipe if the renderer changes.
_BUDGETS_FIXTURE_ACCOUNT_BUDGET = 10000.0


def _budgets_example_personas():
    """REFERENCE_PERSONAS (engineering + sales) with budgets added for the fixture."""
    import copy

    from claude_code_with_bedrock.persona_defaults import REFERENCE_PERSONAS as _REF

    personas = copy.deepcopy(_REF)
    for p in personas:
        if p["name"] == "engineering":
            p["budget_amount_usd"] = 5000.0
        elif p["name"] == "sales":
            p["budget_amount_usd"] = 500.0
    return personas


class TestCommittedExampleFixture:
    """The rendered AWS Budgets stack must be CI-cfn-linted, like the persona stack.

    ``deployment/infrastructure/bedrock-budgets.example.yaml`` is a generated
    artifact that CI's ``cfn-lint deployment/infrastructure/*.yaml`` step lints as
    a stand-in for real rendered Budgets output. Without it, a renderer change that
    emitted schema-invalid CloudFormation (bad ``CostFilters`` shape, wrong
    ``Threshold`` type, malformed TopicPolicy) would pass every YAML-only unit test
    and only fail at a customer's ``ccwb deploy`` — the exact failure mode the
    persona stack's committed fixture already guards against. This is the budgets
    sibling of ``test_persona_template.test_committed_example_fixture_matches_renderer``.
    """

    def _fixture_path(self):
        from pathlib import Path

        return (
            Path(__file__).parent.parent.parent
            / "deployment"
            / "infrastructure"
            / "bedrock-budgets.example.yaml"
        )

    def test_committed_budgets_example_exists(self):
        assert self._fixture_path().exists(), (
            "bedrock-budgets.example.yaml is missing — CI cannot cfn-lint the rendered "
            "Budgets stack without it. Generate it from _budgets_example_personas()."
        )

    def test_committed_budgets_example_matches_renderer(self):
        """Drift guard: the committed fixture body must equal the renderer output.

        If the renderer changes but the fixture isn't regenerated, CI would lint a
        stale template. Compare parsed structures so comment/whitespace don't matter.
        """
        committed = self._fixture_path().read_text(encoding="utf-8")
        committed_body = "\n".join(line for line in committed.splitlines() if not line.startswith("#"))
        rendered = render_budgets_stack(
            _budgets_example_personas(), account_budget_amount_usd=_BUDGETS_FIXTURE_ACCOUNT_BUDGET
        )
        assert yaml.safe_load(committed_body) == yaml.safe_load(rendered), (
            "bedrock-budgets.example.yaml is out of sync with budgets_template.render_budgets_stack — "
            "regenerate it from _budgets_example_personas() (account budget "
            f"{_BUDGETS_FIXTURE_ACCOUNT_BUDGET})."
        )
