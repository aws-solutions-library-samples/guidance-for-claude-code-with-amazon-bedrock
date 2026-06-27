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
        # Auto-detect environment for easier diagnosis
        import platform
        issue_body += "\n## Environment\n"
        issue_body += f"- **OS:** {platform.system()} {platform.release()} ({platform.machine()})\n"
        issue_body += f"- **Python:** {platform.python_version()}\n"
        # Read auth type and monitoring mode from config.json
        _home = Path.home()
        _config_path = _home / "claude-code-with-bedrock" / "config.json"
        _auth_type = "unknown"
        _monitoring_mode = "none"
        if _config_path.exists():
            try:
                with open(_config_path) as _cf:
                    _cfg = json.load(_cf)
                _profiles = _cfg.get("profiles", _cfg)
                _first = next((v for k, v in _profiles.items() if isinstance(v, dict)), {})
                _auth_type = _first.get("auth_type", "oidc")
                _monitoring_mode = _first.get("monitoring_mode", "none")
            except Exception:
                pass
        issue_body += f"- **Auth type:** {_auth_type}\n"
        issue_body += f"- **Monitoring mode:** {_monitoring_mode}\n"
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


def _collect_environment():
    """Collect environment info for diagnostics."""
    import platform
    home = Path.home()
    config_path = home / "claude-code-with-bedrock" / "config.json"
    env = {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": platform.python_version(),
        "auth_type": "unknown",
        "monitoring_mode": "none",
        "profiles": [],
        "region": "unknown",
    }
    if config_path.exists():
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            profiles = cfg.get("profiles", cfg)
            for name, data in profiles.items():
                if not isinstance(data, dict):
                    continue
                env["profiles"].append(name)
                env["auth_type"] = data.get("auth_type", "oidc")
                env["monitoring_mode"] = data.get("monitoring_mode", "none")
                env["region"] = data.get("aws_region", "unknown")
        except Exception:
            pass
    return env


def print_verbose_config(console: Console):
    """Print sanitized configuration details for troubleshooting."""
    console.print("\n[bold]Configuration Details[/bold] (--verbose)\n")
    home = Path.home()
    config_path = home / "claude-code-with-bedrock" / "config.json"

    if not config_path.exists():
        console.print("[dim]No config.json found — skipping verbose output[/dim]")
        return

    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except Exception as e:
        console.print(f"[red]Cannot read config.json: {e}[/red]")
        return

    profiles = cfg.get("profiles", cfg)
    for name, data in profiles.items():
        if not isinstance(data, dict):
            continue
        console.print(f"[cyan]Profile: {name}[/cyan]")
        console.print(f"  Auth type: {data.get('auth_type', 'oidc')}")
        console.print(f"  Region: {data.get('aws_region', 'not set')}")
        console.print(f"  Provider: {data.get('provider_type', data.get('provider_domain', 'not set'))}")
        if data.get("auth_type") == "idc":
            console.print(f"  IDC Start URL: {data.get('idc_start_url', 'not set')}")
            console.print(f"  IDC Account: {data.get('idc_account_id', 'not set')}")
            console.print(f"  IDC Permission Set: {data.get('idc_permission_set_name', 'not set')}")
        else:
            domain = data.get("provider_domain", data.get("oidc_issuer_url", "not set"))
            console.print(f"  Provider domain: {domain}")
            console.print(f"  Client ID: {data.get('client_id', 'not set')[:8]}..." if data.get('client_id') else "  Client ID: not set")
        if data.get("monitoring_mode"):
            console.print(f"  Monitoring: {data.get('monitoring_mode')}")
        if data.get("otel_collector_endpoint"):
            console.print(f"  OTEL endpoint: {data.get('otel_collector_endpoint')}")
        if data.get("quota_api_endpoint"):
            console.print(f"  Quota API: {data.get('quota_api_endpoint')}")
        console.print()

    # Check settings.json hooks
    for settings_name in ["settings.json", "managed-settings.json"]:
        settings_path = home / ".claude" / settings_name
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text())
                console.print(f"[cyan]{settings_name}[/cyan]")
                env = settings.get("env", {})
                if env.get("AWS_PROFILE"):
                    console.print(f"  AWS_PROFILE: {env['AWS_PROFILE']}")
                hooks = settings.get("hooks", {})
                for hook_name in ["awsCredentialExport", "awsAuthRefresh", "otelHeadersHelper"]:
                    val = hooks.get(hook_name)
                    if val:
                        # Show just the command basename for readability
                        cmd = val if isinstance(val, str) else str(val)
                        console.print(f"  {hook_name}: [green]✓[/green] {cmd[:60]}")
                    else:
                        console.print(f"  {hook_name}: [dim]not set[/dim]")
                console.print()
            except Exception:
                pass


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
        option("verbose", "v", description="Show detailed configuration for troubleshooting"),
        option("json", description="Output results as JSON (for automation)"),
    ]

    def handle(self) -> int:
        """Execute the doctor command."""
        console = Console()
        checks = run_doctor()
        exit_code = print_results(checks, console)

        if self.option("verbose"):
            print_verbose_config(console)

        if self.option("json"):
            import json as json_mod
            output = {
                "checks": [{"name": c.name, "status": c.status, "message": c.message, "fix": c.fix} for c in checks],
                "environment": _collect_environment(),
            }
            console.print_json(json_mod.dumps(output))

        return exit_code
