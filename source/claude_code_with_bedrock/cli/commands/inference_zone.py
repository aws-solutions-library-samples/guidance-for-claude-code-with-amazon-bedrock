# ABOUTME: ccwb inference-zone CLI commands (create/list/delete).
# ABOUTME: Interactive wizard for per-zone Bedrock application inference profiles.

"""Per-zone Bedrock application inference profile management (GDPR).

A *zone* is a compliance boundary (e.g. ``france``, ``eu``, ``us``).
Each zone can host one or more Claude models. This command creates
one Bedrock application inference profile per (zone × model) pair,
tagged with ``Zone=<zone>``, ``ccwb:Region=<region>``, and ccwb
ownership metadata.

The ``Zone`` tag is the load-bearing identifier for IAM enforcement
under ``enforce_project_isolation=True``; ``ccwb:Region`` closes the
cross-region data-residency loophole by binding the profile to a
specific region at invocation time.

Admins run ``ccwb inference-zone create`` interactively (wizard with
zone name, region-vs-cross-region backing, multi-select model list).
The command discovers available models live via ``bedrock:ListFoundation
Models`` and falls back to ``claude_code_with_bedrock.models.CLAUDE_MODELS``
when the API is unreachable or returns an unfamiliar naming scheme.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import boto3
import questionary
from botocore.exceptions import ClientError, NoCredentialsError
from cleo.commands.command import Command
from cleo.helpers import option
from rich import box
from rich.console import Console
from rich.table import Table

from claude_code_with_bedrock.config import Config, Profile
from claude_code_with_bedrock.models import CLAUDE_MODELS

# --------------------------------------------------------------------------- #
# Zone name validation
# --------------------------------------------------------------------------- #

_ZONE_NAME_PATTERN = re.compile(r"^[a-z]+$")
_ZONE_NAME_MAX_LEN = 32
_ZONE_RESERVED = frozenset({"aws", "amazon", "bedrock", "default", "system", "admin"})

_ZONE_NAME_RULE = (
    "Zone names must be ONE word of lowercase letters a-z only. "
    "No digits, hyphens, underscores, uppercase letters, or special characters. "
    "Examples: france, europe, restricted, production, sandbox."
)


def validate_zone_name(raw: str) -> str:
    """Validate and return a zone name. Raises ValueError on violation."""
    if not raw:
        raise ValueError("Zone name cannot be empty. " + _ZONE_NAME_RULE)
    if len(raw) > _ZONE_NAME_MAX_LEN:
        raise ValueError(
            f"Zone name '{raw}' is too long (max {_ZONE_NAME_MAX_LEN} characters)."
        )
    if not _ZONE_NAME_PATTERN.match(raw):
        raise ValueError(f"Zone name '{raw}' is invalid. " + _ZONE_NAME_RULE)
    if raw in _ZONE_RESERVED:
        raise ValueError(
            f"Zone name '{raw}' is reserved. Please choose a different name."
        )
    return raw


def _zone_name_prompt_validator(value: str) -> bool | str:
    """questionary-compatible validator: return True or an error message."""
    try:
        validate_zone_name(value.strip())
        return True
    except ValueError as e:
        return str(e)


# --------------------------------------------------------------------------- #
# Model discovery
# --------------------------------------------------------------------------- #

# Anthropic foundation-model-ID pattern. The suffix shape varies across
# model releases and we've seen all of these in the wild:
#   anthropic.claude-opus-4-7                            (newest format, no date, no -v)
#   anthropic.claude-sonnet-4-6                          (newest format)
#   anthropic.claude-opus-4-6-v1                         (has -v but no date)
#   anthropic.claude-opus-4-5-20251101-v1:0              (has date + -v + :N)
#   anthropic.claude-sonnet-4-5-20250929-v1:0            (date + -v + :N)
#   anthropic.claude-haiku-4-5-20251001-v1:0             (date + -v + :N)
# Cross-region (CRIS) ids add a zone prefix: us.anthropic..., eu.anthropic...
# We accept all variants so future Anthropic releases with new suffix
# shapes keep working without requiring code changes.
_ANTHROPIC_MODEL_RE = re.compile(
    r"^(?:[a-z]{2,6}\.)?"                        # optional zone prefix "us.", "eu.", "apac.", "global."
    r"anthropic\."
    r"claude-(?P<family>opus|sonnet|haiku)"
    r"-(?P<major>\d)"                            # single-digit major (4, 5, ...)
    r"-(?P<minor>\d{1,2})"                       # 1-2 digit minor (1-99). Excludes 8-digit date
    r"(?![\d])"                                   # boundary: next char must not be a digit
    r"(?:-\d{8})?"                                # optional date stamp
    r"(?:-v\d+)?"                                 # optional -v<rev>
    r"(?::\d+)?$"                                 # optional :N suffix on inference profile IDs
)


@dataclass(frozen=True)
class ModelChoice:
    """One Claude model available for selection."""

    short_name: str            # e.g. "opus-4-6"
    display_name: str          # e.g. "Claude Opus 4.6"
    family: str                # opus | sonnet | haiku
    major: int
    minor: int
    foundation_arn_template: str  # arn pattern without partition/region filled
    cris_profile_id: str | None   # e.g. "us.anthropic.claude-opus-4-6-v1" if available

    def __lt__(self, other: ModelChoice) -> bool:
        # Family order, then newer versions first
        family_order = {"opus": 0, "sonnet": 1, "haiku": 2}
        return (
            family_order.get(self.family, 99),
            -self.major,
            -self.minor,
        ) < (
            family_order.get(other.family, 99),
            -other.major,
            -other.minor,
        )


def _parse_model_id(model_id: str) -> tuple[str, int, int] | None:
    """Return (family, major, minor) for a recognized Anthropic ID, else None."""
    m = _ANTHROPIC_MODEL_RE.match(model_id)
    if not m:
        return None
    return m.group("family"), int(m.group("major")), int(m.group("minor"))


def _discover_models_live(region: str) -> list[ModelChoice]:
    """Try to enumerate Anthropic models in the region via Bedrock APIs.

    Returns the latest 2 versions per family (opus, sonnet, haiku). Returns
    an empty list if the API call fails for any reason (no creds, region
    unreachable, API throttling). Callers should fall back to ``_discover
    _models_from_models_py()``.
    """
    try:
        client = boto3.client("bedrock", region_name=region)
        # Foundation models in this region:
        fm_resp = client.list_foundation_models(byProvider="anthropic")
    except (ClientError, NoCredentialsError, Exception):
        return []

    # CRIS profiles (system-defined) also enumerate what cross-region routing
    # exists so we can surface them as an alternative backing.
    try:
        sys_resp = client.list_inference_profiles(typeEquals="SYSTEM_DEFINED")
        sys_profiles = sys_resp.get("inferenceProfileSummaries", []) or []
    except (ClientError, Exception):
        sys_profiles = []

    # Build a map short_name -> ModelChoice. Keep only INVOKE-capable chat models.
    by_short: dict[str, ModelChoice] = {}
    for fm in fm_resp.get("modelSummaries", []) or []:
        model_id = fm.get("modelId", "")
        parsed = _parse_model_id(model_id)
        if not parsed:
            continue
        family, major, minor = parsed
        # Only interactive chat modalities — skip embeddings/image.
        if "TEXT" not in (fm.get("outputModalities") or []):
            continue
        # Only models that support on-demand invocation or inference profile.
        lifecycle = fm.get("modelLifecycle", {}).get("status", "ACTIVE")
        if lifecycle != "ACTIVE":
            continue
        short = f"{family}-{major}-{minor}"
        if short in by_short:
            continue  # already recorded

        # Find a matching CRIS profile for this family/version, if any.
        cris_id = None
        for sp in sys_profiles:
            sp_id = sp.get("inferenceProfileId", "")
            sp_parsed = _parse_model_id(sp_id)
            if sp_parsed == (family, major, minor):
                cris_id = sp_id
                break

        by_short[short] = ModelChoice(
            short_name=short,
            display_name=f"Claude {family.capitalize()} {major}.{minor}",
            family=family,
            major=major,
            minor=minor,
            foundation_arn_template=model_id,  # we'll splice region/partition when building copyFrom
            cris_profile_id=cris_id,
        )

    # Keep only the top 2 versions per family.
    families: dict[str, list[ModelChoice]] = {}
    for mc in by_short.values():
        families.setdefault(mc.family, []).append(mc)

    keep: list[ModelChoice] = []
    for lst in families.values():
        lst.sort()  # uses __lt__ = newer-first
        keep.extend(lst[:2])
    return sorted(keep)


def _discover_models_from_models_py() -> list[ModelChoice]:
    """Fallback: enumerate from the repo's CLAUDE_MODELS dict.

    This only runs when live Bedrock API discovery fails — typically
    missing credentials, throttling, or a region with no Bedrock
    endpoint. The hardcoded list in ``claude_code_with_bedrock/models.py``
    is maintained alongside releases but always lags by days to weeks,
    so admins should treat fallback output as a degraded experience and
    rerun when their AWS credentials are valid.
    """
    out: list[ModelChoice] = []
    for short, meta in CLAUDE_MODELS.items():
        # Skip variants that aren't straightforward (govcloud, etc.).
        # The models.py dict includes govcloud overlays with suffixes
        # like "sonnet-4-5-govcloud" that should never surface in a
        # generic model picker — they belong in specialized govcloud flows.
        m = re.match(r"^(opus|sonnet|haiku)-(\d)-(\d{1,2})$", short)
        if not m:
            continue
        family, major, minor = m.group(1), int(m.group(2)), int(m.group(3))
        base_model = meta.get("base_model_id", "")
        profiles = meta.get("profiles", {}) or {}
        # Pick "us" as the preferred CRIS if present; caller can switch.
        cris_id = None
        for cris_key in ("us", "eu", "apac", "global"):
            if cris_key in profiles:
                cris_id = profiles[cris_key].get("model_id")
                break
        out.append(
            ModelChoice(
                short_name=short,
                display_name=meta.get("name", f"Claude {family.capitalize()} {major}.{minor}"),
                family=family,
                major=major,
                minor=minor,
                foundation_arn_template=base_model,
                cris_profile_id=cris_id,
            )
        )
    # Top 2 per family, newest first.
    families: dict[str, list[ModelChoice]] = {}
    for mc in out:
        families.setdefault(mc.family, []).append(mc)
    keep: list[ModelChoice] = []
    for lst in families.values():
        lst.sort()
        keep.extend(lst[:2])
    return sorted(keep)


def discover_models(region: str) -> tuple[list[ModelChoice], str]:
    """Return (models, source) where source is 'live' or 'fallback'."""
    live = _discover_models_live(region)
    if live:
        return live, "live"
    return _discover_models_from_models_py(), "fallback"


# --------------------------------------------------------------------------- #
# CRIS (cross-region) profile discovery
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CrisProfile:
    """A system-defined cross-region inference profile available to the account."""

    profile_id: str        # e.g. "us.anthropic.claude-opus-4-6-v1"
    profile_arn: str       # full ARN
    zone_prefix: str       # "us" | "eu" | "apac" | "global"
    model_short: str       # "opus-4-6"


# Representative region per CRIS zone — AWS's ListInferenceProfiles is
# region-scoped and only returns system-defined profiles whose coverage
# includes the calling region. To see all CRIS zones (us, eu, apac, au,
# global, ...), we query from a region within each. Querying a single
# region (e.g. us-west-2) returns only `us.*` and `global.*`, missing
# the EU / APAC / AU profiles entirely.
#
# Values chosen for broad Bedrock coverage; any reachable region from
# the CRIS's set would work. Listed in discovery preference order —
# the first reachable region per CRIS is the one we probe.
_CRIS_DISCOVERY_REGIONS = [
    ("us",     ["us-east-1", "us-west-2"]),
    ("eu",     ["eu-west-1", "eu-central-1", "eu-west-3"]),
    ("apac",   ["ap-northeast-1", "ap-southeast-1", "ap-southeast-2"]),
    ("au",     ["ap-southeast-2", "ap-southeast-4"]),
    # "global" typically surfaces from any region but we include it so
    # it's never missed.
    ("global", ["us-east-1", "us-west-2", "eu-west-1"]),
]


def _list_cris_in_region(region: str) -> list[CrisProfile]:
    """Query SYSTEM_DEFINED inference profiles from one region."""
    try:
        client = boto3.client("bedrock", region_name=region)
        resp = client.list_inference_profiles(typeEquals="SYSTEM_DEFINED")
    except (ClientError, NoCredentialsError, Exception):
        return []

    out: list[CrisProfile] = []
    for sp in resp.get("inferenceProfileSummaries", []) or []:
        sp_id = sp.get("inferenceProfileId", "")
        sp_arn = sp.get("inferenceProfileArn", "")
        if not sp_id or not sp_arn:
            continue
        parsed = _parse_model_id(sp_id)
        if not parsed:
            continue
        family, major, minor = parsed
        # Extract zone prefix (everything before the first dot) — e.g. "us"
        prefix = sp_id.split(".", 1)[0] if "." in sp_id else ""
        if not prefix:
            continue
        out.append(
            CrisProfile(
                profile_id=sp_id,
                profile_arn=sp_arn,
                zone_prefix=prefix,
                model_short=f"{family}-{major}-{minor}",
            )
        )
    return out


def discover_cris_profiles(primary_region: str) -> list[CrisProfile]:
    """Enumerate CRIS profiles across multiple region probes and merge.

    AWS's `ListInferenceProfiles SYSTEM_DEFINED` is region-scoped: a
    single call from `us-west-2` returns only `us.*` and `global.*`,
    missing `eu.*`, `apac.*`, and `au.*` entirely. We probe one region
    per CRIS zone and deduplicate by profile ARN.

    ``primary_region`` is used as a first-pass optimization: if the
    admin is already calling from a Bedrock-enabled region, we try it
    first for whichever CRIS it covers before probing the others.
    """
    seen_arns: set[str] = set()
    merged: list[CrisProfile] = []

    # Build the probe sequence — primary_region first, then one region
    # per CRIS zone. Skip regions we already probed.
    probes: list[str] = []
    if primary_region:
        probes.append(primary_region)
    for _zone, regions in _CRIS_DISCOVERY_REGIONS:
        for r in regions:
            if r not in probes:
                probes.append(r)
                break  # one region per CRIS is enough

    for r in probes:
        try:
            for cp in _list_cris_in_region(r):
                if cp.profile_arn in seen_arns:
                    continue
                seen_arns.add(cp.profile_arn)
                merged.append(cp)
        except Exception:
            continue
    return merged


# --------------------------------------------------------------------------- #
# Region discovery
# --------------------------------------------------------------------------- #

# Every AWS commercial region where Amazon Bedrock is available as of 2026-04.
# Used as the candidate list for region probing — not a strict allow-list.
# Keeping this explicit instead of calling ec2:DescribeRegions because
# Bedrock availability lags behind regional launches and a probe-per-region
# is the most reliable signal anyway.
_BEDROCK_CANDIDATE_REGIONS = [
    # North America
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "ca-west-1",
    # South America
    "sa-east-1",
    # Europe
    "eu-west-1", "eu-west-2", "eu-west-3",
    "eu-central-1", "eu-central-2",
    "eu-north-1", "eu-south-1", "eu-south-2",
    # Asia Pacific
    "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
    "ap-southeast-1", "ap-southeast-2", "ap-southeast-3", "ap-southeast-4",
    "ap-south-1", "ap-south-2",
    "ap-east-1", "ap-east-2",
    # Middle East
    "me-central-1", "me-south-1",
    # Africa
    "af-south-1",
    # GovCloud (partition-separate; admin can pick if their account is in GC)
    "us-gov-east-1", "us-gov-west-1",
]


# AWS cross-region inference profile (CRIS) region sets as of 2026-04.
# The CRIS zones are AWS-defined: each system-defined inference profile
# carries the caller's request to one of the regions in its set. New
# regions get added to these sets over time; the values here are the
# current published coverage and are only used for informational hints
# and for the "which region to tag this profile with" picker.
_CRIS_REGION_SETS: dict[str, list[str]] = {
    "us": [
        "us-east-1", "us-east-2", "us-west-1", "us-west-2",
        "ca-central-1", "ca-west-1",
    ],
    "eu": [
        "eu-central-1", "eu-central-2",
        "eu-north-1", "eu-south-1", "eu-south-2",
        "eu-west-1", "eu-west-2", "eu-west-3",
    ],
    "apac": [
        "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
        "ap-southeast-1", "ap-southeast-2", "ap-southeast-4",
        "ap-south-1", "ap-south-2",
        "ap-east-1",
    ],
    "au": [
        "ap-southeast-2", "ap-southeast-4",
    ],
    "global": [
        # The "global" CRIS spans every commercial region Bedrock supports.
        # Users invoke it from any region; AWS routes to whichever endpoint
        # has capacity. We list a representative US entry here as the
        # tag-region default; the admin can pick any reachable region.
        "us-east-1", "us-east-2", "us-west-1", "us-west-2",
        "ca-central-1", "ca-west-1",
        "eu-central-1", "eu-central-2",
        "eu-north-1", "eu-south-1", "eu-south-2",
        "eu-west-1", "eu-west-2", "eu-west-3",
        "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
        "ap-southeast-1", "ap-southeast-2", "ap-southeast-4",
        "ap-south-1", "ap-south-2",
    ],
}


def _cris_region_list(zone_prefix: str) -> list[str]:
    """Return the canonical list of regions covered by a CRIS zone prefix.

    Falls back to the commercial candidate list if the prefix is unknown
    (e.g. a new AWS zone we don't yet track — the caller will still have
    the region probing narrow it down).
    """
    return _CRIS_REGION_SETS.get(zone_prefix, list(_BEDROCK_CANDIDATE_REGIONS))


def _cris_regions_hint(zone_prefix: str) -> str:
    """One-line human summary of a CRIS zone's region set for the picker."""
    regions = _CRIS_REGION_SETS.get(zone_prefix, [])
    if not regions:
        return "regions unknown"
    if len(regions) <= 3:
        return ", ".join(regions)
    return f"{regions[0]}, {regions[1]}, ... ({len(regions)} regions)"


