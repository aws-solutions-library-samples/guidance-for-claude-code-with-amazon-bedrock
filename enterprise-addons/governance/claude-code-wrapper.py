#!/usr/bin/env python3
"""
Enterprise wrapper for Claude Code that enforces governance policies.
This script wraps the standard Claude Code execution with enterprise controls.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import argparse

# Enterprise policy configuration
ENTERPRISE_POLICY_PROFILES = {
    "plan-only": {
        "CLAUDE_DEFAULT_MODE": "plan",
        "CLAUDE_ALLOW_FILE_WRITE": "false", 
        "CLAUDE_ALLOW_SHELL_EXEC": "false",
        "CLAUDE_NETWORK_ACCESS": "deny",
        "CLAUDE_MAX_TOKENS": "4000",
        "CLAUDE_INTERACTIVE_MODE": "false"
    },
    "restricted": {
        "CLAUDE_DEFAULT_MODE": "interactive",
        "CLAUDE_ALLOW_FILE_WRITE": "true",
        "CLAUDE_ALLOW_SHELL_EXEC": "restricted", 
        "CLAUDE_NETWORK_ACCESS": "restricted",
        "CLAUDE_MAX_TOKENS": "8000",
        "CLAUDE_ALLOWED_COMMANDS": "pytest,jest,npm,pip,ruff,eslint,tsc,mypy,black,git",
        "CLAUDE_DENIED_COMMANDS": "curl,wget,ssh,scp,docker,kubectl,rm,sudo"
    },
    "standard": {
        "CLAUDE_DEFAULT_MODE": "interactive",
        "CLAUDE_ALLOW_FILE_WRITE": "true",
        "CLAUDE_ALLOW_SHELL_EXEC": "true",
        "CLAUDE_NETWORK_ACCESS": "allow",
        "CLAUDE_MAX_TOKENS": "200000",
        "CLAUDE_CACHE_ENABLED": "true"
    },
    "elevated": {
        "CLAUDE_DEFAULT_MODE": "interactive",
        "CLAUDE_ALLOW_FILE_WRITE": "true", 
        "CLAUDE_ALLOW_SHELL_EXEC": "true",
        "CLAUDE_NETWORK_ACCESS": "allow",
        "CLAUDE_MAX_TOKENS": "200000",
        "CLAUDE_CACHE_ENABLED": "true",
        "CLAUDE_ADVANCED_FEATURES": "true",
        "CLAUDE_INFRASTRUCTURE_ACCESS": "read-only"
    }
}

def load_enterprise_config() -> Optional[Dict[str, Any]]:
    """Load enterprise configuration from various possible locations."""
    config_paths = [
        Path.cwd() / "enterprise-config.json",
        Path.home() / ".claude-code" / "enterprise-config.json",
        Path("/etc/claude-code/enterprise-config.json")
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load config from {config_path}: {e}", file=sys.stderr)
                continue
    
    return None

def get_security_profile() -> str:
    """Determine the security profile to use."""
    # Check command line argument
    if len(sys.argv) > 1 and sys.argv[1].startswith("--security-profile="):
        return sys.argv[1].split("=")[1]
    
    # Check environment variable
    profile = os.environ.get("CLAUDE_ENTERPRISE_PROFILE")
    if profile:
        return profile
        
    # Check enterprise config
    config = load_enterprise_config()
    if config and "security_profile" in config:
        return config["security_profile"]
    
    # Default fallback
    return "standard"

def apply_security_profile(profile_name: str) -> None:
    """Apply security profile environment variables."""
    if profile_name not in ENTERPRISE_POLICY_PROFILES:
        print(f"Warning: Unknown security profile '{profile_name}', using 'standard'", file=sys.stderr)
        profile_name = "standard"
    
    profile_env = ENTERPRISE_POLICY_PROFILES[profile_name]
    
    # Apply profile environment variables
    for key, value in profile_env.items():
        # Only set if not already set (allows for overrides)
        if key not in os.environ:
            os.environ[key] = value
    
    # Set profile indicator for monitoring
    os.environ["CLAUDE_ENTERPRISE_PROFILE_ACTIVE"] = profile_name
    
    print(f"🏢 Enterprise security profile: {profile_name}", file=sys.stderr)

def check_policy_compliance() -> bool:
    """Check if current environment complies with enterprise policies."""
    profile_name = get_security_profile()
    
    # Check for policy violations
    violations = []
    
    if profile_name == "plan-only":
        if os.environ.get("CLAUDE_ALLOW_FILE_WRITE", "false").lower() == "true":
            violations.append("File write operations are not allowed in plan-only mode")
        if os.environ.get("CLAUDE_ALLOW_SHELL_EXEC", "false").lower() == "true":
            violations.append("Shell execution is not allowed in plan-only mode")
    
    elif profile_name == "restricted":
        denied_commands = os.environ.get("CLAUDE_DENIED_COMMANDS", "").split(",")
        # This would need integration with Claude Code's command filtering
        pass
    
    if violations:
        print("🚨 Policy violations detected:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return False
    
    return True

def setup_monitoring() -> None:
    """Set up monitoring and audit logging."""
    config = load_enterprise_config()
    if not config:
        return
    
    # Set up OpenTelemetry environment if monitoring enabled
    if config.get("monitoring_enabled", False):
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = config.get(
            "otel_endpoint", 
            "http://localhost:4317"
        )
        os.environ["OTEL_SERVICE_NAME"] = "claude-code-enterprise"
        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = f"service.name=claude-code,security.profile={get_security_profile()}"
    
    # Set up audit logging
    audit_log_path = config.get("audit_log_path")
    if audit_log_path:
        os.environ["CLAUDE_AUDIT_LOG_PATH"] = audit_log_path

def find_claude_code_executable() -> Optional[str]:
    """Find the Claude Code executable."""
    # Check common locations
    possible_paths = [
        "claude",  # In PATH
        "/usr/local/bin/claude",
        "/opt/homebrew/bin/claude",
        str(Path.home() / ".local" / "bin" / "claude"),
        str(Path.home() / "node_modules" / ".bin" / "claude")
    ]
    
    for path in possible_paths:
        try:
            result = subprocess.run([path, "--version"], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=5)
            if result.returncode == 0:
                return path
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            continue
    
    return None

def main():
    """Main entry point for enterprise wrapper."""
    parser = argparse.ArgumentParser(
        description="Enterprise wrapper for Claude Code",
        add_help=False  # Pass through to underlying claude command
    )
    parser.add_argument("--security-profile", 
                       choices=list(ENTERPRISE_POLICY_PROFILES.keys()),
                       help="Override security profile")
    parser.add_argument("--check-policy", 
                       action="store_true",
                       help="Check policy compliance and exit")
    
    # Parse known args, pass the rest through
    known_args, remaining_args = parser.parse_known_args()
    
    # Handle check-policy option
    if known_args.check_policy:
        profile_name = get_security_profile()
        print(f"Active security profile: {profile_name}")
        if check_policy_compliance():
            print("✅ Policy compliance check passed")
            return 0
        else:
            print("❌ Policy compliance check failed")
            return 1
    
    # Apply security profile
    profile_name = known_args.security_profile or get_security_profile()
    apply_security_profile(profile_name)
    
    # Set up monitoring
    setup_monitoring()
    
    # Check compliance before execution
    if not check_policy_compliance():
        print("Execution blocked due to policy violations", file=sys.stderr)
        return 1
    
    # Find Claude Code executable
    claude_executable = find_claude_code_executable()
    if not claude_executable:
        print("Error: Claude Code executable not found", file=sys.stderr)
        print("Please install Claude Code first", file=sys.stderr)
        return 1
    
    # Execute Claude Code with remaining arguments
    try:
        # Remove our custom args from the command line
        filtered_args = [arg for arg in sys.argv[1:] if not arg.startswith("--security-profile") and arg != "--check-policy"]
        
        result = subprocess.run([claude_executable] + filtered_args, 
                              env=os.environ.copy())
        return result.returncode
    except KeyboardInterrupt:
        print("\n\nClaude Code execution interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error executing Claude Code: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())