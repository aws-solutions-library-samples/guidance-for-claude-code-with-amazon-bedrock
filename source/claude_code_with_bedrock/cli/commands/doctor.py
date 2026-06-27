# ABOUTME: Doctor command to validate installation health and catch common misconfigurations
# ABOUTME: Checks credential-process binary, config, AWS profile, settings, and telemetry helper

"""Doctor command — validate installation health and catch common misconfigurations."""

import json
import subprocess
import sys
from pathlib import Path

from cleo.commands.command import Command
from cleo.helpers import option
from rich.console import Console
from rich.table import Table


class HealthCheck:
    """A single health check with name, runner, and result."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.status = "skipped"  # pass, fail, warn, skipped
        self.message = ""
        self.fix = ""

    def pass_(self, msg=""):
        self.status = "pass"
        self.message = msg

    def fail(self, msg, fix=""):
        self.status = "fail"
        self.message = msg
        self.fix = fix

    def warn(self, msg, fix=""):
        self.status = "warn"
        self.message = msg
        self.fix = fix


def run_doctor(home: Path = None):
    """Run all health checks and return list of HealthCheck results."""
    checks = []

    if home is None:
        home = Path.home()
    install_dir = home / "claude-code-with-bedrock"

    # 1. Binary presence
    check = HealthCheck("credential-process", "Credential helper binary exists")
    binary_name = "credential-process.exe" if sys.platform == "win32" else "credential-process"
    binary_path = install_dir / binary_name
    if binary_path.exists():
        check.pass_(str(binary_path))
    else:
        check.fail(f"Not found at {binary_path}", "Run 'ccwb package' and execute the installer")
    checks.append(check)

    # 2. Config.json
    check = HealthCheck("config.json", "Configuration file present and valid")
    config_path = install_dir / "config.json"
    config_data = None
    if config_path.exists():
        try:
            with open(config_path) as f:
                config_data = json.load(f)
            profiles = list(config_data.get("profiles", config_data).keys())
            profiles = [p for p in profiles if p != "profiles"]
            check.pass_(f"Profiles: {', '.join(profiles[:5])}")
        except json.JSONDecodeError as e:
            check.fail(f"Invalid JSON: {e}", "Re-run the installer or re-package")
    else:
        check.fail(f"Not found at {config_path}", "Run the installer from 'ccwb package' output")
    checks.append(check)

    # 3. AWS config profile
    check = HealthCheck("aws-profile", "AWS config references credential-process")
    aws_config = home / ".aws" / "config"
    if aws_config.exists():
        content = aws_config.read_text()
        if "credential_process" in content and "claude-code-with-bedrock" in content:
            check.pass_("credential_process configured in ~/.aws/config")
        else:
            check.warn(
                "~/.aws/config exists but no credential_process entry found",
                "Re-run the installer or manually add credential_process to your AWS profile",
            )
    else:
        check.fail("~/.aws/config not found", "Run the installer")
    checks.append(check)

    # 4. Settings.json
    check = HealthCheck("settings.json", "Claude Code settings configured")
    settings_paths = [
        home / ".claude" / "settings.json",
        home / ".claude" / "managed-settings.json",
    ]
    found_settings = None
    for sp in settings_paths:
        if sp.exists():
            found_settings = sp
            break
    if found_settings:
        try:
            settings = json.loads(found_settings.read_text())
            has_env = "env" in settings
            has_hooks = "hooks" in settings
            check.pass_(f"{found_settings.name} (env={'✓' if has_env else '✗'}, hooks={'✓' if has_hooks else '✗'})")
        except Exception as e:
            check.fail(f"Cannot parse {found_settings}: {e}")
    else:
        check.fail("No settings.json or managed-settings.json in ~/.claude/", "Run the installer")
    checks.append(check)

    # 5. Credential test (non-blocking — just tries to invoke credential-process)
    check = HealthCheck("credential-test", "Credential helper responds")
    if binary_path.exists() and config_data:
        # Find first profile name
        if "profiles" in config_data:
            first_profile = next(iter(config_data["profiles"]), None)
        else:
            first_profile = next((k for k in config_data if k != "profiles"), None)

        if first_profile:
            try:
                result = subprocess.run(
                    [str(binary_path), "--profile", first_profile, "--health-check"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    check.pass_(f"Profile '{first_profile}' responds")
                else:
                    check.warn(
                        f"credential-process exited {result.returncode} (may need auth)",
                        "Run credential-process manually to authenticate",
                    )
            except subprocess.TimeoutExpired:
                check.warn("credential-process timed out (may need interactive auth)")
            except Exception as e:
                check.fail(f"Cannot execute: {e}")
        else:
            check.warn("No profiles found in config.json")
    else:
        check.status = "skipped"
        check.message = "Binary or config not available"
    checks.append(check)

    # 6. OTEL helper
    check = HealthCheck("otel-helper", "Telemetry helper binary exists")
    otel_name = "otel-helper.exe" if sys.platform == "win32" else "otel-helper"
    otel_path = install_dir / otel_name
    if otel_path.exists():
        check.pass_(str(otel_path))
    elif config_data:
        # Check if monitoring is even configured
        profiles_data = config_data.get("profiles", config_data)
        any_monitoring = any(
            "otel_collector_endpoint" in (profiles_data.get(p, {}) if isinstance(profiles_data.get(p), dict) else {})
            for p in profiles_data
            if p != "profiles"
        )
        if any_monitoring:
            check.fail(
                f"Monitoring configured but {otel_name} not found",
                "Re-run 'ccwb package' with Go installed, then re-install",
            )
        else:
            check.status = "skipped"
            check.message = "Monitoring not configured"
    else:
        check.status = "skipped"
        check.message = "Config not available"
    checks.append(check)

    return checks


def print_results(checks: list, console: Console = None):
    """Print health check results as a rich table. Returns exit code (0=ok, 1=failures)."""
    if console is None:
        console = Console()

    console.print("\n[bold]ccwb doctor[/bold] — Installation Health Check\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("Status", width=6)
    table.add_column("Details")

    for c in checks:
        if c.status == "pass":
            status = "[green]PASS[/green]"
        elif c.status == "fail":
            status = "[red]FAIL[/red]"
        elif c.status == "warn":
            status = "[yellow]WARN[/yellow]"
        else:
            status = "[dim]SKIP[/dim]"

        details = c.message
        if c.fix:
            details += f"\n[dim]  Fix: {c.fix}[/dim]"

        table.add_row(c.name, status, details)

    console.print(table)

    # Summary
    fails = sum(1 for c in checks if c.status == "fail")
    warns = sum(1 for c in checks if c.status == "warn")
    passes = sum(1 for c in checks if c.status == "pass")

    console.print()
    if fails == 0:
        console.print(f"[green]✓ All checks passed[/green] ({passes} pass, {warns} warnings)")
        return 0
    else:
        console.print(f"[red]✗ {fails} check(s) failed[/red] ({passes} pass, {warns} warnings)")
        # Generate pre-filled GitHub issue URL to reduce filing burden
        failed_checks = [c for c in checks if c.status == "fail"]
        issue_body = "## ccwb doctor output\n\n"
        issue_body += "| Check | Status | Details |\n|-------|--------|---------|\n"
        for c in checks:
            issue_body += f"| {c.name} | {c.status.upper()} | {c.message} |\n"
        issue_body += "\n## Environment\n- OS: \n- Python: \n- ccwb version: \n"
        import urllib.parse
        params = urllib.parse.urlencode({
            "title": f"ccwb doctor: {', '.join(c.name for c in failed_checks)} failed",
            "body": issue_body,
            "labels": "bug",
        })
        issue_url = f"https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues/new?{params}"
        console.print(f"\n[dim]Report this issue (pre-filled):[/dim]")
        console.print(f"  {issue_url}")
        return 1


class DoctorCommand(Command):
    name = "doctor"
    description = "Validate installation health and catch common misconfigurations"
    help = """Run post-installation health checks on the local machine.

Checks credential-process binary, config.json, AWS profile, Claude Code
settings, credential helper responsiveness, and otel-helper presence.

Use after running the installer to verify everything is working:
  <info>poetry run ccwb doctor</info>

To check a specific profile:
  <info>poetry run ccwb doctor --profile MyProfile</info>
"""

    options = [
        option("profile", description="Configuration profile to check", flag=False),
    ]

    def handle(self) -> int:
        """Execute the doctor command."""
        console = Console()
        checks = run_doctor()
        return print_results(checks, console)
