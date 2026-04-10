# ABOUTME: CLI commands for managing per-user Bedrock Application Inference Profiles
# ABOUTME: Provides list and set-default subcommands for user inference profile ARN management

"""Inference profiles commands — list and set the default model ARN."""

import json
from pathlib import Path

import boto3
from cleo.commands.command import Command
from cleo.helpers import option
from rich import box
from rich.console import Console
from rich.table import Table

from claude_code_with_bedrock.config import Config
from claude_code_with_bedrock.models import (
    get_application_profile_name,
    get_enabled_inference_profile_models,
)


def _get_profiles_cache_path(profile_name: str) -> Path:
    """Return the local ARN cache path for the given ccwb profile."""
    return Path.home() / ".claude-code-session" / f"{profile_name}-inference-profiles.json"


def _load_profiles_cache(profile_name: str) -> dict[str, str]:
    """Load {model_key: arn} from the local cache file, or return {}."""
    cache_path = _get_profiles_cache_path(profile_name)
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_profiles_cache(profile_name: str, arns: dict[str, str]) -> None:
    """Persist {model_key: arn} to the local cache file."""
    cache_path = _get_profiles_cache_path(profile_name)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(arns, f, indent=2)


def _get_current_claude_json_model() -> str | None:
    """Read the model field from ~/.claude.json, or return None."""
    claude_json = Path.home() / ".claude.json"
    if claude_json.exists():
        try:
            with open(claude_json) as f:
                return json.load(f).get("model")
        except Exception:
            pass
    return None


def _write_claude_json_model(arn: str) -> None:
    """Set the model field in ~/.claude.json, preserving all other fields."""
    claude_json = Path.home() / ".claude.json"
    data: dict = {}
    if claude_json.exists():
        try:
            with open(claude_json) as f:
                data = json.load(f)
        except Exception:
            pass
    data["model"] = arn
    with open(claude_json, "w") as f:
        json.dump(data, f, indent=2)


class ProfilesListCommand(Command):
    name = "profiles list"
    description = "List your Bedrock Application Inference Profile ARNs"

    options = [
        option("profile", description="ccwb configuration profile to use", flag=False),
        option("refresh", description="Re-fetch ARNs from AWS instead of using local cache", flag=True),
        option("json", description="Output in JSON format", flag=True),
    ]

    def handle(self) -> int:
        """List the user's inference profile ARNs from cache or AWS."""
        console = Console()
        config = Config.load()

        profile_name = self.option("profile") or config.active_profile
        profile = config.get_profile(profile_name)
        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found. Run 'ccwb init' first.[/red]")
            return 1

        if not profile.inference_profiles_enabled:
            console.print(
                "[yellow]Application Inference Profiles are not enabled for this deployment.\n"
                "Set inference_profiles_enabled = true in your ccwb profile configuration.[/yellow]"
            )
            return 1

        refresh = self.option("refresh")
        arns = {} if refresh else _load_profiles_cache(profile_name)

        if refresh or not arns:
            arns = self._fetch_arns_from_aws(profile, console)
            if arns:
                _save_profiles_cache(profile_name, arns)

        if not arns:
            console.print(
                "[yellow]No inference profiles found. " "They are created automatically on your next login.[/yellow]"
            )
            return 0

        current_model_arn = _get_current_claude_json_model()
        enabled_models = get_enabled_inference_profile_models()

        if self.option("json"):
            output = {
                "profiles": {
                    key: {
                        "arn": arn,
                        "display_name": enabled_models.get(key, {}).get("display_name", key),
                        "is_default": arn == current_model_arn,
                    }
                    for key, arn in arns.items()
                },
                "current_claude_json_model": current_model_arn,
            }
            console.print(json.dumps(output, indent=2))
            return 0

        # Rich table output
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan")
        table.add_column("Model Key", style="cyan", no_wrap=True)
        table.add_column("Display Name")
        table.add_column("ARN")
        table.add_column("Default", justify="center")

        for model_key, arn in sorted(arns.items()):
            display_name = enabled_models.get(model_key, {}).get("display_name", model_key)
            is_default = "●" if arn == current_model_arn else ""
            table.add_row(model_key, display_name, arn, f"[green]{is_default}[/green]")

        console.print("\n[bold]Your Bedrock Application Inference Profiles[/bold]")
        console.print(table)

        if current_model_arn:
            console.print(f"\n[dim]Default model in ~/.claude.json:[/dim] {current_model_arn}")
        else:
            console.print(
                "\n[yellow]~/.claude.json has no model set. "
                "Run 'ccwb profiles set-default <model_key>' to configure it.[/yellow]"
            )

        console.print(
            "\n[dim]Tip: use these ARNs with any Bedrock-compatible tool "
            "(AWS CLI, boto3, Bedrock Playground, VS Code settings).[/dim]"
        )
        return 0

    def _fetch_arns_from_aws(self, profile, console: Console) -> dict[str, str]:
        """Query AWS Bedrock to find this user's application inference profiles."""
        import keyring

        # Retrieve the cached id_token to determine the user's email
        id_token_raw = keyring.get_password(f"claude-code-{profile.name}", "id_token")
        if not id_token_raw:
            console.print(
                "[yellow]No cached session found. Please log in first "
                "(run any Claude Code command to trigger authentication).[/yellow]"
            )
            return {}

        import jwt as pyjwt

        try:
            claims = pyjwt.decode(id_token_raw, options={"verify_signature": False})
            email = claims.get("email", "")
        except Exception:
            email = ""

        if not email:
            console.print("[red]Could not determine your email from the cached session.[/red]")
            return {}

        enabled_models = get_enabled_inference_profile_models()
        expected_names = {get_application_profile_name(email, model_key): model_key for model_key in enabled_models}

        try:
            bedrock = boto3.client("bedrock", region_name=profile.aws_region)
            paginator = bedrock.get_paginator("list_inference_profiles")
            arns: dict[str, str] = {}
            for page in paginator.paginate(typeEquals="APPLICATION"):
                for p in page.get("inferenceProfileSummaries", []):
                    name = p.get("inferenceProfileName", "")
                    if name in expected_names:
                        model_key = expected_names[name]
                        arns[model_key] = p["inferenceProfileArn"]
            return arns
        except Exception as e:
            console.print(f"[red]Could not query AWS Bedrock: {e}[/red]")
            return {}