def discover_bedrock_regions(candidate_regions: list[str] | None = None) -> list[str]:
    """Return regions from ``candidate_regions`` that answer Bedrock calls.

    If ``candidate_regions`` is None or empty, the full commercial+GovCloud
    Bedrock region list is probed. The admin's profile-level
    ``allowed_bedrock_regions`` list is intentionally NOT used as a filter
    here — zone creation should be independent of which CRIS the admin
    picked at ``ccwb init`` time. A customer who wants an EU zone shouldn't
    have to re-init their profile just because they originally picked a
    US cross-region inference profile as their default.

    Probing is sequential because the calls are cheap (a single bedrock:
    ListFoundationModels each) and the number of regions is under 30.
    """
    ok: list[str] = []
    for r in (candidate_regions if candidate_regions else _BEDROCK_CANDIDATE_REGIONS):
        try:
            client = boto3.client("bedrock", region_name=r)
            client.list_foundation_models(byProvider="anthropic")
            ok.append(r)
        except Exception:
            continue
    return ok


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _rewrite_arn_region(arn: str, new_region: str) -> str:
    """Return an ARN with its region segment replaced.

    ARN format: ``arn:<partition>:<service>:<region>:<account>:<resource>``.
    We only touch the fourth segment. All other segments pass through.

    Used for CRIS source ARNs: bedrock:ListInferenceProfiles surfaces
    the profile ARN in whichever region we queried, but CreateApplication
    InferenceProfile requires the copyFrom source to be in the SAME
    region as the call. A system-defined CRIS profile is routable from
    any region in its coverage set — we just need the caller's region
    in the ARN string for the API check.
    """
    parts = arn.split(":", 5)
    if len(parts) < 6:
        return arn  # not an ARN we recognize; return as-is
    parts[3] = new_region
    return ":".join(parts)


