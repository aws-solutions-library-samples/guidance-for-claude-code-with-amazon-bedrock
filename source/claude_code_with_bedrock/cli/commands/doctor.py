# ABOUTME: Doctor command to validate installation health and catch common misconfigurations.
# ABOUTME: Integrates credential-process --explain and otel-helper --status for deep diagnostics.

"""Doctor command — validate installation health and catch common misconfigurations.

Two diagnostic layers:
  1. ccwb doctor         → static checks + --explain/--status integration (no auth)
  2. ccwb doctor --live  → actually attempts authentication and telemetry

This consolidates what would otherwise be 3 separate tools into one command
that progressively reveals more detail (plain → --verbose → --live → --json).
"""

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
        self.detail = None  # optional structured data (e.g. --explain output)

    def pass_(self, msg="", detail=None):
        self.status = "pass"
        self.message = msg
        self.detail = detail

    def fail(self, msg, fix="", detail=None):
        self.status = "fail"
        self.message = msg
        self.fix = fix
        self.detail = detail

    def warn(self, msg, fix="", detail=None):
        self.status = "warn"
        self.message = msg
        self.fix = fix
        self.detail = detail


def _find_binary(install_dir: Path, name: str) -> Path | None:
    """Find a binary, checking platform-appropriate extensions."""
    if sys.platform == "win32":
        # Check .exe, .cmd, .ps1 in order
        for ext in [".exe", ".cmd", ".ps1"]:
            p = install_dir / f"{name}{ext}"
            if p.exists():
                return p
    else:
        p = install_dir / name
        if p.exists():
            return p
    return None


def _run_binary_json(binary_path: Path, args: list, timeout: int = 10) -> dict | None:
    """Run a binary with args, parse JSON stdout. Returns None on failure."""
    try:
        cmd = [str(binary_path)] + args
        # On Windows, .cmd/.ps1 need shell or explicit interpreter
        if binary_path.suffix == ".ps1":
            cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File"] + cmd
        elif binary_path.suffix == ".cmd":
            cmd = ["cmd", "/c"] + cmd

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError, OSError):
        pass
    return None


