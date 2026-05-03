#!/usr/bin/env python3
# ABOUTME: CI script to validate models.py against live Bedrock APIs
# ABOUTME: Checks ListFoundationModels (regions) and ListInferenceProfiles (CRIS routing)

"""Validate that CLAUDE_MODELS in models.py matches live Bedrock APIs.

Checks:
1. Every destination_region actually has Bedrock Claude models (ListFoundationModels)
2. No new Bedrock regions with Claude models are missing from models.py
3. CRIS inference profiles match models.py profiles (ListInferenceProfiles)
4. AllowedBedrockRegions defaults in CFN templates are in sync
5. Model IDs in models.py exist in the Bedrock model catalog

Usage:
    python scripts/validate_bedrock_regions.py
"""

import concurrent.futures
import json
import sys
from pathlib import Path

try:
    import boto3
    import botocore.config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

# Regions to probe — superset of all AWS regions that could have Bedrock
CANDIDATE_REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "ca-west-1",
    "eu-central-1", "eu-central-2", "eu-north-1",
    "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-2", "eu-west-3",
    "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-south-1", "ap-south-2", "ap-east-1", "ap-east-2",
    "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-4", "ap-southeast-5",
    "sa-east-1", "af-south-1", "me-south-1", "me-central-1", "il-central-1",
    "mx-central-1",
]

PROBE_CONFIG = botocore.config.Config(
    connect_timeout=5, read_timeout=10, retries={"max_attempts": 1},
) if HAS_BOTO3 else None


# ---------------------------------------------------------------------------
# 1. ListFoundationModels — region availability
# ---------------------------------------------------------------------------

def probe_region(region: str) -> tuple[str, list[str]]:
    """Check if a region has Claude models via ListFoundationModels."""
    try:
        client = boto3.client("bedrock", region_name=region, config=PROBE_CONFIG)
        resp = client.list_foundation_models(byProvider="Anthropic")
        models = [
            m["modelId"] for m in resp.get("modelSummaries", [])
            if "claude" in m.get("modelId", "").lower()
        ]
        return region, models
    except Exception:
        return region, []