def _save_zone_mapping(
    config: Config,
    profile: Profile,
    zone: str,
    model_short: str,
    arn: str,
) -> None:
    """Persist the resulting ARN into the active ccwb profile."""
    if not isinstance(profile.zone_inference_profiles, dict):
        profile.zone_inference_profiles = {}
    profile.zone_inference_profiles.setdefault(zone, {})[model_short] = arn
    config.save_profile(profile)


def _remove_zone_mapping(
    config: Config,
    profile: Profile,
    zone: str,
    model_short: str | None = None,
) -> None:
    """Remove a single (zone, model) or all models for a zone."""
    mapping = getattr(profile, "zone_inference_profiles", {}) or {}
    if zone not in mapping:
        return
    if model_short:
        mapping[zone].pop(model_short, None)
        if not mapping[zone]:
            del mapping[zone]
    else:
        del mapping[zone]
    profile.zone_inference_profiles = mapping
    config.save_profile(profile)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


class InferenceZoneCreateCommand(Command):
    """Create (or extend) a zone with one or more Bedrock inference profiles."""

    name = "inference-zone create"
    description = "Create Bedrock application inference profiles for a GDPR zone"

    options = [
        option("profile", description="ccwb configuration profile", flag=False, default=None),
        option(
            "zone",
            description="Zone name (lowercase letters only; skip to prompt)",
            flag=False,
            default=None,
        ),
    ]

    def handle(self) -> int:  # pragma: no cover - interactive CLI
        console = Console()
        config = Config.load()
        profile_name = self.option("profile") or config.active_profile
        profile = config.get_profile(profile_name)
        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found.[/red]")
            return 1

        # ---- Zone name ----
        raw_zone = self.option("zone")
        if raw_zone:
            try:
                zone = validate_zone_name(raw_zone.strip().lower())
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                return 1
        else:
            console.print(
                "\n[bold cyan]Zone name[/bold cyan]  "
                "[dim](one word, lowercase letters only)[/dim]"
            )
            answer = questionary.text(
                "Zone name:",
                instruction=f"({_ZONE_NAME_RULE})",
                validate=_zone_name_prompt_validator,
            ).ask()
            if answer is None:
                console.print("[yellow]Cancelled.[/yellow]")
                return 1
            zone = answer.strip().lower()

        # ---- Pick the cross-region inference (CRIS) zone ----
        # Modern Claude models (4.5+) do NOT support on-demand invocation
        # against bare foundation-model ARNs — CreateApplicationInferenceProfile
        # must copyFrom a CRIS profile. So the admin's real choice is which
        # CRIS zone backs this ccwb zone: us (6 US+Canada regions), eu (7 EU
        # regions), apac (multiple APAC regions), or global (all).
        #
        # The admin's ccwb zone name (e.g. "france") is a ccwb concept; it's
        # separate from the AWS CRIS zone prefix. One ccwb zone "france" is
        # typically backed by the "eu" CRIS, one ccwb zone "us" typically
        # backed by the "us" CRIS — but nothing prevents an admin from
        # backing a ccwb zone "sandbox" with the "global" CRIS if they want.
        console.print(f"\n[bold cyan]Configuration for zone '{zone}'[/bold cyan]")

        # CRIS discovery region: use the profile's primary region as the
        # control-plane endpoint. CRIS profile ARNs are region-partitioned,
        # so we need a reachable region to query.
        discovery_region = profile.aws_region
        console.print(
            f"[dim]Discovering cross-region inference profiles via {discovery_region}...[/dim]"
        )
        all_cris = discover_cris_profiles(discovery_region)
        if not all_cris:
            console.print(
                "[red]No cross-region inference profiles visible from "
                f"{discovery_region}. Check that your admin credentials have "
                "bedrock:ListInferenceProfiles and the region is Bedrock-enabled.[/red]"
            )
            return 1

        zone_prefixes = sorted({c.zone_prefix for c in all_cris})
        console.print(
            "[dim]Modern Claude models (4.5+) require a cross-region inference "
            "profile as the backing — bare foundation-model invocation is not "
            "supported. Pick the AWS CRIS zone that covers the regions your "
            f"ccwb zone '{zone}' should serve:[/dim]"
        )
        cris_prefix = questionary.select(
            "AWS cross-region inference zone:",
            choices=[
                questionary.Choice(
                    f"{p}  ({_cris_regions_hint(p)})",
                    value=p,
                )
                for p in zone_prefixes
            ],
            default=zone_prefixes[0],
        ).ask()
        if cris_prefix is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 1

        # ---- Pick the authoritative region for the ccwb:Region tag ----
        # The app-inference-profile itself lives in one region (the region
        # where we call CreateApplicationInferenceProfile). The CRIS it
        # copyFroms routes across multiple regions, but the profile resource
        # itself is regional. We tag it with ccwb:Region=<that region> so
        # IAM can enforce aws:ResourceTag/ccwb:Region == aws:RequestedRegion
        # and pin residency.
        cris_regions = _cris_region_list(cris_prefix)
        console.print(
            f"[dim]Checking which {cris_prefix}.* regions your account can reach for Bedrock...[/dim]"
        )
        reachable = discover_bedrock_regions(cris_regions)
        if not reachable:
            console.print(
                f"[red]None of the {cris_prefix}.* CRIS regions is reachable from your account. "
                f"Requested: {', '.join(cris_regions)}[/red]"
            )
            return 1
        region_for_create = questionary.select(
            f"Region where the '{zone}' inference profiles will be created:",
            choices=reachable,
            default=reachable[0],
            instruction="(determines the ccwb:Region tag IAM uses for residency enforcement)",
        ).ask()
        if region_for_create is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 1

        # ---- Model selection (multi-select) ----
        # Filter models to those that have a CRIS profile under the chosen
        # prefix — we can't back a zone with a model whose CRIS doesn't exist.
        console.print(
            f"\n[dim]Discovering Claude models in {cris_prefix}.* CRIS...[/dim]"
        )
        models, source = discover_models(discovery_region)
        cris_model_shorts = {
            c.model_short for c in all_cris if c.zone_prefix == cris_prefix
        }
        models = [m for m in models if m.short_name in cris_model_shorts]

        if not models:
            console.print(
                f"[red]No Claude models available in the '{cris_prefix}' CRIS.[/red]"
            )
            return 1
        if source == "fallback":
            console.print(
                "[yellow]Using built-in model list (Bedrock API unreachable or "
                "returned unfamiliar model IDs).[/yellow]"
            )

        selected_shorts = questionary.checkbox(
            f"Which models to enable for zone '{zone}'? (space to toggle, enter to confirm)",
            choices=[
                questionary.Choice(f"{m.display_name}  [{m.short_name}]", value=m.short_name)
                for m in models
            ],
        ).ask()
        if not selected_shorts:
            console.print("[yellow]No models selected. Aborted.[/yellow]")
            return 1

        # ---- Create each selected profile ----
        bedrock = boto3.client("bedrock", region_name=region_for_create)
        created: list[tuple[str, str]] = []  # (short, arn)
        failures: list[tuple[str, str]] = []  # (short, error)

        for short in selected_shorts:
            mc = next(m for m in models if m.short_name == short)

            # Always copyFrom the chosen CRIS profile. AWS routes invocations
            # across the CRIS's region set; our app-inference-profile adds
            # the Zone / ccwb:Region tags that gate access via IAM.
            cris = next(
                (c for c in all_cris if c.zone_prefix == cris_prefix and c.model_short == short),
                None,
            )
            if not cris:
                failures.append(
                    (short, f"No {cris_prefix}.{short} CRIS profile found")
                )
                continue
            # CRIS ARNs are region-partitioned: the discovered ARN reflects
            # whichever probe region surfaced the profile (often eu-west-1 for
            # the eu.* CRIS). AWS requires the `copyFrom` source ARN to be in
            # the SAME region as the CreateApplicationInferenceProfile call,
            # or we get `ResourceNotFoundException: Inference profile not found`.
            # Rewrite the ARN's region segment to match region_for_create.
            copy_from = _rewrite_arn_region(cris.profile_arn, region_for_create)

            inf_name = f"{zone}-{short}"
            tags = [
                {"key": "Zone", "value": zone},
                {"key": "ccwb:Region", "value": region_for_create},
                {"key": "ccwb:Profile", "value": profile.name},
                {"key": "ccwb:Model", "value": short},
                {"key": "ccwb:CrisZone", "value": cris_prefix},
            ]
            try:
                resp = bedrock.create_inference_profile(
                    inferenceProfileName=inf_name,
                    description=f"ccwb {zone} zone profile for {mc.display_name}",
                    modelSource={"copyFrom": copy_from},
                    tags=tags,
                )
                arn = resp.get("inferenceProfileArn")
                if not arn:
                    failures.append((short, "CreateInferenceProfile returned no ARN"))
                    continue
                created.append((short, arn))
                _save_zone_mapping(config, profile, zone, short, arn)
            except ClientError as e:
                failures.append((short, str(e)))

        # ---- Summary ----
        if created:
            table = Table(
                title=f"Zone '{zone}' — {len(created)} inference profile(s) created",
                box=box.ROUNDED,
            )
            table.add_column("Model", style="magenta")
            table.add_column("Region", style="cyan")
            table.add_column("ARN")
            for short, arn in created:
                table.add_row(short, region_for_create, arn)
            console.print(table)
            console.print(
                f"\n[bold]How end users in zone '{zone}' configure their environment:[/bold]\n"
                f"Claude Code needs BOTH the model ARN and the matching AWS region.\n"
                f"Pair them when setting up the shell (example for PowerShell):\n\n"
                f"  [cyan]$env:ANTHROPIC_MODEL = '<one of the ARNs above>'[/cyan]\n"
                f"  [cyan]$env:AWS_REGION = '{region_for_create}'[/cyan]\n\n"
                f"Or on macOS/Linux:\n\n"
                f"  [cyan]export ANTHROPIC_MODEL='<arn>'[/cyan]\n"
                f"  [cyan]export AWS_REGION='{region_for_create}'[/cyan]\n\n"
                f"Or inside Claude Code after auth, set the model with:\n\n"
                f"  [cyan]/model <arn>[/cyan]\n\n"
                f"[yellow]Important:[/yellow] AWS_REGION must be [bold]{region_for_create}[/bold] "
                f"to match the profile's resource region — without it the AWS SDK "
                f"routes the request to the wrong endpoint and returns 'invalid ARN'.\n"
                f"Share the ARN + region table above with your users.\n"
                f"\n[dim]Users inside Claude Code can also use:[/dim]"
                "  [cyan]/model <arn>[/cyan]"
            )
        if failures:
            for short, err in failures:
                console.print(f"[red]FAILED {short}: {err}[/red]")
            return 1
        return 0


