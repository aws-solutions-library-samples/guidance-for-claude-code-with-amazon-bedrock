# ABOUTME: FR-5.1 install->use->teardown integration test for per-persona model routing.
# ABOUTME: Locks the cross-step + cross-language invariant: AIP names/ARNs that package
# ABOUTME: serializes are exactly what the Go helper routes and what destroy tears down.

"""FR-5.1 per-persona model-routing lifecycle integration test.

Per-persona model routing spans four steps in two languages, and no single unit
test proves they agree end to end:

1. **deploy** creates one Application Inference Profile (AIP) per *entitled tier*,
   named ``{pool}-{persona}-{tier}`` via :func:`persona_models.aip_name`, and reads
   each ARN back into ``persona["inference_profile_arns"]``.
2. **package** (`_create_config`) serializes those ARNs into ``config.json``,
   `_create_persona_model_wrapper` emits ``persona-model.{sh,ps1}``, and the
   generated installer copies the wrapper to ``~/claude-code-with-bedrock/``.
3. **use** — the Go ``credential-process --get-persona-model`` reads that same
   ``config.json`` and emits ``export ANTHROPIC_*_MODEL=<arn>`` for the resolved
   persona's tiers.
4. **teardown** — ``ccwb destroy`` deletes AIPs by names re-derived from the same
   :func:`persona_models.aip_name`.

A drift in any step silently breaks routing or orphans a billable resource. This
test drives the REAL code at each step (no re-implementation) and asserts the
single invariant that ties them together:

    AIP names deploy would create
      == ARNs package serializes into config.json
      == ARNs the Go helper emits as exports
      == AIP names destroy deletes

The "use" leg shells into the Go test ``TestPersonaModelExportsFromConfigJSON``
(in ``cmd/credential-process``), which loads the *packaged* config.json through
the real ``config.LoadProfileFromPath`` loader — so the cross-language config
contract is exercised against a real artifact, not a hand-built fixture. If the
Go toolchain is unavailable the use-leg assertion FAILS (not skips): a silent
skip would let cross-language drift through in CI, exactly what this guards.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from claude_code_with_bedrock.cli.commands.destroy import DestroyCommand
from claude_code_with_bedrock.cli.commands.package import PackageCommand
from claude_code_with_bedrock.config import Profile
from claude_code_with_bedrock.persona_models import aip_name, entitled_tiers

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GO_DIR = _REPO_ROOT / "source" / "go"

_POOL = "acme-pool"
_REGION = "us-east-1"
_ACCOUNT = "111122223333"


def _arn(pool: str, persona: str, tier: str) -> str:
    """The AIP ARN deploy would record for a persona tier (shape mirrors AWS)."""
    return f"arn:aws:bedrock:{_REGION}:{_ACCOUNT}:application-inference-profile/{aip_name(pool, persona, tier)}"


def _profile_with_resolved_arns() -> Profile:
    """A direct-federation persona profile as it looks AFTER deploy resolved AIPs.

    engineering -> all tiers (haiku/sonnet/opus); sales -> haiku only (sonnet+opus
    denied). Each entitled tier carries the ARN deploy would have read back, so this
    is the exact ``profile.personas`` state ``ccwb package`` serializes.
    """
    personas = [
        {
            "name": "engineering",
            "display_name": "Engineering",
            "group": "eng-team",
            "allowed_models": ["anthropic.*"],
            "denied_models": [],
            "enforcement_mode": "block",
            "cost_tags": {"Team": "Engineering"},
            "role_arn": f"arn:aws:iam::{_ACCOUNT}:role/{_POOL}-engineering",
        },
        {
            "name": "sales",
            "display_name": "Sales",
            "group": "sales-team",
            "allowed_models": ["anthropic.*haiku*"],
            "denied_models": ["anthropic.*sonnet*", "anthropic.*opus*"],
            "enforcement_mode": "block",
            "cost_tags": {"Team": "Sales"},
            "role_arn": f"arn:aws:iam::{_ACCOUNT}:role/{_POOL}-sales",
        },
    ]
    # Attach resolved ARNs for exactly the tiers each persona is entitled to —
    # mirroring deploy._create_persona_inference_profiles, derived from the SAME
    # entitled_tiers + aip_name helpers (single source of truth).
    for p in personas:
        p["inference_profile_arns"] = {t: _arn(_POOL, p["name"], t) for t in entitled_tiers(p)}

    return Profile(
        name="ClaudeCode",
        provider_domain="acme.okta.com",
        client_id="client-xyz",
        credential_storage="keyring",
        aws_region=_REGION,
        identity_pool_name=_POOL,
        federation_type="direct",
        federated_role_arn=f"arn:aws:iam::{_ACCOUNT}:role/base",
        personas=personas,
    )


def _go_binary() -> str | None:
    found = shutil.which("go")
    if found:
        return found
    for c in ("/opt/homebrew/bin/go", "/usr/local/bin/go", "/usr/local/go/bin/go"):
        if Path(c).exists():
            return c
    return None


class _Console:
    def print(self, *a, **k):
        pass


class TestPersonaModelLifecycle:
    """install -> use -> teardown, end to end, on the real code paths."""

    def test_package_serializes_resolved_arns_and_emits_wrapper(self, tmp_path):
        """STEP 1-2 (install): package writes config.json with the per-tier ARNs,
        emits the wrapper, and the installer copies it to the documented path."""
        profile = _profile_with_resolved_arns()
        cmd = PackageCommand()
        cmd.line = lambda *a, **k: None

        cmd._create_config(tmp_path, profile, profile.federated_role_arn, "direct", "ClaudeCode")
        cmd._create_persona_model_wrapper(tmp_path, profile, "ClaudeCode", _Console())
        be = [("macos-arm64", tmp_path / "credential-process-macos-arm64")]
        (tmp_path / "credential-process-macos-arm64").write_text("x")
        installer = cmd._create_installer(tmp_path, profile, be, None)

        # config.json carries every entitled tier's ARN, byte-equal to what deploy resolved.
        cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        personas = {p["name"]: p for p in cfg["ClaudeCode"]["personas"]}
        assert personas["engineering"]["inference_profile_arns"] == {
            "haiku": _arn(_POOL, "engineering", "haiku"),
            "sonnet": _arn(_POOL, "engineering", "sonnet"),
            "opus": _arn(_POOL, "engineering", "opus"),
        }
        assert personas["sales"]["inference_profile_arns"] == {"haiku": _arn(_POOL, "sales", "haiku")}

        # Wrapper emitted and the installer copies it to the path the docs source.
        assert (tmp_path / "persona-model.sh").exists()
        installer_body = Path(installer).read_text(encoding="utf-8")
        assert "cp persona-model.sh ~/claude-code-with-bedrock/persona-model.sh" in installer_body

    def test_use_go_helper_routes_packaged_arns(self, tmp_path):
        """STEP 3 (use): the REAL Go helper, reading the REAL packaged config.json,
        emits exports pointing at exactly the ARNs package serialized.

        Fails (not skips) when Go is unavailable — silent skip would hide drift."""
        go = _go_binary()
        assert go, "Go toolchain not found; the cross-language use-leg cannot be verified"

        profile = _profile_with_resolved_arns()
        cmd = PackageCommand()
        cmd.line = lambda *a, **k: None
        cmd._create_config(tmp_path, profile, profile.federated_role_arn, "direct", "ClaudeCode")
        config_path = tmp_path / "config.json"

        # Expected exports for the sales persona (haiku only): the per-tier var + bare
        # ANTHROPIC_MODEL=primary (haiku is the only/most-capable entitled tier).
        haiku = _arn(_POOL, "sales", "haiku")
        expect = "\n".join(
            [f"export ANTHROPIC_DEFAULT_HAIKU_MODEL={haiku}", f"export ANTHROPIC_MODEL={haiku}"]
        )

        env = dict(os.environ)
        env.update(
            {
                "GOPROXY": env.get("GOPROXY", "direct"),
                "GOFLAGS": env.get("GOFLAGS", "-mod=mod"),
                "CCWB_IT_CONFIG": str(config_path),
                "CCWB_IT_PROFILE": "ClaudeCode",
                "CCWB_IT_GROUP": "sales-team",
                "CCWB_IT_EXPECT": expect,
            }
        )
        result = subprocess.run(
            [go, "test", "./cmd/credential-process/", "-run", "TestPersonaModelExportsFromConfigJSON",
             "-count=1", "-v"],
            cwd=str(_GO_DIR), env=env, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, (
            "Go helper did not route the packaged ARNs (or the run was skipped/failed):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        # The Go test must have RUN (not skipped) — prove the env bridge worked.
        assert "--- SKIP" not in result.stdout, f"use-leg skipped unexpectedly:\n{result.stdout}"
        assert "PASS" in result.stdout

    def test_teardown_deletes_exactly_the_created_aips(self, tmp_path):
        """STEP 4 (teardown): destroy deletes AIPs whose names match what deploy
        created via aip_name — closing the lifecycle with no orphans."""
        profile = _profile_with_resolved_arns()

        deleted: list[str] = []
        client = MagicMock()
        client.delete_inference_profile.side_effect = (
            lambda inferenceProfileIdentifier: deleted.append(inferenceProfileIdentifier)
        )
        with patch("boto3.client", return_value=client):
            DestroyCommand()._delete_persona_inference_profiles(profile, _Console())

        # Every per-tier AIP name deploy could have created (all tiers, since teardown
        # is authoritative and sweeps tiers a persona may have lost) + the legacy name.
        expected = set()
        for p in profile.personas:
            for tier in ("haiku", "sonnet", "opus"):
                expected.add(aip_name(_POOL, p["name"], tier))
            expected.add(f"{_POOL}-{p['name']}")  # legacy pre-FR-5.1 name
        assert set(deleted) == expected

    def test_lifecycle_invariant_names_match_across_all_steps(self, tmp_path):
        """The single cross-step invariant, asserted directly: for each persona,
        the AIP base-name embedded in every serialized ARN (package) is exactly the
        name destroy targets (teardown), for every entitled tier (deploy)."""
        profile = _profile_with_resolved_arns()
        cmd = PackageCommand()
        cmd.line = lambda *a, **k: None
        cmd._create_config(tmp_path, profile, profile.federated_role_arn, "direct", "ClaudeCode")
        cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))

        # Names destroy would delete (authoritative: all tiers + legacy).
        destroy_targets = set()
        for p in profile.personas:
            for tier in ("haiku", "sonnet", "opus"):
                destroy_targets.add(aip_name(_POOL, p["name"], tier))
            destroy_targets.add(f"{_POOL}-{p['name']}")

        # Names embedded in the serialized ARNs (what the helper routes).
        for p in cfg["ClaudeCode"]["personas"]:
            for tier, arn in p.get("inference_profile_arns", {}).items():
                embedded_name = arn.rsplit("/", 1)[-1]  # ...application-inference-profile/<name>
                assert embedded_name == aip_name(_POOL, p["name"], tier)
                assert embedded_name in destroy_targets, (
                    f"routed AIP {embedded_name!r} is not in destroy's delete set — "
                    "package/destroy naming has drifted"
                )