def run_doctor(home: Path = None, live: bool = False) -> list:
    """Run all health checks and return list of HealthCheck results.

    Args:
        home: Override home directory (for testing).
        live: If True, also perform network-dependent checks (auth, proxy health).
    """
    checks = []

    if home is None:
        home = Path.home()
    install_dir = home / "claude-code-with-bedrock"

    # ─── Check 1: credential-process binary ───────────────────────────────────
    check = HealthCheck("credential-process", "Credential helper binary exists")
    binary_path = _find_binary(install_dir, "credential-process")
    if binary_path:
        check.pass_(str(binary_path))
    else:
        check.fail(
            f"Not found in {install_dir}",
            "Run 'ccwb package' and execute the installer",
        )
    checks.append(check)

    # ─── Check 2: config.json ─────────────────────────────────────────────────
    check = HealthCheck("config.json", "Configuration file present and valid")
    config_path = install_dir / "config.json"
    config_data = None
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                config_data = json.load(f)
            profiles = config_data.get("profiles", config_data)
            profile_names = [p for p in profiles if isinstance(profiles.get(p), dict)]
            check.pass_(f"Profiles: {', '.join(profile_names[:5])}")
        except json.JSONDecodeError as e:
            check.fail(f"Invalid JSON: {e}", "Re-run the installer or re-package")
    else:
        check.fail(f"Not found at {config_path}", "Run the installer from 'ccwb package' output")
    checks.append(check)

    # ─── Check 3: AWS config profile ──────────────────────────────────────────
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

    # ─── Check 4: Claude Code settings.json ────────────────────────────────────
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
            msg = f"{found_settings.name} (env={'✓' if has_env else '✗'}, hooks={'✓' if has_hooks else '✗'})"
            check.pass_(msg)
        except Exception as e:
            check.fail(f"Cannot parse {found_settings}: {e}")
    else:
        check.fail("No settings.json or managed-settings.json in ~/.claude/", "Run the installer")
    checks.append(check)

    # ─── Check 5: credential-process --explain (resolved config) ──────────────
    check = HealthCheck("explain", "Resolved auth mode and configuration")
    if binary_path:
        explain_data = _run_binary_json(binary_path, ["--explain"])
        if explain_data:
            mode = explain_data.get("auth", {}).get("mode", "unknown")
            ver = explain_data.get("version", "unknown")
            commit = explain_data.get("commit", "unknown")
            provider_type = ""
            if explain_data.get("provider"):
                provider_type = f", provider={explain_data['provider'].get('type', '?')}"
            monitoring = explain_data.get("monitoring", {})
            monitoring_str = ""
            if monitoring.get("enabled"):
                mon_mode = monitoring.get("mode", "?")
                delivery = monitoring.get("config_delivery", "static")
                monitoring_str = f", monitoring={mon_mode}"
                if delivery == "bootstrap":
                    monitoring_str += " (bootstrap)"
            quota_str = ""
            if explain_data.get("quota", {}).get("enabled"):
                quota_str = ", quota=enabled"
            check.pass_(
                f"mode={mode}{provider_type}{monitoring_str}{quota_str} (v{ver} @{commit})",
                detail=explain_data,
            )
        else:
            check.warn(
                "credential-process --explain failed or not supported",
                "Update to latest version (v2.5.0+) for --explain support",
            )
    else:
        check.status = "skipped"
        check.message = "Binary not available"
    checks.append(check)

    # ─── Check 6: otel-helper ──────────────────────────────────────────────────
    check = HealthCheck("otel-helper", "Telemetry helper binary exists")
    otel_path = _find_binary(install_dir, "otel-helper")
    if otel_path:
        check.pass_(str(otel_path))
    elif config_data:
        # Only fail if monitoring is actually configured
        profiles_data = config_data.get("profiles", config_data)
        any_monitoring = any(
            isinstance(profiles_data.get(p), dict) and profiles_data[p].get("otel_collector_endpoint")
            for p in profiles_data
        )
        if any_monitoring:
            check.fail(
                "Monitoring configured but otel-helper not found",
                "Re-run 'ccwb package' with Go installed, then re-install",
            )
        else:
            check.status = "skipped"
            check.message = "Monitoring not configured"
    else:
        check.status = "skipped"
        check.message = "Config not available"
    checks.append(check)

    # ─── Check 7: otel-helper --status (proxy health) ─────────────────────────
    check = HealthCheck("otel-status", "Telemetry proxy status")
    if otel_path:
        status_data = _run_binary_json(otel_path, ["--status"])
        if status_data:
            proxy = status_data.get("proxy", {})
            cache = status_data.get("cache", {})
            if proxy.get("listening"):
                check.pass_(
                    f"Proxy listening on port {proxy.get('port')}, cache={'✓' if cache.get('has_headers') else '✗'}",
                    detail=status_data,
                )
            else:
                # Proxy not running is only a problem if monitoring is configured
                if config_data:
                    profiles_data = config_data.get("profiles", config_data)
                    any_monitoring = any(
                        isinstance(profiles_data.get(p), dict) and profiles_data[p].get("otel_collector_endpoint")
                        for p in profiles_data
                    )
                    if any_monitoring:
                        check.warn(
                            f"Proxy not running (port {proxy.get('port')})",
                            "Proxy starts automatically when credential-process runs",
                        )
                    else:
                        check.status = "skipped"
                        check.message = "Monitoring not configured"
                else:
                    check.pass_("Proxy not running (no monitoring configured)", detail=status_data)
        else:
            check.warn(
                "otel-helper --status failed or not supported",
                "Update to latest version (v2.5.0+) for --status support",
            )
    else:
        check.status = "skipped"
        check.message = "otel-helper not available"
    checks.append(check)

    # ─── Check 8 (live only): credential-process auth test ─────────────────────
    if live:
        check = HealthCheck("auth-test", "Credential helper can authenticate")
        if binary_path and config_data:
            # Try credential-process with a short timeout
            try:
                result = subprocess.run(
                    [str(binary_path), "--check-expiration"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    check.pass_("Credentials valid (not expired)")
                elif result.returncode == 1:
                    check.warn(
                        "Credentials expired (needs browser auth or refresh)",
                        "Run 'credential-process' manually to re-authenticate",
                    )
                else:
                    check.fail(f"Exit code {result.returncode}: {result.stderr.strip()[:100]}")
            except subprocess.TimeoutExpired:
                check.warn("Timed out — may need interactive authentication")
            except Exception as e:
                check.fail(f"Cannot execute: {e}")
        else:
            check.status = "skipped"
            check.message = "Binary or config not available"
        checks.append(check)

        # ─── Check 9 (live only): proxy port health ───────────────────────────
        check = HealthCheck("proxy-health", "OTEL proxy accepting connections")
        import socket
        for port in [4318, 4319]:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    check.pass_(f"Port {port} accepting connections")
                    break
            except (TimeoutError, OSError):
                continue
        else:
            if config_data:
                profiles_data = config_data.get("profiles", config_data)
                any_monitoring = any(
                    isinstance(profiles_data.get(p), dict) and profiles_data[p].get("otel_collector_endpoint")
                    for p in profiles_data
                )
                if any_monitoring:
                    check.warn(
                        "No OTEL proxy listening on 4318 or 4319",
                        "Run credential-process to spawn the proxy, or start otel-helper manually",
                    )
                else:
                    check.status = "skipped"
                    check.message = "Monitoring not configured"
            else:
                check.status = "skipped"
                check.message = "Config not available"
        checks.append(check)

    return checks


def print_results(checks: list, console: Console = None) -> int:
    """Print health check results as a rich table. Returns exit code (0=ok, 1=failures)."""
    if console is None:
        console = Console()

    console.print("\n[bold]ccwb doctor[/bold] — Installation Health Check\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", style="cyan", min_width=18)
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
        _print_issue_link(checks, console)
        return 1


def _print_issue_link(checks: list, console: Console):
    """Generate a pre-filled GitHub issue URL from failed checks."""
    import platform
    import urllib.parse

    failed_checks = [c for c in checks if c.status == "fail"]

    issue_body = "## ccwb doctor output\n\n"
    issue_body += "| Check | Status | Details |\n|-------|--------|---------|\n"
    for c in checks:
        issue_body += f"| {c.name} | {c.status.upper()} | {c.message} |\n"

    issue_body += "\n## Environment\n"
    issue_body += f"- **OS:** {platform.system()} {platform.release()} ({platform.machine()})\n"
    issue_body += f"- **Python:** {platform.python_version()}\n"

    # Include --explain output if available
    explain_check = next((c for c in checks if c.name == "explain" and c.detail), None)
    if explain_check:
        issue_body += f"- **Auth mode:** {explain_check.detail.get('auth', {}).get('mode', 'unknown')}\n"
        issue_body += f"- **Version:** {explain_check.detail.get('version', 'unknown')}\n"
        issue_body += f"- **Commit:** {explain_check.detail.get('commit', 'unknown')}\n"
        if explain_check.detail.get("provider"):
            issue_body += f"- **Provider:** {explain_check.detail['provider'].get('type', 'unknown')}\n"
        monitoring = explain_check.detail.get("monitoring", {})
        if monitoring.get("enabled"):
            issue_body += f"- **Monitoring:** {monitoring.get('mode', 'unknown')} ({monitoring.get('config_delivery', 'static')})\n"
            if monitoring.get("endpoint"):
                issue_body += f"- **OTEL endpoint:** {monitoring['endpoint']}\n"
            if monitoring.get("bootstrap_endpoint"):
                issue_body += f"- **Bootstrap endpoint:** {monitoring['bootstrap_endpoint']}\n"

    params = urllib.parse.urlencode({
        "title": f"ccwb doctor: {', '.join(c.name for c in failed_checks)} failed",
        "body": issue_body,
        "labels": "bug",
    })
    issue_url = f"https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues/new?{params}"
    console.print("\n[dim]Report this issue (pre-filled):[/dim]")
    console.print(f"  {issue_url}")


def print_verbose(checks: list, console: Console):
    """Print detailed --explain and --status output for troubleshooting."""
    console.print("\n[bold]Detailed Diagnostics[/bold] (--verbose)\n")

    explain_check = next((c for c in checks if c.name == "explain" and c.detail), None)
    if explain_check:
        console.print("[cyan]credential-process --explain:[/cyan]")
        console.print_json(json.dumps(explain_check.detail, indent=2))
        console.print()

    status_check = next((c for c in checks if c.name == "otel-status" and c.detail), None)
    if status_check:
        console.print("[cyan]otel-helper --status:[/cyan]")
        console.print_json(json.dumps(status_check.detail, indent=2))
        console.print()


class DoctorCommand(Command):
    name = "doctor"
    description = "Validate installation health and catch common misconfigurations"
    help = """Run post-installation health checks on the local machine.

Checks credential-process binary, config.json, AWS profile, Claude Code
settings, resolved auth mode (via --explain), and telemetry proxy status.

Use after running the installer to verify everything is working:
  <info>poetry run ccwb doctor</info>

Live checks (actually attempts auth + proxy connectivity):
  <info>poetry run ccwb doctor --live</info>

Detailed config dump for troubleshooting:
  <info>poetry run ccwb doctor --verbose</info>

Machine-readable output (pipe to scripts or support):
  <info>poetry run ccwb doctor --json</info>
"""

    options = [
        option("profile", description="Configuration profile to check", flag=False),
        option("verbose", "v", description="Show detailed --explain and --status JSON output"),
        option("live", "l", description="Perform live checks (auth test, proxy connectivity)"),
        option("json", description="Output results as JSON (for automation)"),
    ]

    def handle(self) -> int:
        """Execute the doctor command."""
        console = Console()
        live = self.option("live")
        checks = run_doctor(live=live)

        if self.option("json"):
            output = {
                "checks": [
                    {
                        "name": c.name,
                        "status": c.status,
                        "message": c.message,
                        "fix": c.fix,
                        "detail": c.detail,
                    }
                    for c in checks
                ],
            }
            console.print_json(json.dumps(output))
            return 0 if not any(c.status == "fail" for c in checks) else 1

        exit_code = print_results(checks, console)

        if self.option("verbose"):
            print_verbose(checks, console)

        return exit_code