class InferenceZoneListCommand(Command):
    """List zone -> (model, ARN) mappings recorded in the active ccwb profile."""

    name = "inference-zone list"
    description = "List zones and their inference profile ARNs"

    options = [
        option("profile", description="ccwb configuration profile", flag=False, default=None),
        option("zone", description="Filter to a single zone", flag=False, default=None),
    ]

    def handle(self) -> int:  # pragma: no cover - thin CLI glue
        console = Console()
        config = Config.load()
        profile_name = self.option("profile") or config.active_profile
        profile = config.get_profile(profile_name)
        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found.[/red]")
            return 1

        mapping = getattr(profile, "zone_inference_profiles", {}) or {}
        zone_filter = (self.option("zone") or "").strip().lower() or None

        if zone_filter:
            zones_to_show = {zone_filter: mapping.get(zone_filter, {})}
            if not zones_to_show[zone_filter]:
                console.print(
                    f"[yellow]No profiles recorded for zone '{zone_filter}'.[/yellow]"
                )
                return 0
        else:
            zones_to_show = mapping

        if not zones_to_show:
            console.print(
                "[yellow]No zones recorded.[/yellow] "
                "Run [cyan]ccwb inference-zone create[/cyan]."
            )
            return 0

        for zone in sorted(zones_to_show):
            models = zones_to_show[zone]
            table = Table(title=f"Zone '{zone}'", box=box.ROUNDED)
            table.add_column("Model", style="magenta")
            table.add_column("Region", style="cyan")
            table.add_column("ARN")
            for short in sorted(models):
                arn = models[short]
                # Extract region from the ARN: arn:aws:bedrock:<region>:...
                parts = arn.split(":", 5)
                region = parts[3] if len(parts) >= 4 else "?"
                table.add_row(short, region, arn)
            console.print(table)

        # Print the exact env-var commands so the admin can copy directly
        # into an email to zone users. Region is extracted from each ARN.
        if not zone_filter and len(zones_to_show) > 0:
            console.print(
                "\n[dim]End users need BOTH ANTHROPIC_MODEL and AWS_REGION set "
                "together (the region must match the ARN's region segment).[/dim]"
            )
        return 0


