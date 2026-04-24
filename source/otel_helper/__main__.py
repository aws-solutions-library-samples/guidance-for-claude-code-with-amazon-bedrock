#!/usr/bin/env python3
# ABOUTME: OTEL helper script that extracts user attributes from JWT tokens or AWS caller identity
# ABOUTME: Outputs HTTP headers for OpenTelemetry collector to enable user attribution
# ABOUTME: Supports anonymous mode when authentication is disabled
"""
OTEL Headers Helper Script for Claude Code

This script retrieves authentication tokens from the storage method chosen by the customer
(system keyring or session file) and formats them as HTTP headers for use with the OTEL collector.
It extracts user information from JWT tokens and provides properly formatted headers
that the OTEL collector's attributes processor converts to resource attributes.

When authentication is disabled, identity is determined from the AWS caller:
- AWS IAM Identity Center (SSO) users: real username/email extracted from the
  assumed-role ARN session name (e.g. daniel.wirjo@company.com)
- IAM users: username extracted from the user ARN
- Non-SSO assumed roles: anonymous tracking via hashed ARN (consistent per principal)
- No AWS credentials: falls back to a generic anonymous identifier
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    import boto3
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    logger = logging.getLogger("claude-otel-headers")
    logger.warning("boto3 not available, anonymous mode will not work")

# Module-level cache for STS GetCallerIdentity to avoid repeated API calls.
# Each entry stores {"identity": <dict>, "cached_at": <float>}.
_sts_identity_cache = {}
_STS_CACHE_TTL_SECONDS = 300  # 5 minutes

# Configure debug mode if requested
DEBUG_MODE = os.environ.get("DEBUG_MODE", "").lower() in ("true", "1", "yes", "y")
TEST_MODE = False  # Will be set by command line argument
ANONYMOUS_MODE = False  # Will be set by command line argument

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
    parser.add_argument(
        "--anonymous",
        action="store_true",
        help="Force anonymous mode using AWS caller identity instead of JWT auth",
    )
    parser.add_argument(
        "--proxy",
        metavar="TARGET_URL",
        help="Run as a local OTLP proxy on port 4318, forwarding to TARGET_URL with user headers injected",
    )
    parser.add_argument(
        "--proxy-port",
        type=int,
        default=4318,
        metavar="PORT",
        help="Port for the local OTLP proxy (default: 4318)",
    )
    args = parser.parse_args()

    global TEST_MODE, ANONYMOUS_MODE
    TEST_MODE = args.test
    ANONYMOUS_MODE = args.anonymous

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


def get_cache_path():
    """Get the path to the OTEL headers cache file."""
    cache_dir = Path.home() / ".claude-code-session"
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile = os.environ.get("AWS_PROFILE", "ClaudeCode")
    return cache_dir / f"{profile}-otel-headers.json"


def read_cached_headers():
    """Read cached OTEL headers if they exist.

    User attributes (email, team, etc.) don't change between sessions,
    so cached headers are served regardless of token expiry. Headers are
    refreshed opportunistically when a valid token is available.
    """
    try:
        cache_path = get_cache_path()
        if not cache_path.exists():
            return None
        with open(cache_path) as f:
            cached = json.load(f)
        headers = cached.get("headers")
        if not headers:
            return None
        logger.debug("Using cached OTEL headers")
        return headers
    except Exception as e:
        logger.debug(f"Failed to read cached headers: {e}")
        return None


def write_cached_headers(headers, token_exp):
    """Write OTEL headers to cache file and a companion raw headers file."""
    try:
        cache_path = get_cache_path()
        import tempfile

        # Write main cache file atomically (prevents shell wrapper reading partial JSON)
        fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"headers": headers, "token_exp": token_exp, "cached_at": int(time.time())}, f)
            os.chmod(tmp_path, 0o600)
            os.rename(tmp_path, str(cache_path))
        except Exception:
            os.unlink(tmp_path)
            raise

        # Write companion file with just the raw headers JSON for the shell wrapper to cat
        raw_path = cache_path.with_suffix(".raw")
        fd, tmp_path = tempfile.mkstemp(dir=cache_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(headers, f)
            os.chmod(tmp_path, 0o600)
            os.rename(tmp_path, str(raw_path))
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.debug(f"Failed to write cached headers: {e}")


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
            timeout=30,  # Reduced from 300s - fail open if auth can't complete quickly
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


def get_aws_caller_identity():
    """Get AWS caller identity using STS GetCallerIdentity API.

    Results are cached for _STS_CACHE_TTL_SECONDS (default 5 min) to avoid
    redundant API calls when OTEL headers are regenerated frequently.
    """
    if not BOTO3_AVAILABLE:
        logger.warning("boto3 not available, cannot get AWS caller identity")
        return None

    # Check module-level cache
    cache_key = "default"
    cached = _sts_identity_cache.get(cache_key)
    if cached and (time.time() - cached["cached_at"]) < _STS_CACHE_TTL_SECONDS:
        logger.debug("Using cached STS GetCallerIdentity result")
        return cached["identity"]

    try:
        sts_client = boto3.client('sts')
        identity = sts_client.get_caller_identity()

        # Store in cache
        _sts_identity_cache[cache_key] = {
            "identity": identity,
            "cached_at": time.time(),
        }

        logger.info(f"Retrieved AWS caller identity: {identity.get('Arn', 'unknown')}")
        return identity
    except Exception as e:
        logger.warning(f"Failed to get AWS caller identity: {e}")
        return None


def _parse_arn_identity(arn):
    """Extract identity information from an AWS ARN.

    Detects AWS IAM Identity Center (SSO) ARNs and extracts the username/email
    from the session name. SSO assumed-role ARNs follow the pattern:
        arn:aws:sts::<account>:assumed-role/AWSReservedSSO_<PermissionSet>_<hash>/<username>

    For regular IAM users, extracts the username from:
        arn:aws:iam::<account>:user/<username>
        arn:aws:iam::<account>:user/<path>/<username>

    For non-SSO assumed roles, returns None (identity cannot be determined).

    Returns:
        dict with 'username', 'email', 'role', 'issuer' keys, or None if
        identity cannot be extracted from the ARN.
    """
    if not arn:
        return None

    try:
        parts = arn.split(":")
        if len(parts) < 6:
            return None

        resource = parts[5]  # e.g. "assumed-role/AWSReservedSSO_.../user@email.com"

        # Case 1: SSO assumed role
        # Pattern: assumed-role/AWSReservedSSO_<PermissionSet>_<hash>/<session-name>
        if resource.startswith("assumed-role/AWSReservedSSO_"):
            role_and_session = resource[len("assumed-role/"):]
            slash_idx = role_and_session.find("/")
            if slash_idx == -1:
                return None

            role_name = role_and_session[:slash_idx]
            session_name = role_and_session[slash_idx + 1:]

            # Extract permission set name from role: AWSReservedSSO_<Name>_<hash>
            # Remove "AWSReservedSSO_" prefix and trailing "_<hash>" (12 hex chars)
            perm_set = role_name[len("AWSReservedSSO_"):]
            # The hash suffix is the last segment after underscore
            last_underscore = perm_set.rfind("_")
            if last_underscore > 0:
                perm_set = perm_set[:last_underscore]

            # Session name is typically the SSO username (often an email)
            username = session_name
            email = session_name if "@" in session_name else f"{session_name}@anonymous"

            logger.info(f"Detected AWS SSO identity: {username} (permission set: {perm_set})")
            return {
                "username": username,
                "email": email,
                "role": perm_set,
                "issuer": "aws-sso",
            }

        # Case 2: IAM user
        # Pattern: user/<username> or user/<path>/<username>
        if resource.startswith("user/"):
            user_path = resource[len("user/"):]
            # Take the last segment as username (handles path-based users)
            username = user_path.rsplit("/", 1)[-1]
            return {
                "username": username,
                "email": f"{username}@anonymous",
                "role": "iam-user",
                "issuer": "aws-iam",
            }

        # Case 3: Non-SSO assumed role — cannot determine individual identity
        return None

    except Exception as e:
        logger.debug(f"Failed to parse ARN identity: {e}")
        return None


def _parse_assumed_role_arn(arn):
    """Extract role name and session name from a non-SSO assumed-role ARN.

    Pattern: arn:aws:sts::<account>:assumed-role/<RoleName>/<SessionName>

    Returns:
        dict with 'role_name' and 'session_name', or None if not an assumed-role ARN.
    """
    if not arn:
        return None

    try:
        parts = arn.split(":")
        if len(parts) < 6:
            return None

        resource = parts[5]

        if not resource.startswith("assumed-role/"):
            return None

        role_and_session = resource[len("assumed-role/"):]
        slash_idx = role_and_session.find("/")
        if slash_idx == -1:
            return None

        role_name = role_and_session[:slash_idx]
        session_name = role_and_session[slash_idx + 1:]

        return {
            "role_name": role_name,
            "session_name": session_name,
        }
    except Exception as e:
        logger.debug(f"Failed to parse assumed role ARN: {e}")
        return None


def create_anonymous_user_info(caller_identity=None):
    """Create user information for metrics when auth is disabled.

    If the caller is using AWS IAM Identity Center (SSO), real identity
    information (username/email) is extracted from the assumed-role ARN.
    For IAM users, the username is extracted from the user ARN.
    For non-SSO assumed roles, a hashed anonymous identifier is generated.
    """
    if caller_identity and caller_identity.get('Arn'):
        arn = caller_identity['Arn']
        account_id = caller_identity.get('Account', 'unknown')
        # SECURITY NOTE: 'aws-{account_id}' exposes the AWS account ID in metrics.
        # This is acceptable for internal observability but should be reviewed if
        # metrics are exported to external or third-party monitoring systems.
        org_id = f"aws-{account_id}"

        # Try to extract real identity from ARN (works for SSO and IAM users)
        arn_identity = _parse_arn_identity(arn)

        if arn_identity:
            # Real identity extracted from ARN — use username directly as user_id
            logger.info(f"Created identified user from ARN: {arn_identity['username']}")
            return {
                "email": arn_identity["email"],
                "user_id": arn_identity["username"],
                "username": arn_identity["username"],
                "organization_id": org_id,
                "department": "unspecified",
                "team": "default-team",
                "cost_center": "general",
                "manager": "unassigned",
                "location": "remote",
                "role": arn_identity["role"],
                "account_uuid": "",
                "issuer": arn_identity["issuer"],
                "subject": arn,
            }
        else:
            # Non-SSO assumed role: extract role name and session name for tracking.
            # Session names can be set by the caller (e.g. a CI pipeline name or
            # username), so they provide useful attribution even without SSO.
            role_info = _parse_assumed_role_arn(arn)
            if role_info:
                logger.info(f"Tracking assumed role: {role_info['role_name']}/{role_info['session_name']}")
                return {
                    "email": f"{role_info['session_name']}@anonymous",
                    "user_id": role_info["session_name"],
                    "username": role_info["session_name"],
                    "organization_id": org_id,
                    "department": "unspecified",
                    "team": "default-team",
                    "cost_center": "general",
                    "manager": "unassigned",
                    "location": "remote",
                    "role": role_info["role_name"],
                    "account_uuid": "",
                    "issuer": "aws-iam",
                    "subject": arn,
                }

            # Fallback: unrecognised ARN format — hash for anonymous tracking
            arn_hash = hashlib.sha256(arn.encode()).hexdigest()[:36]
            user_id = f"anon-{arn_hash[:8]}-{arn_hash[8:12]}-{arn_hash[12:16]}-{arn_hash[16:20]}-{arn_hash[20:32]}"
            logger.info(f"Created anonymous user ID from ARN: {user_id}")

            return {
                "email": "anonymous@example.com",
                "user_id": user_id,
                "username": "anonymous",
                "organization_id": org_id,
                "department": "anonymous",
                "team": "anonymous",
                "cost_center": "anonymous",
                "manager": "anonymous",
                "location": "anonymous",
                "role": "anonymous",
                "account_uuid": "",
                "issuer": "anonymous-mode",
                "subject": arn,
            }
    else:
        # No AWS identity at all
        logger.warning("No AWS caller identity available, using fallback anonymous ID")
        return {
            "email": "anonymous@example.com",
            "user_id": "anon-unknown",
            "username": "anonymous",
            "organization_id": "unknown",
            "department": "anonymous",
            "team": "anonymous",
            "cost_center": "anonymous",
            "manager": "anonymous",
            "location": "anonymous",
            "role": "anonymous",
            "account_uuid": "",
            "issuer": "anonymous-mode",
            "subject": "anon-unknown",
        }


def run_proxy(target_url: str, port: int = 4318):
    """Run a local OTLP proxy that injects user identity headers before forwarding.

    CoWork sends OTLP directly to the collector without user headers. This proxy
    sits at localhost:PORT, reads the cached user email from the monitoring token,
    adds x-user-email (and related) headers to every request, then forwards to the
    real ECS collector endpoint. The metrics_aggregator can then correlate CoWork
    token events to user emails just like it does for Claude Code CLI sessions.
    """
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    target_url = target_url.rstrip("/")
    logger.info(f"Starting OTLP proxy on port {port}, forwarding to {target_url}")

    def get_user_headers():
        """Return enrichment headers derived from the cached monitoring token."""
        token = None
        if not ANONYMOUS_MODE:
            token = os.environ.get("CLAUDE_CODE_MONITORING_TOKEN") or get_token_via_credential_process()

        if token:
            payload = decode_jwt_payload(token)
            user_info = extract_user_info(payload)
        else:
            caller_identity = get_aws_caller_identity()
            user_info = create_anonymous_user_info(caller_identity)

        return format_as_headers_dict(user_info)

    # Pre-fetch headers once at startup; refresh on each request so token
    # rotations are picked up without restarting the proxy.
    _header_cache = {"headers": {}, "fetched_at": 0}
    _HEADER_REFRESH_SECONDS = 300

    def fresh_user_headers():
        now = time.time()
        if now - _header_cache["fetched_at"] > _HEADER_REFRESH_SECONDS:
            try:
                _header_cache["headers"] = get_user_headers()
                _header_cache["fetched_at"] = now
            except Exception as e:
                logger.warning(f"Could not refresh user headers: {e}")
        return _header_cache["headers"]

    class ProxyHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self._proxy()

        def do_GET(self):
            # Health-check endpoint — CoWork polls / before starting telemetry
            if self.path in ("/", "/health"):
                self.send_response(200)
                self.end_headers()
            else:
                self._proxy()

        def _proxy(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""

            forward_url = f"{target_url}{self.path}"

            # Validate URL scheme to prevent file:// or other dangerous schemes
            if not forward_url.startswith(("http://", "https://")):
                logger.warning(f"Rejected proxy request with invalid scheme: {forward_url}")
                self.send_response(400)
                self.end_headers()
                return

            req = urllib.request.Request(forward_url, data=body, method=self.command)

            # Copy original headers
            for key, value in self.headers.items():
                lower = key.lower()
                if lower in ("host", "content-length", "transfer-encoding"):
                    continue
                req.add_header(key, value)

            # Inject user identity headers (override any client-supplied values)
            for header_name, header_value in fresh_user_headers().items():
                req.add_header(header_name, header_value)

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    self.send_response(resp.status)
                    for key, value in resp.getheaders():
                        if key.lower() != "transfer-encoding":
                            self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(resp.read())
            except Exception as e:
                logger.warning(f"Proxy forward error: {e}")
                self.send_response(502)
                self.end_headers()

        def log_message(self, fmt, *args):
            logger.debug(f"proxy: {fmt % args}")

    server = HTTPServer(("127.0.0.1", port), ProxyHandler)
    print(f"OTLP proxy listening on 127.0.0.1:{port} → {target_url}", flush=True)

    def shutdown_on_signal(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    import signal
    import threading as _threading
    if _threading.current_thread() is _threading.main_thread():
        signal.signal(signal.SIGTERM, shutdown_on_signal)
        signal.signal(signal.SIGINT, shutdown_on_signal)

    server.serve_forever()


def main():
    """Main function to generate OTEL headers"""
    args = parse_args()

    # Proxy mode: long-running local OTLP forwarder with user header injection
    if args.proxy:
        run_proxy(args.proxy, port=args.proxy_port)
        return 0

    # Layer 1: Check file cache first (avoids credential-process entirely)
    if not TEST_MODE:
        cached_headers = read_cached_headers()
        if cached_headers:
            print(json.dumps(cached_headers))
            return 0

    # Try to get token from environment first (fastest, set by credential_provider/__main__.py)
    token = None
    if not ANONYMOUS_MODE:
        token = os.environ.get("CLAUDE_CODE_MONITORING_TOKEN")
        if token:
            logger.info("Using token from environment variable CLAUDE_CODE_MONITORING_TOKEN")
        else:
            # Use credential-process to get token (handles auth if needed)
            # This avoids direct keychain access from OTEL helper
            token = get_token_via_credential_process()
    else:
        logger.info("Anonymous mode forced via --anonymous flag")

    # Decode token and extract user info
    try:
        if token:
            # Auth mode: Extract user info from JWT token
            payload = decode_jwt_payload(token)
            user_info = extract_user_info(payload)
            logger.info("Using authenticated user information from JWT token")
        else:
            # Anonymous mode: Use AWS caller identity for unique tracking
            logger.info("No authentication token available, using anonymous mode")
            caller_identity = get_aws_caller_identity()
            user_info = create_anonymous_user_info(caller_identity)

        # Generate headers dictionary
        headers_dict = format_as_headers_dict(user_info)
        # In test mode, print detailed output
        if TEST_MODE:
            print("===== TEST MODE OUTPUT =====\n")
            if token:
                print("Mode: Authenticated (JWT Token)")
            else:
                print("Mode: Anonymous (AWS Caller Identity)")
            print("\nGenerated HTTP Headers:")
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
            # Cache headers for future calls (avoids credential-process on next invocation)
            if token:
                token_exp = payload.get("exp")
                if token_exp:
                    write_cached_headers(headers_dict, token_exp)
                else:
                    logger.debug("JWT has no exp claim, skipping cache write")
            else:
                # Anonymous mode: cache with a synthetic TTL (5 minutes)
                write_cached_headers(headers_dict, int(time.time()) + _STS_CACHE_TTL_SECONDS)
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