class ProfilesSetDefaultCommand(Command):
    name = "profiles set-default"
    description = "Set the default inference profile model written to ~/.claude.json"

    arguments_definition = [
        # Cleo positional argument defined inline via the arguments property
    ]

    options = [
        option("profile", description="ccwb configuration profile to use", flag=False),
    ]

    def handle(self) -> int:
        """Update ~/.claude.json with the ARN for the chosen model key."""
        console = Console()
        config = Config.load()

        profile_name = self.option("profile") or config.active_profile
        profile = config.get_profile(profile_name)
        if not profile:
            console.print(f"[red]Profile '{profile_name}' not found. Run 'ccwb init' first.[/red]")
            return 1

        if not profile.inference_profiles_enabled:
            console.print("[yellow]Application Inference Profiles are not enabled for this deployment.[/yellow]")
            return 1

        # Read model_key from the first positional argument
        model_key = self.argument("model_key") if self.has_argument("model_key") else None
        if not model_key:
            console.print("[red]Usage: ccwb profiles set-default <model_key>[/red]")
            console.print("\nAvailable model keys:")
            for k, v in get_enabled_inference_profile_models().items():
                console.print(f"  [cyan]{k}[/cyan]  {v['display_name']}")
            return 1

        arns = _load_profiles_cache(profile_name)
        if not arns:
            console.print(
                "[yellow]No cached profiles found. "
                "Run 'ccwb profiles list --refresh' to fetch them from AWS.[/yellow]"
            )
            return 1

        arn = arns.get(model_key)
        if not arn:
            console.print(f"[red]No inference profile found for model key '{model_key}'.[/red]")
            console.print(f"Available keys: {', '.join(arns.keys())}")
            return 1

        _write_claude_json_model(arn)
        enabled_models = get_enabled_inference_profile_models()
        display_name = enabled_models.get(model_key, {}).get("display_name", model_key)
        console.print(f"[green]Default model set to [bold]{display_name}[/bold] ({model_key})[/green]")
        console.print(f"[dim]ARN: {arn}[/dim]")
        console.print("[dim]~/.claude.json updated.[/dim]")
        return 0

    @property
    def arguments(self):
        from cleo.helpers import argument

        return [argument("model_key", description="Model key to set as default (e.g. sonnet-4-6)")]
