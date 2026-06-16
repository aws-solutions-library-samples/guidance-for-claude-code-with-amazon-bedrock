# ABOUTME: Tests for persona serialization into config.json by package.py _create_config.
# ABOUTME: Asserts the §4.2 field projection, role_arn passthrough, and backward compat.

"""Tests for ``PackageCommand._create_config`` persona serialization (spec §4.2)."""

import json
from pathlib import Path

from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile


def _profile(**overrides) -> Profile:
    kwargs = {
        "name": "ClaudeCode",
        "provider_domain": "company.okta.com",
        "client_id": "client-123",
        "credential_storage": "keyring",
        "aws_region": "us-east-1",
        "identity_pool_name": "pool",
        "federation_type": "direct",
        "federated_role_arn": "arn:aws:iam::111122223333:role/base",
    }
    kwargs.update(overrides)
    return Profile(**kwargs)


def _write_config(tmp_path: Path, profile: Profile) -> dict:
    cmd = PackageCommand()
    cmd._create_config(
        output_dir=tmp_path,
        profile=profile,
        federation_identifier=profile.federated_role_arn or "arn:aws:iam::111122223333:role/base",
        federation_type="direct",
        profile_name=profile.name,
    )
    with open(tmp_path / "config.json", encoding="utf-8") as f:
        return json.load(f)


PERSONAS = [
    {
        "name": "engineering",
        "display_name": "Engineering",
        "group": "eng-team",
        "allowed_models": ["anthropic.*"],
        "denied_models": [],
        "monthly_token_limit": 300_000_000,
        "daily_token_limit": None,
        "enforcement_mode": "block",
        "budget_amount_usd": None,
        "cost_tags": {"Team": "Engineering"},
        "role_arn": "arn:aws:iam::111122223333:role/persona-eng",
    },
    {
        "name": "sales",
        "display_name": "Sales",
        "group": "sales-team",
        "allowed_models": ["anthropic.*haiku*"],
        "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"],
        "monthly_token_limit": 10_000_000,
        "enforcement_mode": "block",
        "cost_tags": {"Team": "Sales"},
        "role_arn": "arn:aws:iam::111122223333:role/persona-sales",
    },
]


class TestPersonaSerialization:
    def test_personas_written_with_role_arn(self, tmp_path):
        profile = _profile(personas=PERSONAS, groups_claim_name="groups", fallback_persona="engineering")
        config = _write_config(tmp_path, profile)["ClaudeCode"]

        assert "personas" in config
        assert [p["name"] for p in config["personas"]] == ["engineering", "sales"]
        assert config["personas"][0]["role_arn"] == "arn:aws:iam::111122223333:role/persona-eng"
        assert config["personas"][1]["role_arn"] == "arn:aws:iam::111122223333:role/persona-sales"

    def test_top_level_persona_fields(self, tmp_path):
        profile = _profile(personas=PERSONAS, groups_claim_name="cognito:groups", fallback_persona="engineering")
        config = _write_config(tmp_path, profile)["ClaudeCode"]

        assert config["groups_claim_name"] == "cognito:groups"
        assert config["fallback_persona"] == "engineering"

    def test_serialization_projects_only_42_fields(self, tmp_path):
        """Only the spec §4.2 fields the Go PersonaConfig consumes are emitted."""
        profile = _profile(personas=PERSONAS)
        eng = _write_config(tmp_path, profile)["ClaudeCode"]["personas"][0]

        allowed = {
            "name",
            "display_name",
            "group",
            "allowed_models",
            "denied_models",
            "role_arn",
            "monthly_token_limit",
            "enforcement_mode",
            "cost_tags",
        }
        assert set(eng).issubset(allowed)
        # Python-only fields must NOT leak into config.json (Go has no such tags).
        assert "daily_token_limit" not in eng
        assert "budget_amount_usd" not in eng

    def test_empty_optional_fields_omitted(self, tmp_path):
        """allowed_models=[] / denied_models=[] are falsy → omitted (omitempty parity)."""
        profile = _profile(personas=PERSONAS)
        eng = _write_config(tmp_path, profile)["ClaudeCode"]["personas"][0]

        # engineering has denied_models == [] → omitted; allowed_models non-empty → present
        assert "denied_models" not in eng
        assert eng["allowed_models"] == ["anthropic.*"]

    def test_required_fields_always_present(self, tmp_path):
        """name/group/role_arn are always emitted even when empty."""
        minimal = [{"name": "min", "group": "min-team"}]  # no role_arn yet
        profile = _profile(personas=minimal)
        persona = _write_config(tmp_path, profile)["ClaudeCode"]["personas"][0]

        assert persona["name"] == "min"
        assert persona["group"] == "min-team"
        assert persona["role_arn"] == ""

    def test_fallback_omitted_when_none(self, tmp_path):
        profile = _profile(personas=PERSONAS, fallback_persona=None)
        config = _write_config(tmp_path, profile)["ClaudeCode"]

        assert "fallback_persona" not in config
        # groups_claim_name still emitted alongside personas
        assert config["groups_claim_name"] == "groups"


class TestBackwardCompat:
    def test_no_personas_key_when_unconfigured(self, tmp_path):
        """A profile with no personas must not add any persona keys (legacy path)."""
        profile = _profile()  # personas defaults to []
        config = _write_config(tmp_path, profile)["ClaudeCode"]

        assert "personas" not in config
        assert "groups_claim_name" not in config
        assert "fallback_persona" not in config

    def test_legacy_federated_role_arn_still_written(self, tmp_path):
        """The existing direct-federation field is unaffected by the persona block."""
        profile = _profile()
        config = _write_config(tmp_path, profile)["ClaudeCode"]

        assert config["federated_role_arn"] == "arn:aws:iam::111122223333:role/base"
        assert config["federation_type"] == "direct"

    def test_personas_not_serialized_under_cognito_federation(self, tmp_path):
        """L3: personas are direct-IAM only — serializing them under Cognito is dead data.

        Even if a profile somehow carries personas, _create_config invoked for a
        Cognito-federation package must NOT emit persona keys (the Go helper ignores
        personas unless FederationType=='direct', and deploy skips persona provisioning
        under Cognito per FR-2.7).
        """
        profile = _profile(federation_type="cognito", personas=PERSONAS)
        cmd = PackageCommand()
        cmd._create_config(
            output_dir=tmp_path,
            profile=profile,
            federation_identifier="pool",
            federation_type="cognito",
            profile_name=profile.name,
        )
        with open(tmp_path / "config.json", encoding="utf-8") as f:
            config = json.load(f)["ClaudeCode"]

        assert "personas" not in config
        assert "groups_claim_name" not in config
        assert "fallback_persona" not in config
