# ABOUTME: Regression tests for cost-based quota wiring: wizard answers must reach
# ABOUTME: the profile, the stack, and both Lambdas (previously dropped end-to-end).

"""Cost-based quota was half-wired: the wizard asked for $ budgets but the
answers were dropped at every hop.

- No Profile fields existed for limit type / cost limits → not in the profile
  JSON, lost on re-init.
- deploy never passed MonthlyCostLimitUsd / DailyCostLimitUsd; the template
  declared them but wired them to nothing.
- quota_check's environment-default policy activated only when
  MONTHLY_TOKEN_LIMIT > 0 — cost mode zeroes token limits, so cost-mode
  deployments resolved NO policy and every user was unlimited.
- quota_monitor alerted `total_tokens > monthly_limit` with no zero guard, so
  a 0 token limit (cost mode) alert-stormed every active user each scan.
- The wizard also asked for token counts in cost mode (the mode gate only
  wrapped a header print) and silently dropped the monthly enforcement answer.

These tests pin every hop of the repaired chain.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

# ruff: noqa: E402
sys.path.insert(0, str(Path(__file__).parent.parent))

from claude_code_with_bedrock.cli.commands.init import InitCommand
from claude_code_with_bedrock.config import Config, Profile

LAMBDA_DIR = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure" / "lambda-functions"
TEMPLATE = Path(__file__).resolve().parents[2] / "deployment" / "infrastructure" / "quota-monitoring.yaml"


def _load_lambda(name: str, env: dict):
    """Load a Lambda module fresh with the given environment (loader pattern
    from test_quota_monitor_lambda.py). Restores os.environ afterwards so
    later tests loading the same Lambdas don't inherit these limits."""
    base = {
        "AWS_DEFAULT_REGION": "us-gov-west-1",
        "QUOTA_TABLE": "TestQuotaTable",
        "POLICIES_TABLE": "TestPoliciesTable",
        "SNS_TOPIC_ARN": "arn:aws-us-gov:sns:us-gov-west-1:123456789012:test-alerts",
    }
    base.update(env)
    prior = {key: os.environ.get(key) for key in base}
    for key, value in base.items():
        os.environ[key] = str(value)
    try:
        module_name = f"{name}_cost_{abs(hash(frozenset((k, str(v)) for k, v in base.items())))}"
        spec = importlib.util.spec_from_file_location(module_name, LAMBDA_DIR / name / "index.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestProfileFields:
    def test_cost_fields_round_trip(self):
        p = Profile(
            name="t",
            provider_domain="d",
            client_id="c",
            credential_storage="session",
            aws_region="us-gov-west-1",
            identity_pool_name="p",
            quota_limit_type="cost",
            monthly_cost_limit_usd=50.0,
            daily_cost_limit_usd=5.0,
        )
        loaded = Profile.from_dict(p.to_dict())
        assert loaded.quota_limit_type == "cost"
        assert loaded.monthly_cost_limit_usd == 50.0
        assert loaded.daily_cost_limit_usd == 5.0

    def test_old_profiles_default_to_token_mode(self):
        data = Profile(
            name="t",
            provider_domain="d",
            client_id="c",
            credential_storage="session",
            aws_region="us-east-1",
            identity_pool_name="p",
        ).to_dict()
        for key in ("quota_limit_type", "monthly_cost_limit_usd", "daily_cost_limit_usd"):
            data.pop(key)
        loaded = Profile.from_dict(data)
        assert loaded.quota_limit_type == "token"
        assert loaded.monthly_cost_limit_usd == 0
        assert loaded.daily_cost_limit_usd == 0


class TestInitRoundTrip:
    def _rebuild(self, profile: Profile) -> dict:
        command = InitCommand()
        fake_config = Config()
        with (
            patch.object(Config, "load", return_value=fake_config),
            patch.object(fake_config, "get_profile", return_value=profile),
            patch.object(InitCommand, "_stack_exists", side_effect=Exception("no creds")),
        ):
            return command._check_existing_deployment("test")

    def test_rerun_preserves_cost_quota_fields(self):
        profile = Profile(
            name="test",
            provider_domain="example.okta.com",
            client_id="0oa1234567890",
            identity_pool_name="claude-code-auth",
            credential_storage="keyring",
            aws_region="us-gov-west-1",
            quota_monitoring_enabled=True,
            quota_limit_type="cost",
            monthly_cost_limit_usd=75.0,
            daily_cost_limit_usd=10.0,
            monthly_token_limit=0,
        )
        quota = self._rebuild(profile)["quota"]
        assert quota["limit_type"] == "cost"
        assert quota["monthly_cost_limit"] == 75.0
        assert quota["daily_cost_limit"] == 10.0


def _load_template() -> dict:
    class CFNLoader(yaml.SafeLoader):
        pass

    def _cfn(loader, suffix, node):  # noqa: ARG001 - yaml constructor signature
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node)
        return loader.construct_mapping(node)

    CFNLoader.add_multi_constructor("!", _cfn)
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=CFNLoader)