class InferenceZoneDeleteCommand(Command):
    """Delete all (or one specific) Bedrock inference profile for a zone."""

    name = "inference-zone delete"
    description = "Delete zone inference profile(s)"

    options = [
        option("profile", description="ccwb configuration profile", flag=False, default=None),
        option("zone", description="Zone name to delete from", flag=False),
        option(
            "model",
            description="Specific model short-name; omit to delete ALL models for the zone",
            flag=False,
            default=None,
        ),
        option("region", description="AWS region", flag=False, default=None),
        option("yes", "y", description="Skip confirmation prompt", flag=True),
    ]

    def handle(self) -> int:  # pragma: no cover - thin CLI glue
        console = Console()
        config = Config.load()
        profile_name = self.option("profile") or config.active_profile
        profile = config.get_profile(profile_name)
        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found.[/red]")
            return 1

        zone_raw = (self.option("zone") or "").strip().lower()
        if not zone_raw:
            console.print("[red]--zone is required[/red]")
            return 1
        try:
            zone = validate_zone_name(zone_raw)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return 1

        model_short = (self.option("model") or "").strip() or None
        region = self.option("region") or profile.aws_region

        mapping = getattr(profile, "zone_inference_profiles", {}) or {}
        zone_map = mapping.get(zone, {})
        if not zone_map:
            console.print(
                f"[red]Zone '{zone}' has no profiles recorded in the ccwb profile.[/red]"
            )
            return 1

        if model_short:
            if model_short not in zone_map:
                console.print(
                    f"[red]Zone '{zone}' has no '{model_short}' profile recorded.[/red]"
                )
                return 1
            targets = {model_short: zone_map[model_short]}
        else:
            targets = dict(zone_map)

        # Confirm
        if not self.option("yes"):
            console.print(f"\n[bold]About to delete from zone '{zone}':[/bold]")
            for short, arn in targets.items():
                console.print(f"  {short}  {arn}")
            resp = self.ask("\nDelete? [y/N] ", default="n")
            if not resp or resp.lower() not in ("y", "yes"):
                console.print("Aborted.")
                return 1

        bedrock = boto3.client("bedrock", region_name=region)
        failed = []
        for short, arn in targets.items():
            try:
                bedrock.delete_inference_profile(inferenceProfileIdentifier=arn)
                _remove_zone_mapping(config, profile, zone, short)
                console.print(f"[green]Deleted[/green] {short}  {arn}")
            except ClientError as e:
                failed.append((short, str(e)))
                console.print(f"[red]FAILED {short}: {e}[/red]")
        return 1 if failed else 0
