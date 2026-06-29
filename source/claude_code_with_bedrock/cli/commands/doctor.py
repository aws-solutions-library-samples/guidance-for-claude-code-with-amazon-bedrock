# ABOUTME: Doctor command to validate installation health and catch common misconfigurations.
# ABOUTME: Integrates credential-process --explain and otel-helper --status for deep diagnostics.

"""Doctor command — validate installation health and export diagnostics.

Two modes:
  1. ccwb doctor         → pretty self-troubleshooting (static checks, no network)
  2. ccwb doctor --json  → full diagnostic export (static + live checks + raw config)
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


def run_doctor(home: Path = None, profile: str = None, include_live: bool = False) -> list:
    """Run health checks and return list of HealthCheck results.

    Args:
        home: Override home directory (for testing).
        profile: If set, check only this profile (passed to --explain/--status).
        include_live: If True, also run network-dependent checks (auth, proxy).
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
        explain_args = ["--explain"]
        if profile:
            explain_args.extend(["--profile", profile])
        explain_data = _run_binary_json(binary_path, explain_args)
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
                monitoring_str = f", monitoring={mon_mode}"
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

    # ─── Check 6: otel-helper binary ──────────────────────────────────────────
    check = HealthCheck("otel-helper", "Telemetry helper binary exists")
    otel_path = _find_binary(install_dir, "otel-helper")
    if otel_path:
        check.pass_(str(otel_path))
    elif config_data:
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

    # ─── Check 7: otel-helper --status ────────────────────────────────────────
    check = HealthCheck("otel-status", "Telemetry proxy status")
    if otel_path:
        status_args = ["--status"]
        if profile:
            status_args.extend(["--profile", profile])
        status_data = _run_binary_json(otel_path, status_args)
        if status_data:
            proxy = status_data.get("proxy", {})
            cache = status_data.get("cache", {})
            if proxy.get("listening"):
                check.pass_(
                    f"Proxy listening on port {proxy.get('port')}, cache={'✓' if cache.get('has_headers') else '✗'}",
                    detail=status_data,
                )
            else:
                if config_data:
                    profiles_data = config_data.get("profiles", config_data)
                    any_monitoring = any(
                        isinstance(profiles_data.get(p), dict)
                        and profiles_data[p].get("otel_collector_endpoint")
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

    # ─── Live checks (only in --json export mode) ─────────────────────────────
    if include_live:
        # Auth test
        check = HealthCheck("auth-test", "Credential helper can authenticate")
        if binary_path and config_data:
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

        # Proxy port health
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
                    isinstance(profiles_data.get(p), dict)
                    and profiles_data[p].get("otel_collector_endpoint")
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

    console.print("\n[bold]ccwb doctor[/bold]\n")

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

    fails = sum(1 for c in checks if c.status == "fail")
    warns = sum(1 for c in checks if c.status == "warn")
    passes = sum(1 for c in checks if c.status == "pass")

    console.print()
    if fails == 0:
        console.print(f"[green]✓ All checks passed[/green] ({passes} pass, {warns} warnings)")
    else:
        console.print(f"[red]✗ {fails} check(s) failed[/red] ({passes} pass, {warns} warnings)")
        console.print("\n[dim]Export diagnostics for troubleshooting:[/dim]")
        console.print("  [cyan]ccwb doctor --json > diagnostics.json[/cyan]")

    return 0 if fails == 0 else 1


class DoctorCommand(Command):
    name = "doctor"
    description = "Validate installation health and export diagnostics"
    help = """Run post-installation health checks on the local machine.

Checks credential-process binary, config.json, AWS profile, Claude Code
settings, resolved auth mode (via --explain), and telemetry proxy status.

Quick self-check (instant, no network):
  <info>poetry run ccwb doctor</info>

Full diagnostic export (includes live probes):
  <info>poetry run ccwb doctor --json > diagnostics.json</info>
"""

    options = [
        option("profile", description="Configuration profile to check", flag=False),
        option("json", description="Full diagnostic export as JSON (includes live checks)"),
    ]

    def handle(self) -> int:
        """Execute the doctor command."""
        console = Console()
        profile = self.option("profile")
        is_json = self.option("json")

        # JSON mode includes live checks for complete diagnostics
        checks = run_doctor(profile=profile, include_live=is_json)

        if is_json:
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

        return print_results(checks, console)