class TestTemplateWiring:
    def test_cost_params_wired_to_both_lambdas(self):
        resources = _load_template()["Resources"]
        for fn in ("QuotaCheckFunction", "QuotaMonitorFunction"):
            env = resources[fn]["Properties"]["Environment"]["Variables"]
            assert env.get("MONTHLY_COST_LIMIT_USD") == "MonthlyCostLimitUsd", fn
            assert env.get("DAILY_COST_LIMIT_USD") == "DailyCostLimitUsd", fn

    def test_monthly_token_limit_accepts_zero(self):
        """Cost mode passes MonthlyTokenLimit=0; MinValue must allow it."""
        params = _load_template()["Parameters"]
        assert params["MonthlyTokenLimit"]["MinValue"] == 0


class TestQuotaCheckCostDefaults:
    def test_cost_only_env_resolves_default_policy(self):
        """The regression: cost mode (token limit 0) resolved NO policy →
        every user unlimited. A cost limit alone must activate the default."""
        mod = _load_lambda(
            "quota_check",
            {"MONTHLY_TOKEN_LIMIT": "0", "MONTHLY_COST_LIMIT_USD": "50", "DAILY_COST_LIMIT_USD": "5"},
        )
        policy = mod.resolve_quota_for_user("user@example.gov", [])
        assert policy is not None, "cost-only config must resolve the default policy"
        assert policy["monthly_cost_limit"] == 50.0
        assert policy["daily_cost_limit"] == 5.0
        assert policy["monthly_token_limit"] == 0

    def test_no_limits_resolves_no_policy(self):
        mod = _load_lambda("quota_check", {"MONTHLY_TOKEN_LIMIT": "0", "MONTHLY_COST_LIMIT_USD": "0"})
        assert mod.resolve_quota_for_user("user@example.gov", []) is None


class TestQuotaMonitorCostAlerts:
    ENV = {
        "MONTHLY_TOKEN_LIMIT": "0",
        "MONTHLY_COST_LIMIT_USD": "100",
        "DAILY_COST_LIMIT_USD": "10",
        "ENABLE_FINEGRAINED_QUOTAS": "false",
    }

    def _alerts(self, mod, *, total_tokens=0, daily_tokens=0, monthly_cost=0.0, daily_cost=0.0):
        policy = mod.resolve_user_quota("u@example.gov", [], {})
        return mod.check_limits_and_generate_alerts(
            email="u@example.gov",
            total_tokens=total_tokens,
            daily_tokens=daily_tokens,
            policy=policy,
            month_name="July 2026",
            current_date="2026-07-13",
            days_remaining=18,
            days_in_month=31,
            sent_alerts=set(),
            monthly_cost=monthly_cost,
            daily_cost=daily_cost,
        )

    def test_zero_token_limit_generates_no_token_alerts(self):
        """The alert-storm regression: with monthly_limit=0, any usage
        previously produced a 'monthly exceeded' alert every scan."""
        mod = _load_lambda("quota_monitor", self.ENV)
        alerts = self._alerts(mod, total_tokens=5_000_000, monthly_cost=1.0)
        assert not [a for a in alerts if a["alert_type"] == "monthly"], alerts

    def test_cost_warning_and_exceeded_levels(self):
        mod = _load_lambda("quota_monitor", self.ENV)
        warn = self._alerts(mod, monthly_cost=85.0)
        assert [a for a in warn if a["alert_type"] == "monthly_cost" and a["alert_level"] == "warning"]
        over = self._alerts(mod, monthly_cost=101.0)
        assert [a for a in over if a["alert_type"] == "monthly_cost" and a["alert_level"] == "exceeded"]

    def test_daily_cost_alert_carries_date(self):
        mod = _load_lambda("quota_monitor", self.ENV)
        alerts = self._alerts(mod, daily_cost=11.0)
        daily = [a for a in alerts if a["alert_type"] == "daily_cost"]
        assert daily and daily[0]["date"] == "2026-07-13"

    def test_usage_entry_includes_cost_with_stale_day_guard(self):
        mod = _load_lambda("quota_monitor", self.ENV)
        item = {
            "total_tokens": 1000,
            "daily_tokens": 500,
            "estimated_cost": 42.5,
            "daily_cost_usd": 7.5,
            "daily_date": "2026-07-12",
        }
        entry = mod._build_usage_entry(item, "2026-07-13")
        assert entry["monthly_cost"] == 42.5
        assert entry["daily_cost"] == 0, "stale-day guard must reset the daily cost counter"
        entry_today = mod._build_usage_entry({**item, "daily_date": "2026-07-13"}, "2026-07-13")
        assert entry_today["daily_cost"] == 7.5
