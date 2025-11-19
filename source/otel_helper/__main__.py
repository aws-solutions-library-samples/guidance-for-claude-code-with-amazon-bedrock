#!/usr/bin/env python3
# ABOUTME: OTEL helper script that extracts user attributes from JWT tokens
# ABOUTME: Outputs HTTP headers for OpenTelemetry collector to enable user attribution
"""
OTEL Headers Helper Script for Claude Code

This script retrieves authentication tokens from the storage method chosen by the customer
(system keyring or session file) and formats them as HTTP headers for use with the OTEL collector.
It extracts user information from JWT tokens and provides properly formatted headers
that the OTEL collector's attributes processor converts to resource attributes.
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import subprocess
import sys

# Configure debug mode if requested
DEBUG_MODE = os.environ.get("DEBUG_MODE", "").lower() in ("true", "1", "yes", "y")
TEST_MODE = False  # Will be set by command line argument

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("claude-otel-headers")

# Constants
# Token retrieval is now handled via credential-process to avoid keychain prompts


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(description="Generate OTEL headers from authentication token")
    parser.add_argument("--test", action="store_true", help="Run in test mode with verbose output")
    parser.add_argument("--verbose", action="store_true", help="Show verbose output")
    args = parser.parse_args()

    global TEST_MODE
    TEST_MODE = args.test

    # Set debug mode if verbose is specified
    if args.verbose or args.test:
        global DEBUG_MODE
        DEBUG_MODE = True
        logger.setLevel(logging.DEBUG)

    return args


# Note: Storage method configuration no longer needed
# OTEL helper uses credential-process which handles storage internally


# Note: Direct keychain and session file access removed
# All token retrieval now goes through credential-process
# This prevents macOS keychain permission prompts for the OTEL helper


def decode_jwt_payload(token):
    """Decode the payload portion of a JWT token"""
    try:
        # Get the payload part (second segment)
        _, payload_b64, _ = token.split(".")

        # Add padding if needed
        padding_needed = len(payload_b64) % 4
        if padding_needed:
            payload_b64 += "=" * (4 - padding_needed)

        # Replace URL-safe characters and decode
        payload_b64 = payload_b64.replace("-", "+").replace("_", "/")
        decoded = base64.b64decode(payload_b64)
        payload = json.loads(decoded)

        if DEBUG_MODE:
            # Safely log the payload with sensitive information redacted
            redacted_payload = payload.copy()
            # Redact potentially sensitive fields
            for field in ["email", "sub", "at_hash", "nonce"]:
                if field in redacted_payload:
                    redacted_payload[field] = f"<{field}-redacted>"
            logger.debug(f"JWT Payload (redacted): {json.dumps(redacted_payload, indent=2)}")

        return payload
    except Exception as e:
        logger.error(f"Error decoding JWT: {e}")
        return {}


def extract_user_info(payload):
    """Extract user information from JWT claims"""
    # Extract basic user info
    email = payload.get("email") or payload.get("preferred_username") or payload.get("mail") or "unknown@example.com"

    # For Cognito, use the sub as user_id and hash it for privacy
    user_id = payload.get("sub") or payload.get("user_id") or ""
    if user_id:
        # Create a consistent hash of the user ID for privacy
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()[:36]
        # Format as UUID-like string
        user_id = (
            f"{user_id_hash[:8]}-{user_id_hash[8:12]}-{user_id_hash[12:16]}-{user_id_hash[16:20]}-{user_id_hash[20:32]}"
        )

    # Extract username - for Cognito it's in cognito:username
    username = payload.get("cognito:username") or payload.get("preferred_username") or email.split("@")[0]

    # Extract organization - derive from issuer or provider
    org_id = "amazon-internal"  # Default for internal deployment
    if payload.get("iss"):
        from urllib.parse import urlparse

        # Secure provider detection using proper URL parsing
        issuer = payload["iss"]
        # Handle both full URLs and domain-only inputs
        url_to_parse = issuer if issuer.startswith(("http://", "https://")) else f"https://{issuer}"

        try:
            parsed = urlparse(url_to_parse)
            hostname = parsed.hostname

            if hostname:
                hostname_lower = hostname.lower()

                # Check for exact domain match or subdomain match
                # Using endswith with leading dot prevents bypass attacks
                if hostname_lower.endswith(".okta.com") or hostname_lower == "okta.com":
                    org_id = "okta"
                elif hostname_lower.endswith(".auth0.com") or hostname_lower == "auth0.com":
                    org_id = "auth0"
                elif hostname_lower.endswith(".microsoftonline.com") or hostname_lower == "microsoftonline.com":
                    org_id = "azure"
        except Exception:
            pass  # Keep default org_id if parsing fails

    # Extract team/department information - these fields vary by IdP
    # Provide defaults for consistent metric dimensions
    department = payload.get("department") or payload.get("dept") or payload.get("division") or "unspecified"
    team = payload.get("team") or payload.get("team_id") or payload.get("group") or "default-team"
    cost_center = payload.get("cost_center") or payload.get("costCenter") or payload.get("cost_code") or "general"
    manager = payload.get("manager") or payload.get("manager_email") or "unassigned"
    location = payload.get("location") or payload.get("office_location") or payload.get("office") or "remote"
    role = payload.get("role") or payload.get("job_title") or payload.get("title") or "user"

    return {
        "email": email,
        "user_id": user_id,
        "username": username,
        "organization_id": org_id,
        "department": department,
        "team": team,
        "cost_center": cost_center,
        "manager": manager,
        "location": location,
        "role": role,
        "account_uuid": payload.get("aud", ""),
        "issuer": payload.get("iss", ""),
        "subject": payload.get("sub", ""),
    }


def format_as_headers_dict(attributes):
    """Format attributes as headers dictionary for JSON output"""
    # Map attributes to HTTP headers expected by OTEL collector
    # Note: Headers must be lowercase to match OTEL collector configuration
    header_mapping = {
        "email": "x-user-email",
        "user_id": "x-user-id",
        "username": "x-user-name",
        "department": "x-department",
        "team": "x-team-id",
        "cost_center": "x-cost-center",
        "organization_id": "x-organization",
        "location": "x-location",
        "role": "x-role",
        "manager": "x-manager",
    }

    headers = {}
    for attr_key, header_name in header_mapping.items():
        if attr_key in attributes and attributes[attr_key]:
            headers[header_name] = attributes[attr_key]

    return headers


def get_token_via_credential_process():
    """Get monitoring token via credential-process to avoid direct keychain access"""
    logger.info("Getting token via credential-process...")

    # Path to credential process - add .exe extension on Windows
    import platform

    if platform.system() == "Windows":
        credential_process = os.path.expanduser("~/claude-code-with-bedrock/credential-process.exe")
    else:
        credential_process = os.path.expanduser("~/claude-code-with-bedrock/credential-process")

    # Check if credential process exists
    if not os.path.exists(credential_process):
        logger.warning(f"Credential process not found at {credential_process}")
        return None

    # Get profile name from AWS_PROFILE environment variable (set by Claude Code from settings.json)
    # Fall back to "ClaudeCode" for backward compatibility
    profile = os.environ.get("AWS_PROFILE", "ClaudeCode")

    try:
        # Run credential process with --profile flag and --get-monitoring-token flag
        # This will return cached token or trigger auth if needed
        result = subprocess.run(
            [credential_process, "--profile", profile, "--get-monitoring-token"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for auth if needed
        )

        if result.returncode == 0 and result.stdout.strip():
            logger.info("Successfully retrieved token via credential-process")
            return result.stdout.strip()
        else:
            logger.warning("Could not get token via credential-process")
            return None

    except subprocess.TimeoutExpired:
        logger.warning("Credential process timed out")
        return None
    except Exception as e:
        logger.warning(f"Failed to get token via credential-process: {e}")
        return None


def main():
    """Main function to generate OTEL headers"""
    parse_args()

    # Try to get token from environment first (fastest, set by credential_provider/__main__.py)
    token = os.environ.get("CLAUDE_CODE_MONITORING_TOKEN")
    if token:
        logger.info("Using token from environment variable CLAUDE_CODE_MONITORING_TOKEN")
    else:
        # Use credential-process to get token (handles auth if needed)
        # This avoids direct keychain access from OTEL helper
        token = get_token_via_credential_process()

        if not token:
            logger.warning("Could not obtain authentication token")
            # Return failure to indicate we couldn't get user attributes
            # Claude Code should handle this gracefully
            return 1

    # Decode token and extract user info
    try:
        payload = decode_jwt_payload(token)
        user_info = extract_user_info(payload)

        # Generate headers dictionary
        headers_dict = format_as_headers_dict(user_info)

        # In test mode, print detailed output
        if TEST_MODE:
            print("===== TEST MODE OUTPUT =====\n")
            print("Generated HTTP Headers:")
            for header_name, header_value in headers_dict.items():
                # Display in uppercase for readability but actual values are lowercase
                display_name = header_name.replace("x-", "X-").replace("-id", "-ID")
                print(f"  {display_name}: {header_value}")

            print("\n===== Extracted Attributes =====\n")
            for key, value in user_info.items():
                if key not in ["account_uuid", "issuer", "subject"]:  # Skip technical fields in summary
                    display_value = value[:30] + "..." if len(str(value)) > 30 else value
                    print(f"  {key.replace('_', '.')}: {display_value}")

            # Also show full attributes
            print()
            print(f"  user.email: {user_info['email']}")
            print(f"  user.id: {user_info['user_id'][:30]}...")
            print(f"  user.name: {user_info['username']}")
            print(f"  organization.id: {user_info['organization_id']}")
            print("  service.name: claude-code")
            print(f"  user.account_uuid: {user_info['account_uuid']}")
            print(f"  oidc.issuer: {user_info['issuer'][:30]}...")
            print(f"  oidc.subject: {user_info['subject'][:30]}...")
            print(f"  department: {user_info['department']}")
            print(f"  team.id: {user_info['team']}")
            print(f"  cost_center: {user_info['cost_center']}")
            print(f"  manager: {user_info['manager']}")
            print(f"  location: {user_info['location']}")
            print(f"  role: {user_info['role']}")

            print("\n========================")
        else:
            # Normal mode: Output as JSON (flat object with string values)
            print(json.dumps(headers_dict))

        if DEBUG_MODE or TEST_MODE:
            logger.info("Generated OTEL resource attributes:")
            if DEBUG_MODE:
                logger.debug(f"Attributes: {json.dumps(user_info, indent=2)}")

    except Exception as e:
        logger.error(f"Error processing token: {e}")
        # Return failure on error - Claude Code should handle this gracefully
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