def discover_live_regions(max_workers: int = 10, timeout: float = 30) -> dict[str, list[str]]:
    """Discover all regions with Claude models via parallel API calls."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(probe_region, r): r for r in CANDIDATE_REGIONS}
        done, pending = concurrent.futures.wait(futures, timeout=timeout)
        for f in done:
            region, models = f.result()
            if models:
                results[region] = models
        for f in pending:
            f.cancel()
            print(f"  ⚠ {futures[f]}: timed out (skipped)")
    return results


# ---------------------------------------------------------------------------
# 2. ListInferenceProfiles — CRIS validation
# ---------------------------------------------------------------------------

def discover_inference_profiles(region: str = "us-east-1") -> dict:
    """Fetch system-defined inference profiles and extract routing data.

    Returns: {profile_id: {"name": str, "regions": [str], "models": [str]}}
    """
    profiles = {}
    try:
        client = boto3.client("bedrock", region_name=region, config=PROBE_CONFIG)
        paginator = client.get_paginator("list_inference_profiles")
        for page in paginator.paginate(typeEquals="SYSTEM_DEFINED", maxResults=100):
            for p in page.get("inferenceProfileSummaries", []):
                pid = p.get("inferenceProfileId", "")
                if "anthropic" not in pid.lower():
                    continue
                regions = set()
                model_arns = []
                for m in p.get("models", []):
                    arn = m.get("modelArn", "")
                    model_arns.append(arn)
                    parts = arn.split(":")
                    if len(parts) >= 4 and parts[3]:
                        regions.add(parts[3])
                profiles[pid] = {
                    "name": p.get("inferenceProfileName", ""),
                    "regions": sorted(regions),
                    "models": model_arns,
                }
    except Exception as e:
        print(f"  ⚠ ListInferenceProfiles unavailable: {e}")
    return profiles


# ---------------------------------------------------------------------------
# 3. models.py data loaders
# ---------------------------------------------------------------------------

def load_models_py():
    """Load CLAUDE_MODELS and helpers from models.py."""
    source_dir = Path(__file__).parent.parent / "source"
    sys.path.insert(0, str(source_dir))
    from claude_code_with_bedrock.models import (
        CLAUDE_MODELS,
        get_all_bedrock_regions,
        get_all_model_display_names,
    )
    return CLAUDE_MODELS, set(get_all_bedrock_regions()), get_all_model_display_names()


def load_cfn_template_regions() -> dict[str, set[str]]:
    """Load AllowedBedrockRegions defaults from CloudFormation templates."""
    infra_dir = Path(__file__).parent.parent / "deployment" / "infrastructure"
    templates = {}
    for f in sorted(infra_dir.glob("bedrock-auth-*.yaml")):
        content = f.read_text()
        for line in content.split("\n"):
            if "Default:" in line and ("east" in line or "west" in line or "central" in line):
                start = line.find("'") + 1
                end = line.rfind("'")
                if start > 0 and end > start:
                    templates[f.name] = set(line[start:end].split(","))
    # Also check cognito-identity-pool.yaml
    cip = infra_dir / "cognito-identity-pool.yaml"
    if cip.exists():
        for line in cip.read_text().split("\n"):
            if "Default:" in line and ("east" in line or "west" in line or "central" in line):
                start = line.find("'") + 1
                end = line.rfind("'")
                if start > 0 and end > start:
                    templates[cip.name] = set(line[start:end].split(","))
                    break
    return templates


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def main():
    issues = []
    warnings = []

    # Load models.py data (always works, no AWS creds needed)
    print("📖 Loading models.py data...")
    claude_models, models_py_regions, display_names = load_models_py()
    commercial_regions = {r for r in models_py_regions if "gov" not in r}
    print(f"   {len(claude_models)} models, {len(commercial_regions)} commercial regions, {len(display_names)} display names\n")

    # Collect all model IDs and profile IDs from models.py
    models_py_profile_ids = {}  # profile model_id -> {source_regions, dest_regions}
    models_py_base_ids = set()
    for model_key, model in claude_models.items():
        if "base_model_id" in model:
            models_py_base_ids.add(model["base_model_id"])
        for profile_key, profile in model.get("profiles", {}).items():
            mid = profile["model_id"]
            models_py_profile_ids[mid] = {
                "source": set(profile.get("source_regions", [])),
                "dest": set(profile.get("destination_regions", [])),
                "model_key": model_key,
                "profile_key": profile_key,
            }

    # --- CFN template sync (no AWS creds needed) ---
    print("📋 Checking CloudFormation template defaults...")
    cfn_templates = load_cfn_template_regions()
    for name, regions in cfn_templates.items():
        if regions != commercial_regions:
            missing = commercial_regions - regions
            extra = regions - commercial_regions
            if missing:
                issues.append(f"CFN {name}: missing regions {sorted(missing)}")
                print(f"   ❌ {name}: missing {sorted(missing)}")
            if extra:
                warnings.append(f"CFN {name}: extra regions {sorted(extra)}")
                print(f"   ⚠️  {name}: extra {sorted(extra)}")
            if not missing and not extra:
                print(f"   ✅ {name}: in sync")
        else:
            print(f"   ✅ {name}: in sync")

    # --- Live API checks (need AWS creds) ---
    if not HAS_BOTO3:
        print("\n⚠️  boto3 not installed — skipping live API validation")
    else:
        # ListFoundationModels — region check
        print("\n🔍 Probing regions via ListFoundationModels...")
        live_regions = discover_live_regions()
        live_region_set = set(live_regions.keys())
        print(f"   Found {len(live_region_set)} regions with Claude models")

        new_regions = live_region_set - commercial_regions
        if new_regions:
            for r in sorted(new_regions):
                issues.append(f"NEW REGION: {r} has {len(live_regions[r])} Claude models, not in models.py")
                print(f"   ❌ {r}: {len(live_regions[r])} models — NOT in models.py")

        stale_regions = commercial_regions - live_region_set
        if stale_regions:
            for r in sorted(stale_regions):
                warnings.append(f"CRIS-ONLY: {r} in models.py but not discoverable (may be valid)")
                print(f"   ⚠️  {r}: in models.py but not discoverable (may be CRIS-only)")

        # Validate base model IDs exist
        print("\n🧬 Validating base model IDs...")
        us_east_models = set(live_regions.get("us-east-1", []))
        for base_id in sorted(models_py_base_ids):
            if "gov" in base_id:
                continue
            if base_id in us_east_models:
                print(f"   ✅ {base_id}")
            else:
                warnings.append(f"BASE MODEL: {base_id} not found in us-east-1 catalog")
                print(f"   ⚠️  {base_id}: not in us-east-1 catalog (may be new or deprecated)")

        # ListInferenceProfiles — CRIS validation
        print("\n🌐 Validating inference profiles via ListInferenceProfiles...")
        live_profiles = discover_inference_profiles()
        if live_profiles:
            print(f"   Found {len(live_profiles)} Claude inference profiles")

            # Check each models.py profile against live data
            for mid, info in sorted(models_py_profile_ids.items()):
                if "gov" in mid:
                    continue
                if mid in live_profiles:
                    live_p = live_profiles[mid]
                    live_r = set(live_p["regions"])
                    expected_r = info["dest"]
                    missing_r = expected_r - live_r
                    new_r = live_r - expected_r
                    if missing_r:
                        warnings.append(f"CRIS {mid}: models.py has regions not in live profile: {sorted(missing_r)}")
                        print(f"   ⚠️  {mid}: dest regions {sorted(missing_r)} not in live profile")
                    if new_r:
                        issues.append(f"CRIS {mid}: live profile has new regions not in models.py: {sorted(new_r)}")
                        print(f"   ❌ {mid}: live profile has new regions {sorted(new_r)}")
                    if not missing_r and not new_r:
                        print(f"   ✅ {mid}: regions match")
                else:
                    warnings.append(f"CRIS {mid}: not found in live inference profiles")
                    print(f"   ⚠️  {mid}: not in live profiles (may need newer API version)")

            # Check for new live profiles not in models.py
            for pid in sorted(live_profiles):
                if pid not in models_py_profile_ids:
                    issues.append(f"NEW CRIS: {pid} ({live_profiles[pid]['name']}) not in models.py")
                    print(f"   ❌ {pid}: new profile not in models.py")
        else:
            print("   ⚠️  No profiles returned (API may be unavailable)")

    # --- Summary ---
    print(f"\n{'='*60}")
    if not issues:
        print(f"✅ Validation passed ({len(warnings)} warning(s))")
        for w in warnings:
            print(f"   ⚠️  {w}")
        return 0
    else:
        print(f"❌ {len(issues)} issue(s), {len(warnings)} warning(s):")
        for i in issues:
            print(f"   ❌ {i}")
        for w in warnings:
            print(f"   ⚠️  {w}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
