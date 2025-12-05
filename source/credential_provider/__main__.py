#!/usr/bin/env python3
# ABOUTME: AWS Credential Provider for OIDC authentication and Cognito Identity Pool federation
# ABOUTME: Supports multiple OIDC providers including Okta and Azure AD for Bedrock access
"""
AWS Credential Provider for OIDC + Cognito Identity Pool
Supports multiple OIDC providers for Bedrock access
"""

import base64
import errno
import hashlib
import html as html_module
import json
import os
import platform
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import boto3
import jwt
import keyring
import requests
from botocore import UNSIGNED
from botocore.config import Config

# No longer using file locks - using port-based locking instead

__version__ = "1.0.0"

# OIDC Provider Configurations
PROVIDER_CONFIGS = {
    "okta": {
        "name": "Okta",
        "authorize_endpoint": "/oauth2/v1/authorize",
        "token_endpoint": "/oauth2/v1/token",
        "scopes": "openid profile email",
        "response_type": "code",
        "response_mode": "query",
    },
    "auth0": {
        "name": "Auth0",
        "authorize_endpoint": "/authorize",
        "token_endpoint": "/oauth/token",
        "scopes": "openid profile email",
        "response_type": "code",
        "response_mode": "query",
    },
    "azure": {
        "name": "Azure AD",
        "authorize_endpoint": "/oauth2/v2.0/authorize",
        "token_endpoint": "/oauth2/v2.0/token",
        "scopes": "openid profile email",
        "response_type": "code",
        "response_mode": "query",
    },
    "cognito": {
        "name": "AWS Cognito User Pool",
        "authorize_endpoint": "/oauth2/authorize",
        "token_endpoint": "/oauth2/token",
        "scopes": "openid email",
        "response_type": "code",
        "response_mode": "query",
    },
}


class MultiProviderAuth:
    def __init__(self, profile=None):
        # Debug mode - set before loading config since _load_config may use _debug_print
        self.debug = os.getenv("COGNITO_AUTH_DEBUG", "").lower() in ("1", "true", "yes")

        # Load configuration from environment or config file
        # Auto-detect profile from config.json if not specified
        self.profile = profile or self._auto_detect_profile() or "ClaudeCode"

        self.config = self._load_config()

        # Determine provider type from domain
        self.provider_type = self._determine_provider_type()

        # Fail clearly if provider type is unknown
        if self.provider_type not in PROVIDER_CONFIGS:
            raise ValueError(
                f"Unknown provider type '{self.provider_type}'. "
                f"Valid providers: {', '.join(PROVIDER_CONFIGS.keys())}"
            )
        self.provider_config = PROVIDER_CONFIGS[self.provider_type]

        # OAuth configuration
        self.redirect_port = int(os.getenv("REDIRECT_PORT", "8400"))
        self.redirect_uri = f"http://localhost:{self.redirect_port}/callback"

        # Initialize credential storage
        self._init_credential_storage()

    def _debug_print(self, message):
        """Print debug message only if debug mode is enabled"""
        if self.debug:
            print(f"Debug: {message}", file=sys.stderr)

    def _auto_detect_profile(self):
        """Auto-detect profile name from config.json when only one profile exists."""
        try:
            # Try same directory as binary first (for testing)
            binary_dir = Path(__file__).parent if not getattr(sys, "frozen", False) else Path(sys.executable).parent
            config_path = binary_dir / "config.json"

            # Fall back to installed location
            if not config_path.exists():
                config_path = Path.home() / "claude-code-with-bedrock" / "config.json"

            if not config_path.exists():
                return None

            with open(config_path) as f:
                file_config = json.load(f)

            # New format with "profiles" key
            if "profiles" in file_config:
                profiles = list(file_config["profiles"].keys())
            else:
                # Old format: profile names are top-level keys
                profiles = list(file_config.keys())

            if len(profiles) == 1:
                self._debug_print(f"Auto-detected profile: {profiles[0]}")
                return profiles[0]
            elif len(profiles) > 1:
                self._debug_print(f"Multiple profiles found: {profiles}. Use --profile to specify.")
                return None
            return None
        except Exception as e:
            self._debug_print(f"Could not auto-detect profile: {e}")
            return None

    def _load_config(self):
        """Load configuration from config.json.

        Priority:
        1. Same directory as the binary (for testing dist/ packages)
        2. ~/claude-code-with-bedrock/config.json (for installed packages)
        """
        # Try same directory as binary first (for testing)
        binary_dir = Path(__file__).parent if not getattr(sys, "frozen", False) else Path(sys.executable).parent
        config_path = binary_dir / "config.json"

        # Fall back to installed location
        if not config_path.exists():
            config_path = Path.home() / "claude-code-with-bedrock" / "config.json"

        if not config_path.exists():
            raise ValueError(
                f"Configuration file not found in {binary_dir} or {Path.home() / 'claude-code-with-bedrock'}"
            )

        with open(config_path) as f:
            file_config = json.load(f)

        # Handle new config format with profiles
        if "profiles" in file_config:
            # New format
            profiles = file_config.get("profiles", {})
            if self.profile not in profiles:
                raise ValueError(f"Profile '{self.profile}' not found in configuration")
            profile_config = profiles[self.profile]

            # Map new field names to expected ones
            profile_config["provider_domain"] = profile_config.get("provider_domain", profile_config.get("okta_domain"))
            profile_config["client_id"] = profile_config.get("client_id", profile_config.get("okta_client_id"))

            # Handle both identity_pool_id and identity_pool_name for compatibility
            # BUT: Don't convert identity_pool_name if federated_role_arn is present (Direct STS mode)
            if "identity_pool_name" in profile_config and "federated_role_arn" not in profile_config:
                profile_config["identity_pool_id"] = profile_config["identity_pool_name"]

            profile_config["credential_storage"] = profile_config.get("credential_storage", "session")
        else:
            # Old format for backward compatibility
            profile_config = file_config.get(self.profile, {})

        # Auto-detect federation type based on configuration
        self._detect_federation_type(profile_config)

        # Validate required configuration based on federation type
        if profile_config.get("federation_type") == "direct":
            required = ["provider_domain", "client_id", "federated_role_arn"]
        else:
            required = ["provider_domain", "client_id", "identity_pool_id"]

        missing = [k for k in required if not profile_config.get(k)]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")

        # Set defaults
        profile_config.setdefault("aws_region", "us-east-1")
        profile_config.setdefault("provider_type", "auto")
        profile_config.setdefault("credential_storage", "session")
        profile_config.setdefault(
            "max_session_duration", 43200 if profile_config.get("federation_type") == "direct" else 28800
        )

        return profile_config

    def _detect_federation_type(self, config):
        """Auto-detect whether to use Cognito Identity Pool or direct STS federation"""
        # Explicit federation type takes precedence
        if "federation_type" in config:
            return

        # Auto-detect based on available configuration
        if "federated_role_arn" in config:
            config["federation_type"] = "direct"
            self._debug_print("Detected Direct STS federation mode (federated_role_arn found)")
        elif "identity_pool_id" in config or "identity_pool_name" in config:
            config["federation_type"] = "cognito"
            self._debug_print("Detected Cognito Identity Pool federation mode")
        else:
            # Default to cognito for backward compatibility
            config["federation_type"] = "cognito"
            self._debug_print("Defaulting to Cognito Identity Pool federation mode")

    def _determine_provider_type(self):
        """Determine provider type from domain"""
        domain = self.config["provider_domain"].lower()

        # If provider_type is explicitly set and it's NOT 'auto', use it
        provider_type = self.config.get("provider_type", "auto")
        if provider_type != "auto":
            return provider_type

        # Secure provider detection using proper URL parsing
        if not domain:
            # Fail with clear error for unknown providers
            raise ValueError(
                "Unable to auto-detect provider type for empty domain. "
                "Known providers: Okta, Auth0, Microsoft/Azure, AWS Cognito User Pool. "
                "Please check your provider domain configuration."
            )

        # Handle both full URLs and domain-only inputs
        url_to_parse = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"

        try:
            parsed = urlparse(url_to_parse)
            hostname = parsed.hostname

            if not hostname:
                # Fail with clear error for unknown providers
                raise ValueError(
                    f"Unable to auto-detect provider type for domain '{domain}'. "
                    f"Known providers: Okta, Auth0, Microsoft/Azure, AWS Cognito User Pool. "
                    f"Please check your provider domain configuration."
                )

            hostname_lower = hostname.lower()

            # Check for exact domain match or subdomain match
            # Using endswith with leading dot prevents bypass attacks
            if hostname_lower.endswith(".okta.com") or hostname_lower == "okta.com":
                return "okta"
            elif hostname_lower.endswith(".auth0.com") or hostname_lower == "auth0.com":
                return "auth0"
            elif hostname_lower.endswith(".microsoftonline.com") or hostname_lower == "microsoftonline.com":
                return "azure"
            elif hostname_lower.endswith(".windows.net") or hostname_lower == "windows.net":
                return "azure"
            elif hostname_lower.endswith(".amazoncognito.com") or hostname_lower == "amazoncognito.com":
                # Cognito User Pool domain format: my-domain.auth.{region}.amazoncognito.com
                return "cognito"
            else:
                # Fail with clear error for unknown providers
                raise ValueError(
                    f"Unable to auto-detect provider type for domain '{domain}'. "
                    f"Known providers: Okta, Auth0, Microsoft/Azure, AWS Cognito User Pool. "
                    f"Please check your provider domain configuration."
                )
        except ValueError:
            raise
        except Exception as e:
            # Fail with clear error for unknown providers
            raise ValueError(f"Unable to auto-detect provider type for domain '{domain}': {e}") from e

    def _init_credential_storage(self):
        """Initialize secure credential storage"""
        # Check storage method from config
        self.credential_storage = self.config.get("credential_storage", "session")

        if self.credential_storage == "session":
            # Session-based storage uses temporary files
            self.cache_dir = Path.home() / "claude-code-with-bedrock" / "cache"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        # For keyring, no directory setup needed

    def get_cached_credentials(self):
        """Retrieve valid credentials from configured storage"""
        if self.credential_storage == "keyring":
            try:
                # On Windows, credentials are split into multiple entries due to size limits
                if platform.system() == "Windows":
                    # Retrieve split credentials
                    keys_json = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-keys")
                    token1 = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-token1")
                    token2 = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-token2")
                    meta_json = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-meta")

                    if not all([keys_json, token1, token2, meta_json]):
                        return None

                    # Reconstruct credentials
                    keys = json.loads(keys_json)
                    meta = json.loads(meta_json)

                    creds = {
                        "Version": meta["Version"],
                        "AccessKeyId": keys["AccessKeyId"],
                        "SecretAccessKey": keys["SecretAccessKey"],
                        "SessionToken": token1 + token2,
                        "Expiration": meta["Expiration"],
                    }
                else:
                    # Non-Windows: single entry storage
                    creds_json = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-credentials")

                    if not creds_json:
                        return None

                    creds = json.loads(creds_json)

                # Check for dummy/cleared credentials first
                # These are set when credentials are cleared to maintain keychain permissions
                if creds.get("AccessKeyId") == "EXPIRED":
                    self._debug_print("Found cleared dummy credentials, need re-authentication")
                    return None

                # Validate expiration for real credentials
                exp_str = creds.get("Expiration")
                if exp_str:
                    exp_time = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)

                    # Use credentials if they expire in more than 30 seconds
                    if (exp_time - now).total_seconds() > 30:
                        return creds

            except Exception as e:
                self._debug_print(f"Error retrieving credentials from keyring: {e}")
                return None
        else:
            # Session storage uses ~/.aws/credentials file
            credentials = self.read_from_credentials_file(self.profile)

            if not credentials:
                return None

            # Check for dummy/cleared credentials first
            if credentials.get("AccessKeyId") == "EXPIRED":
                self._debug_print("Found cleared dummy credentials in credentials file, need re-authentication")
                return None

            # Validate expiration
            exp_str = credentials.get("Expiration")
            if exp_str:
                exp_time = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)

                # Use credentials if they expire in more than 30 seconds
                if (exp_time - now).total_seconds() > 30:
                    return credentials

            return None

    def save_credentials(self, credentials):
        """Save credentials to configured storage"""
        if self.credential_storage == "keyring":
            try:
                # On Windows, split credentials into multiple entries due to size limits
                # Windows Credential Manager has a 2560 byte limit, but uses UTF-16LE encoding
                if platform.system() == "Windows":
                    # Split the SessionToken in half
                    token = credentials["SessionToken"]
                    mid = len(token) // 2

                    # Store as 4 separate entries
                    keyring.set_password(
                        "claude-code-with-bedrock",
                        f"{self.profile}-keys",
                        json.dumps(
                            {
                                "AccessKeyId": credentials["AccessKeyId"],
                                "SecretAccessKey": credentials["SecretAccessKey"],
                            }
                        ),
                    )
                    keyring.set_password("claude-code-with-bedrock", f"{self.profile}-token1", token[:mid])
                    keyring.set_password("claude-code-with-bedrock", f"{self.profile}-token2", token[mid:])
                    keyring.set_password(
                        "claude-code-with-bedrock",
                        f"{self.profile}-meta",
                        json.dumps({"Version": credentials["Version"], "Expiration": credentials["Expiration"]}),
                    )
                else:
                    # Non-Windows: store as single entry
                    keyring.set_password(
                        "claude-code-with-bedrock", f"{self.profile}-credentials", json.dumps(credentials)
                    )
            except Exception as e:
                self._debug_print(f"Error saving credentials to keyring: {e}")
                raise Exception(f"Failed to save credentials to keyring: {str(e)}") from e
        else:
            # Session storage uses ~/.aws/credentials file
            self.save_to_credentials_file(credentials, self.profile)

    def clear_cached_credentials(self):
        """Clear all cached credentials for this profile"""
        cleared_items = []

        # Clear from keyring by replacing with expired credentials
        # This maintains keychain access permissions on macOS
        try:
            if platform.system() == "Windows":
                # On Windows, we have 4 separate entries to clear
                entries_to_clear = [
                    f"{self.profile}-keys",
                    f"{self.profile}-token1",
                    f"{self.profile}-token2",
                    f"{self.profile}-meta",
                ]

                for entry in entries_to_clear:
                    if keyring.get_password("claude-code-with-bedrock", entry):
                        # Replace with expired dummy data
                        if "keys" in entry:
                            expired_data = json.dumps({"AccessKeyId": "EXPIRED", "SecretAccessKey": "EXPIRED"})
                        elif "token" in entry:
                            expired_data = "EXPIRED"
                        elif "meta" in entry:
                            expired_data = json.dumps({"Version": 1, "Expiration": "2000-01-01T00:00:00Z"})
                        else:
                            expired_data = "EXPIRED"

                        keyring.set_password("claude-code-with-bedrock", entry, expired_data)

                cleared_items.append("keyring credentials (Windows)")
            else:
                # Non-Windows: single entry storage
                if keyring.get_password("claude-code-with-bedrock", f"{self.profile}-credentials"):
                    # Replace with expired dummy credential instead of deleting
                    # This prevents macOS from asking for "Always Allow" again
                    expired_credential = json.dumps(
                        {
                            "Version": 1,
                            "AccessKeyId": "EXPIRED",
                            "SecretAccessKey": "EXPIRED",
                            "SessionToken": "EXPIRED",
                            "Expiration": "2000-01-01T00:00:00Z",  # Far past date
                        }
                    )
                    keyring.set_password("claude-code-with-bedrock", f"{self.profile}-credentials", expired_credential)
                    cleared_items.append("keyring credentials")
        except Exception as e:
            self._debug_print(f"Could not clear keyring credentials: {e}")

        # Clear monitoring token from keyring
        try:
            if keyring.get_password("claude-code-with-bedrock", f"{self.profile}-monitoring"):
                # Replace with expired dummy token
                expired_token = json.dumps(
                    {"token": "EXPIRED", "expires": 0, "email": "", "profile": self.profile}  # Expired timestamp
                )
                keyring.set_password("claude-code-with-bedrock", f"{self.profile}-monitoring", expired_token)
                cleared_items.append("keyring monitoring token")
        except Exception as e:
            self._debug_print(f"Could not clear keyring monitoring token: {e}")

        # Clear credentials file (for session storage mode)
        try:
            credentials_path = Path.home() / ".aws" / "credentials"
            if credentials_path.exists():
                # Replace with expired dummy credentials instead of deleting
                # This preserves the file for other profiles
                expired_creds = {
                    "Version": 1,
                    "AccessKeyId": "EXPIRED",
                    "SecretAccessKey": "EXPIRED",
                    "SessionToken": "EXPIRED",
                    "Expiration": "2000-01-01T00:00:00Z",
                }
                self.save_to_credentials_file(expired_creds, self.profile)
                cleared_items.append("credentials file")
        except Exception as e:
            self._debug_print(f"Could not clear credentials file: {e}")

        # Clear monitoring token from session directory
        session_dir = Path.home() / ".claude-code-session"
        if session_dir.exists():
            monitoring_file = session_dir / f"{self.profile}-monitoring.json"

            if monitoring_file.exists():
                monitoring_file.unlink()
                cleared_items.append("monitoring token file")

            # Remove directory if empty
            try:
                if not any(session_dir.iterdir()):
                    session_dir.rmdir()
            except Exception:
                pass

        return cleared_items

    def save_monitoring_token(self, id_token, token_claims):
        """Save ID token for monitoring authentication"""
        try:
            # Extract relevant claims
            token_data = {
                "token": id_token,
                "expires": token_claims.get("exp", 0),
                "email": token_claims.get("email", ""),
                "profile": self.profile,
            }

            if self.credential_storage == "keyring":
                # Store monitoring token in keyring
                keyring.set_password("claude-code-with-bedrock", f"{self.profile}-monitoring", json.dumps(token_data))
            else:
                # Save to session directory alongside credentials
                session_dir = Path.home() / ".claude-code-session"
                session_dir.mkdir(parents=True, exist_ok=True)

                # Use simple session file per profile
                token_file = session_dir / f"{self.profile}-monitoring.json"

                with open(token_file, "w") as f:
                    json.dump(token_data, f)
                token_file.chmod(0o600)

            # Also export to environment for this session
            os.environ["CLAUDE_CODE_MONITORING_TOKEN"] = id_token

            self._debug_print(f"Saved monitoring token for {token_claims.get('email', 'user')}")
        except Exception as e:
            # Non-fatal error - monitoring is optional
            self._debug_print(f"Warning: Could not save monitoring token: {e}")

    def get_monitoring_token(self):
        """Retrieve valid monitoring token from configured storage"""
        try:
            # First check if it's in environment (from current session)
            import os

            env_token = os.environ.get("CLAUDE_CODE_MONITORING_TOKEN")
            if env_token:
                return env_token

            if self.credential_storage == "keyring":
                # Retrieve from keyring
                token_json = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-monitoring")

                if not token_json:
                    return None

                token_data = json.loads(token_json)
            else:
                # Check session file
                session_dir = Path.home() / ".claude-code-session"
                token_file = session_dir / f"{self.profile}-monitoring.json"

                if not token_file.exists():
                    return None

                with open(token_file) as f:
                    token_data = json.load(f)

            # Check expiration
            exp_time = token_data.get("expires", 0)
            now = int(datetime.now(timezone.utc).timestamp())

            # Return token if it expires in more than 10 minutes
            if exp_time - now > 600:
                token = token_data["token"]
                # Set in environment for this session
                os.environ["CLAUDE_CODE_MONITORING_TOKEN"] = token
                return token

            return None
        except Exception:
            return None

    def save_to_credentials_file(self, credentials, profile="ClaudeCode"):
        """Save credentials to ~/.aws/credentials file

        Args:
            credentials: Dict with AccessKeyId, SecretAccessKey, SessionToken, Expiration
            profile: Profile name to use in credentials file (default: ClaudeCode)
        """
        import tempfile
        from configparser import ConfigParser

        credentials_path = Path.home() / ".aws" / "credentials"

        # Create ~/.aws directory if it doesn't exist
        credentials_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing file or create new config
        # Disable inline comment characters so we can use keys like 'x-expiration'
        config = ConfigParser(inline_comment_prefixes=())
        if credentials_path.exists():
            try:
                config.read(credentials_path)
            except Exception as e:
                self._debug_print(f"Warning: Could not read existing credentials file: {e}")

        # Update profile section
        if profile not in config:
            config[profile] = {}

        config[profile]["aws_access_key_id"] = credentials["AccessKeyId"]
        config[profile]["aws_secret_access_key"] = credentials["SecretAccessKey"]
        config[profile]["aws_session_token"] = credentials["SessionToken"]

        # Add expiration as a special key that AWS SDK will ignore
        # Use 'x-' prefix which is a convention for custom/extension fields
        if "Expiration" in credentials:
            config[profile]["x-expiration"] = credentials["Expiration"]

        # Atomic write using temporary file
        try:
            # Write to temporary file first
            temp_fd, temp_path = tempfile.mkstemp(dir=credentials_path.parent, prefix=".credentials.", suffix=".tmp")

            try:
                with os.fdopen(temp_fd, "w") as f:
                    config.write(f)

                # Set restrictive permissions on temp file
                os.chmod(temp_path, 0o600)

                # Atomic rename
                os.replace(temp_path, credentials_path)

                self._debug_print(f"Saved credentials to {credentials_path} for profile '{profile}'")
            except Exception:
                # Clean up temp file on error
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass
                raise
        except Exception as e:
            raise Exception(f"Failed to save credentials to file: {str(e)}") from e

    def read_from_credentials_file(self, profile="ClaudeCode"):
        """Read credentials from ~/.aws/credentials file

        Args:
            profile: Profile name to read from credentials file

        Returns:
            Dict with credentials or None if not found
        """
        from configparser import ConfigParser

        credentials_path = Path.home() / ".aws" / "credentials"

        if not credentials_path.exists():
            return None

        try:
            # Disable inline comment characters to read keys like 'x-expiration'
            config = ConfigParser(inline_comment_prefixes=())
            config.read(credentials_path)

            if profile not in config:
                return None

            profile_section = config[profile]

            # Build credentials dict
            credentials = {
                "Version": 1,
                "AccessKeyId": profile_section.get("aws_access_key_id"),
                "SecretAccessKey": profile_section.get("aws_secret_access_key"),
                "SessionToken": profile_section.get("aws_session_token"),
            }

            # Extract expiration from custom field if present
            expiration = profile_section.get("x-expiration")
            if expiration:
                credentials["Expiration"] = expiration

            # Validate all required fields are present
            if not all(
                [credentials.get("AccessKeyId"), credentials.get("SecretAccessKey"), credentials.get("SessionToken")]
            ):
                return None

            return credentials

        except Exception as e:
            self._debug_print(f"Error reading credentials from file: {e}")
            return None

    def check_credentials_file_expiration(self, profile="ClaudeCode"):
        """Check if credentials in file are expired

        Args:
            profile: Profile name to check

        Returns:
            True if expired, False if valid
        """
        credentials = self.read_from_credentials_file(profile)

        if not credentials:
            return True  # No credentials = expired

        exp_str = credentials.get("Expiration")
        if not exp_str:
            # No expiration info, assume expired for safety
            return True

        try:
            exp_time = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)

            # Use 30-second buffer - consider expired if less than 30s remaining
            remaining_seconds = (exp_time - now).total_seconds()
            return remaining_seconds <= 30

        except Exception as e:
            self._debug_print(f"Error parsing expiration: {e}")
            return True  # Assume expired on parse error

    def authenticate_oidc(self):
        """Perform OIDC authentication with PKCE"""
        state = secrets.token_urlsafe(16)
        nonce = secrets.token_urlsafe(16)

        # Generate PKCE parameters
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("utf-8")).digest()).decode("utf-8").rstrip("=")
        )

        # Build authorization URL based on provider
        provider_domain = self.config["provider_domain"]

        # For Azure/Microsoft, if domain includes /v2.0, we need to strip it
        # since the endpoints already include the full path
        if self.provider_type == "azure" and provider_domain.endswith("/v2.0"):
            provider_domain = provider_domain[:-5]  # Remove '/v2.0'

        # For Cognito User Pool, we need to extract the domain and construct the URL differently
        if self.provider_type == "cognito":
            # Domain format: cognito-idp.{region}.amazonaws.com/{user-pool-id}
            # OAuth2 endpoints are at: https://{user-pool-domain}.auth.{region}.amazoncognito.com
            # We need the User Pool domain (configured separately in Cognito console)
            # For now, we'll use the domain as provided, which should be the User Pool domain
            if "amazoncognito.com" not in provider_domain:
                # If it's the identity pool format, we need the actual User Pool domain
                raise ValueError(
                    "For Cognito User Pool, please provide the User Pool domain "
                    "(e.g., 'my-domain.auth.us-east-1.amazoncognito.com'), "
                    "not the identity pool endpoint."
                )
            base_url = f"https://{provider_domain}"
        else:
            base_url = f"https://{provider_domain}"

        auth_params = {
            "client_id": self.config["client_id"],
            "response_type": self.provider_config["response_type"],
            "scope": self.provider_config["scopes"],
            "redirect_uri": self.redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }

        # Add provider-specific parameters
        if self.provider_type == "azure":
            auth_params["response_mode"] = "query"
            auth_params["prompt"] = "select_account"

        auth_url = f"{base_url}{self.provider_config['authorize_endpoint']}?" + urlencode(auth_params)

        # Setup callback server
        auth_result = {"code": None, "error": None}
        server = HTTPServer(("127.0.0.1", self.redirect_port), self._create_callback_handler(state, auth_result))

        # Start server in background
        server_thread = threading.Thread(target=server.handle_request)
        server_thread.daemon = True
        server_thread.start()

        # Open browser
        self._debug_print(f"Opening browser for {self.provider_config['name']} authentication...")
        self._debug_print(f"If browser doesn't open, visit: {auth_url}")
        webbrowser.open(auth_url)

        # Wait for callback
        server_thread.join(timeout=300)  # 5 minute timeout

        if auth_result["error"]:
            raise Exception(f"Authentication error: {auth_result['error']}")

        if not auth_result["code"]:
            raise Exception("Authentication timeout - no authorization code received")

        # Exchange code for tokens
        token_data = {
            "grant_type": "authorization_code",
            "code": auth_result["code"],
            "redirect_uri": self.redirect_uri,
            "client_id": self.config["client_id"],
            "code_verifier": code_verifier,
        }

        # Build token endpoint URL
        token_url = f"{base_url}{self.provider_config['token_endpoint']}"

        token_response = requests.post(
            token_url,
            data=token_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,  # 30 second timeout for token exchange
        )

        if not token_response.ok:
            raise Exception(f"Token exchange failed: {token_response.text}")

        tokens = token_response.json()

        # Validate nonce in ID token (if provider includes it)
        id_token_claims = jwt.decode(tokens["id_token"], options={"verify_signature": False})
        if "nonce" in id_token_claims and id_token_claims.get("nonce") != nonce:
            raise Exception("Invalid nonce in ID token")

        # Enhanced debug logging for claims
        if self.debug:
            self._debug_print("\n=== ID Token Claims ===")
            self._debug_print(json.dumps(id_token_claims, indent=2, default=str))

            # Log specific important claims
            important_claims = [
                "sub",
                "email",
                "name",
                "preferred_username",
                "groups",
                "cognito:groups",
                "custom:department",
                "custom:role",
            ]
            self._debug_print("\n=== Key Claims for Mapping ===")
            for claim in important_claims:
                if claim in id_token_claims:
                    self._debug_print(f"{claim}: {id_token_claims[claim]}")

        return tokens["id_token"], id_token_claims

    def _create_callback_handler(self, expected_state, result_container):
        """Create HTTP handler for OAuth callback"""
        parent = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parent._debug_print(f"Received callback request: {self.path}")
                query = parse_qs(urlparse(self.path).query)

                if query.get("error"):
                    result_container["error"] = query.get("error_description", ["Unknown error"])[0]
                    self._send_response(400, "Authentication failed")
                elif query.get("state", [""])[0] == expected_state and "code" in query:
                    result_container["code"] = query["code"][0]
                    self._send_response(200, "Authentication successful! You can close this window.")
                else:
                    result_container["error"] = "Invalid state or missing code"
                    self._send_response(400, "Invalid response")

            def _send_response(self, code, message):
                self.send_response(code)
                self.send_header("Content-type", "text/html")
                self.end_headers()
                html = f"""
                <html>
                <head><title>Authentication</title></head>
                <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1>{message}</h1>
                    <p>Return to your terminal to continue.</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode())

            def log_message(self, format, *args):
                pass  # Suppress logs

        return CallbackHandler

    def get_aws_credentials(self, id_token, token_claims):
        """Exchange OIDC token for AWS credentials"""
        self._debug_print("Entering get_aws_credentials method")

        # Route to appropriate federation method
        federation_type = self.config.get("federation_type", "cognito")
        self._debug_print(f"Using federation type: {federation_type}")

        if federation_type == "direct":
            return self.get_aws_credentials_direct(id_token, token_claims)
        else:
            return self.get_aws_credentials_cognito(id_token, token_claims)

    def get_aws_credentials_direct(self, id_token, token_claims):
        """Direct STS federation without Cognito Identity Pool - provides 12 hour sessions"""
        self._debug_print("Using Direct STS federation (AssumeRoleWithWebIdentity)")

        # Clear any AWS credentials to prevent recursive calls
        env_vars_to_clear = ["AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
        saved_env = {}
        for var in env_vars_to_clear:
            if var in os.environ:
                saved_env[var] = os.environ[var]
                del os.environ[var]

        try:
            # Get the federated role ARN from config
            federated_role_arn = self.config.get("federated_role_arn")
            if not federated_role_arn:
                raise ValueError("federated_role_arn is required for direct STS federation")

            # Create STS client
            sts_client = boto3.client("sts", region_name=self.config["aws_region"])

            # Prepare session tags from token claims
            session_tags = []

            # Map common claims to session tags
            tag_mappings = {
                "email": "UserEmail",
                "sub": "UserId",
                "preferred_username": "UserName",
                "name": "UserName",  # Fallback for providers that use 'name' instead
            }

            for claim_key, tag_key in tag_mappings.items():
                if claim_key in token_claims:
                    # Session tag values have a 256 character limit
                    tag_value = str(token_claims[claim_key])[:256]
                    session_tags.append({"Key": tag_key, "Value": tag_value})

            # Generate session name from user identifier
            # AWS RoleSessionName regex: [\w+=,.@-]*
            # Auth0 often uses pipe-delimited format in sub claims (e.g., auth0|12345)
            # Sanitize to replace invalid characters with hyphens
            session_name = "claude-code"
            if "sub" in token_claims:
                # Use first 32 chars of sub for uniqueness, sanitized for AWS
                sub_sanitized = re.sub(r"[^\w+=,.@-]", "-", str(token_claims["sub"])[:32])
                session_name = f"claude-code-{sub_sanitized}"
            elif "email" in token_claims:
                # Use email username part, sanitized
                email_part = token_claims["email"].split("@")[0][:32]
                email_sanitized = re.sub(r"[^\w+=,.@-]", "-", email_part)
                session_name = f"claude-code-{email_sanitized}"

            self._debug_print(f"Assuming role: {federated_role_arn}")
            self._debug_print(f"Session name: {session_name}")
            self._debug_print(f"Session tags: {session_tags}")

            # Call AssumeRoleWithWebIdentity
            # Note: AssumeRoleWithWebIdentity doesn't support Tags parameter directly
            # Session tags must be passed via the token claims and configured in the trust policy
            assume_role_params = {
                "RoleArn": federated_role_arn,
                "RoleSessionName": session_name,
                "WebIdentityToken": id_token,
                "DurationSeconds": self.config.get("max_session_duration", 43200),  # 12 hours
            }

            response = sts_client.assume_role_with_web_identity(**assume_role_params)

            # Extract credentials
            creds = response["Credentials"]

            # Format for AWS CLI
            formatted_creds = {
                "Version": 1,
                "AccessKeyId": creds["AccessKeyId"],
                "SecretAccessKey": creds["SecretAccessKey"],
                "SessionToken": creds["SessionToken"],
                "Expiration": (
                    creds["Expiration"].isoformat()
                    if hasattr(creds["Expiration"], "isoformat")
                    else creds["Expiration"]
                ),
            }

            self._debug_print(
                f"Successfully obtained credentials via Direct STS, expires: {formatted_creds['Expiration']}"
            )
            return formatted_creds

        except Exception as e:
            # Check if this is a credential error that suggests bad cached credentials
            error_str = str(e)
            if any(
                err in error_str
                for err in [
                    "InvalidParameterException",
                    "NotAuthorizedException",
                    "ValidationError",
                    "Invalid AccessKeyId",
                    "ExpiredToken",
                    "Invalid JWT",
                ]
            ):
                self._debug_print("Detected invalid credentials, clearing cache...")
                self.clear_cached_credentials()
                # Add helpful message for user
                raise Exception(
                    f"Authentication failed - cached credentials were invalid and have been cleared.\n"
                    f"Please try again to re-authenticate.\n"
                    f"Original error: {error_str}"
                ) from e
            raise Exception(f"Failed to get AWS credentials via Direct STS: {str(e)}") from None
        finally:
            # Restore environment variables
            for var, value in saved_env.items():
                os.environ[var] = value

    def get_aws_credentials_cognito(self, id_token, token_claims):
        """Exchange OIDC token for AWS credentials via Cognito Identity Pool"""
        self._debug_print("Using Cognito Identity Pool federation")

        # Clear any AWS credentials to prevent recursive calls
        env_vars_to_clear = ["AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
        saved_env = {}
        for var in env_vars_to_clear:
            if var in os.environ:
                saved_env[var] = os.environ[var]
                del os.environ[var]

        try:
            # Use unsigned requests for Cognito Identity (no AWS credentials needed)
            self._debug_print("Creating Cognito Identity client...")
            cognito_client = boto3.client(
                "cognito-identity", region_name=self.config["aws_region"], config=Config(signature_version=UNSIGNED)
            )
            self._debug_print("Cognito client created")

            self._debug_print("Creating STS client...")
            boto3.client("sts", region_name=self.config["aws_region"])
            self._debug_print("STS client created")
        finally:
            # Restore environment variables
            for var, value in saved_env.items():
                os.environ[var] = value

        try:
            # Log authentication details for debugging
            self._debug_print(f"Provider type: {self.provider_type}")
            self._debug_print(f"AWS Region: {self.config['aws_region']}")
            self._debug_print(f"Identity Pool ID: {self.config['identity_pool_id']}")

            # Determine the correct login key based on provider type
            if self.provider_type == "cognito":
                # For Cognito User Pool, extract from token issuer to ensure case matches
                if "iss" in token_claims:
                    # Use the issuer from the token to ensure case matches
                    issuer = token_claims["iss"]
                    login_key = issuer.replace("https://", "")
                    self._debug_print("Using issuer from token as login key")
                else:
                    # Fallback: construct from config
                    user_pool_id = self.config.get("cognito_user_pool_id")
                    if not user_pool_id:
                        raise ValueError("cognito_user_pool_id is required for Cognito User Pool authentication")
                    login_key = f"cognito-idp.{self.config['aws_region']}.amazonaws.com/{user_pool_id}"
                    self._debug_print(f"Cognito User Pool ID from config: {user_pool_id}")
            else:
                # For external OIDC providers, use the provider domain
                login_key = self.config["provider_domain"]

            self._debug_print(f"Login key: {login_key}")
            self._debug_print(f"Token claims: {list(token_claims.keys())}")
            if "iss" in token_claims:
                self._debug_print(f"Token issuer: {token_claims['iss']}")

            # Log all claims being passed for principal tags
            if self.debug:
                self._debug_print("\n=== Claims being sent to Cognito Identity ===")
                self._debug_print(f"Provider: {login_key}")
                self._debug_print("Claims that could be mapped to principal tags:")
                for key, value in token_claims.items():
                    self._debug_print(f"  {key}: {value}")

            # Get Cognito identity
            self._debug_print(f"Calling GetId with identity pool: {self.config['identity_pool_id']}")
            identity_response = cognito_client.get_id(
                IdentityPoolId=self.config["identity_pool_id"], Logins={login_key: id_token}
            )

            identity_id = identity_response["IdentityId"]
            self._debug_print(f"Got Cognito Identity ID: {identity_id}")

            # For enhanced flow, directly get credentials
            # Since we have a specific role configured, we'll use the role-based approach
            role_arn = self.config.get("role_arn")
            self._debug_print(f"Configured role ARN: {role_arn if role_arn else 'None (using default pool role)'}")

            if role_arn:
                # Get credentials for identity first to get the OIDC token
                credentials_response = cognito_client.get_credentials_for_identity(
                    IdentityId=identity_id, Logins={login_key: id_token}
                )

                # The credentials from Cognito are temporary credentials for the default role
                # Since we want to use our specific role with session tags, we need to do AssumeRole
                creds = credentials_response["Credentials"]
            else:
                # Get default role from identity pool
                credentials_response = cognito_client.get_credentials_for_identity(
                    IdentityId=identity_id, Logins={login_key: id_token}
                )

                creds = credentials_response["Credentials"]

            # Format for AWS CLI
            formatted_creds = {
                "Version": 1,
                "AccessKeyId": creds["AccessKeyId"],
                "SecretAccessKey": creds["SecretKey"],
                "SessionToken": creds["SessionToken"],
                "Expiration": (
                    creds["Expiration"].isoformat()
                    if hasattr(creds["Expiration"], "isoformat")
                    else creds["Expiration"]
                ),
            }

            return formatted_creds

        except Exception as e:
            # Check if this is a credential error that suggests bad cached credentials
            error_str = str(e)
            if any(
                err in error_str
                for err in [
                    "InvalidParameterException",
                    "NotAuthorizedException",
                    "ValidationError",
                    "Invalid AccessKeyId",
                    "Token is not from a supported provider",
                ]
            ):
                self._debug_print("Detected invalid credentials, clearing cache...")
                self.clear_cached_credentials()
                # Add helpful message for user
                raise Exception(
                    f"Authentication failed - cached credentials were invalid and have been cleared.\n"
                    f"Please try again to re-authenticate.\n"
                    f"Original error: {error_str}"
                ) from e
            raise Exception(f"Failed to get AWS credentials: {str(e)}") from None

    def _wait_for_auth_completion(self, timeout=60):
        """Wait for another process to complete authentication using port-based detection"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check if port is still in use (another auth in progress)
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                test_socket.bind(("127.0.0.1", self.redirect_port))
                test_socket.close()
                # Port is free, auth must have completed or failed
                # Check for cached credentials
                cached = self.get_cached_credentials()
                if cached:
                    return cached
                else:
                    # Auth failed or was cancelled
                    return None
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    # Port still in use, auth still in progress
                    time.sleep(0.5)
                else:
                    # Other error
                    raise
            finally:
                try:
                    test_socket.close()
                except Exception:
                    pass

        return None

    def authenticate_for_monitoring(self):
        """Authenticate specifically for monitoring token (no AWS credential output)"""
        try:
            # Try to acquire port lock by testing if we can bind to it
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                test_socket.bind(("127.0.0.1", self.redirect_port))
                test_socket.close()
                # We got the port, we can proceed with authentication
                self._debug_print("Port available, proceeding with monitoring authentication")
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    # Port in use, another auth is in progress
                    self._debug_print("Another authentication is in progress, waiting...")
                    test_socket.close()

                    # Wait for the other process to complete
                    # After waiting, check if we now have a monitoring token
                    self._wait_for_auth_completion()
                    token = self.get_monitoring_token()
                    if token:
                        return token
                    else:
                        self._debug_print("Authentication timeout or failed in another process")
                        return None
                else:
                    test_socket.close()
                    raise

            # Authenticate with OIDC provider
            self._debug_print(f"Authenticating with {self.provider_config['name']} for monitoring token...")
            id_token, token_claims = self.authenticate_oidc()

            # Get AWS credentials (we need them but won't output them)
            self._debug_print("Exchanging token for AWS credentials...")
            credentials = self.get_aws_credentials(id_token, token_claims)

            # Cache credentials for future use
            self.save_credentials(credentials)

            # Save monitoring token
            self.save_monitoring_token(id_token, token_claims)

            # Return just the monitoring token
            return id_token

        except KeyboardInterrupt:
            # User cancelled
            self._debug_print("Authentication cancelled by user")
            return None
        except Exception as e:
            self._debug_print(f"Error during monitoring authentication: {e}")
            return None

    # ===========================================
    # Quota Check Methods (Phase 2)
    # ===========================================

    def _should_check_quota(self) -> bool:
        """Check if quota checking is configured and enabled."""
        quota_api_endpoint = self.config.get("quota_api_endpoint")
        return bool(quota_api_endpoint)

    def _should_recheck_quota(self) -> bool:
        """Check if quota should be re-verified based on configured interval.

        Returns True if:
        - Quota checking is enabled AND
        - Either interval is 0 (always check) OR
        - Last quota check was more than interval minutes ago
        """
        if not self._should_check_quota():
            return False

        interval_minutes = self.config.get("quota_check_interval", 30)
        if interval_minutes == 0:
            return True  # Always check

        last_check = self._get_last_quota_check_time()
        if not last_check:
            return True  # Never checked

        elapsed = (datetime.now(timezone.utc) - last_check).total_seconds() / 60
        self._debug_print(f"Quota check: {elapsed:.1f} min since last check, interval={interval_minutes} min")
        return elapsed >= interval_minutes

    def _get_last_quota_check_time(self) -> datetime | None:
        """Get timestamp of last quota check from storage."""
        try:
            if self.credential_storage == "keyring":
                timestamp_str = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-quota-check")
                if timestamp_str:
                    return datetime.fromisoformat(timestamp_str)
            else:
                session_dir = Path.home() / ".claude-code-session"
                timestamp_file = session_dir / f"{self.profile}-quota-check.json"
                if timestamp_file.exists():
                    with open(timestamp_file) as f:
                        data = json.load(f)
                        return datetime.fromisoformat(data["last_check"])
            return None
        except Exception as e:
            self._debug_print(f"Could not read quota check timestamp: {e}")
            return None

    def _save_quota_check_timestamp(self):
        """Save current time as last quota check timestamp."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            if self.credential_storage == "keyring":
                keyring.set_password("claude-code-with-bedrock", f"{self.profile}-quota-check", now)
            else:
                session_dir = Path.home() / ".claude-code-session"
                session_dir.mkdir(parents=True, exist_ok=True)
                timestamp_file = session_dir / f"{self.profile}-quota-check.json"
                with open(timestamp_file, "w") as f:
                    json.dump({"last_check": now}, f)
                timestamp_file.chmod(0o600)
            self._debug_print("Saved quota check timestamp")
        except Exception as e:
            self._debug_print(f"Could not save quota check timestamp: {e}")

    def _get_cached_token_claims(self) -> dict | None:
        """Get token claims from cached monitoring token for quota re-check."""
        try:
            if self.credential_storage == "keyring":
                token_json = keyring.get_password("claude-code-with-bedrock", f"{self.profile}-monitoring")
                if token_json:
                    token_data = json.loads(token_json)
                    return {"email": token_data.get("email", "")}
            else:
                session_dir = Path.home() / ".claude-code-session"
                token_file = session_dir / f"{self.profile}-monitoring.json"
                if token_file.exists():
                    with open(token_file) as f:
                        token_data = json.load(f)
                        return {"email": token_data.get("email", "")}
            return None
        except Exception:
            return None

    def _extract_groups(self, token_claims: dict) -> list:
        """Extract group memberships from JWT token claims.

        Looks for groups in multiple claim formats:
        - groups: Standard groups claim
        - cognito:groups: Amazon Cognito groups
        - custom:department: Custom department claim (treated as a group)
        """
        groups = []

        # Standard groups claim
        if "groups" in token_claims:
            claim_groups = token_claims["groups"]
            if isinstance(claim_groups, list):
                groups.extend(claim_groups)
            elif isinstance(claim_groups, str):
                groups.append(claim_groups)

        # Cognito groups
        if "cognito:groups" in token_claims:
            claim_groups = token_claims["cognito:groups"]
            if isinstance(claim_groups, list):
                groups.extend(claim_groups)
            elif isinstance(claim_groups, str):
                groups.append(claim_groups)

        # Custom department (treated as a group for policy matching)
        if "custom:department" in token_claims:
            department = token_claims["custom:department"]
            if department:
                groups.append(f"department:{department}")

        return list(set(groups))  # Remove duplicates

    def _check_quota(self, token_claims: dict, id_token: str) -> dict:
        """Check user quota via the quota check API.

        Args:
            token_claims: JWT token claims containing user info (for logging/fallback)
            id_token: Raw JWT token to send in Authorization header for API Gateway validation

        Returns:
            Quota check result dict with 'allowed' key
        """
        quota_api_endpoint = self.config.get("quota_api_endpoint")
        fail_mode = self.config.get("quota_fail_mode", "open")
        timeout = self.config.get("quota_check_timeout", 5)

        email = token_claims.get("email")
        if not email:
            self._debug_print("No email in token claims, skipping quota check")
            return {"allowed": True, "reason": "no_email"}

        groups = self._extract_groups(token_claims)
        self._debug_print(f"Checking quota for {email} (groups: {groups})")

        try:
            # Send JWT token in Authorization header for API Gateway JWT Authorizer validation
            # The API extracts email/groups from validated JWT claims, not query params
            response = requests.get(
                f"{quota_api_endpoint}/check",
                headers={"Authorization": f"Bearer {id_token}"},
                timeout=timeout
            )

            if response.status_code == 200:
                result = response.json()
                self._debug_print(f"Quota check result: allowed={result.get('allowed')}, reason={result.get('reason')}")
                return result
            elif response.status_code == 401:
                # JWT validation failed at API Gateway
                self._debug_print("Quota check JWT validation failed (401)")
                if fail_mode == "closed":
                    return {
                        "allowed": False,
                        "reason": "jwt_invalid",
                        "message": "Quota check authentication failed - invalid or expired token"
                    }
                return {"allowed": True, "reason": "jwt_invalid"}
            else:
                self._debug_print(f"Quota check returned status {response.status_code}")
                # Fail according to configured mode
                if fail_mode == "closed":
                    return {
                        "allowed": False,
                        "reason": "api_error",
                        "message": f"Quota check failed with status {response.status_code}"
                    }
                return {"allowed": True, "reason": "api_error"}

        except requests.exceptions.Timeout:
            self._debug_print("Quota check timed out")
            if fail_mode == "closed":
                return {
                    "allowed": False,
                    "reason": "timeout",
                    "message": "Quota check timed out. Please try again."
                }
            return {"allowed": True, "reason": "timeout"}

        except requests.exceptions.RequestException as e:
            self._debug_print(f"Quota check request failed: {e}")
            if fail_mode == "closed":
                return {
                    "allowed": False,
                    "reason": "connection_error",
                    "message": f"Could not connect to quota service: {e}"
                }
            return {"allowed": True, "reason": "connection_error"}

        except Exception as e:
            self._debug_print(f"Quota check error: {e}")
            if fail_mode == "closed":
                return {
                    "allowed": False,
                    "reason": "error",
                    "message": f"Quota check failed: {e}"
                }
            return {"allowed": True, "reason": "error"}

    def _handle_quota_blocked(self, quota_result: dict) -> int:
        """Handle blocked quota by displaying user-friendly message.

        Args:
            quota_result: Result from quota check API

        Returns:
            Exit code (always 1 for blocked)
        """
        reason = quota_result.get("reason", "unknown")
        message = quota_result.get("message", "Access blocked due to quota limits")
        usage = quota_result.get("usage", {})
        policy = quota_result.get("policy", {})

        print("\n" + "=" * 60, file=sys.stderr)
        print("ACCESS BLOCKED - QUOTA EXCEEDED", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        print(f"\n{message}\n", file=sys.stderr)

        if usage:
            print("Current Usage:", file=sys.stderr)
            if "monthly_tokens" in usage and "monthly_limit" in usage:
                print(f"  Monthly: {usage['monthly_tokens']:,} / {usage['monthly_limit']:,} tokens ({usage.get('monthly_percent', 0):.1f}%)", file=sys.stderr)
            if "daily_tokens" in usage and "daily_limit" in usage:
                print(f"  Daily: {usage['daily_tokens']:,} / {usage['daily_limit']:,} tokens ({usage.get('daily_percent', 0):.1f}%)", file=sys.stderr)

        if policy:
            print(f"\nPolicy: {policy.get('type', 'unknown')}:{policy.get('identifier', 'unknown')}", file=sys.stderr)

        print("\nTo request an unblock, contact your administrator.", file=sys.stderr)
        print("=" * 60 + "\n", file=sys.stderr)

        # Show browser notification
        self._show_quota_browser_notification(quota_result, is_blocked=True)

        return 1

    def _show_quota_browser_notification(self, quota_result: dict, is_blocked: bool = False):
        """Show quota status in browser with visual progress bars.

        Args:
            quota_result: Result from quota check API
            is_blocked: Whether access is blocked (vs warning)
        """
        try:
            usage = quota_result.get("usage", {})
            message = quota_result.get("message", "")

            # Calculate percentages
            monthly_percent = usage.get("monthly_percent", 0)
            daily_percent = usage.get("daily_percent", 0)

            # Format numbers for display
            monthly_tokens = usage.get("monthly_tokens", 0)
            monthly_limit = usage.get("monthly_limit", 0)
            daily_tokens = usage.get("daily_tokens", 0)
            daily_limit = usage.get("daily_limit", 0)

            def format_tokens(n):
                if n >= 1_000_000_000:
                    return f"{n/1_000_000_000:.1f}B"
                elif n >= 1_000_000:
                    return f"{n/1_000_000:.1f}M"
                elif n >= 1_000:
                    return f"{n/1_000:.1f}K"
                return str(int(n))

            # Determine status styling
            if is_blocked:
                status_emoji = "🚫"
                status_text = "Access Blocked"
                status_color = "#dc3545"
                header_bg = "#f8d7da"
            else:
                status_emoji = "⚠️"
                status_text = "Quota Warning"
                status_color = "#ffc107"
                header_bg = "#fff3cd"

            # Progress bar color based on percentage
            def bar_color(pct):
                if pct >= 100:
                    return "#dc3545"  # Red
                elif pct >= 90:
                    return "#fd7e14"  # Orange
                elif pct >= 80:
                    return "#ffc107"  # Yellow
                return "#28a745"  # Green

            monthly_bar_color = bar_color(monthly_percent)
            daily_bar_color = bar_color(daily_percent) if daily_limit else "#6c757d"

            html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Quota Status - Claude Code</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            margin: 0;
            padding: 40px;
            background: #f5f5f5;
            min-height: 100vh;
            box-sizing: border-box;
        }}
        .container {{
            max-width: 500px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background: {header_bg};
            padding: 30px;
            text-align: center;
            border-bottom: 1px solid rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0;
            color: {status_color};
            font-size: 28px;
        }}
        .content {{
            padding: 30px;
        }}
        .usage-section {{
            margin-bottom: 25px;
        }}
        .usage-label {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 14px;
            color: #666;
        }}
        .usage-value {{
            font-weight: 600;
            color: #333;
        }}
        .progress-bar {{
            height: 24px;
            background: #e9ecef;
            border-radius: 12px;
            overflow: hidden;
        }}
        .progress-fill {{
            height: 100%;
            border-radius: 12px;
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 10px;
            font-size: 12px;
            font-weight: 600;
            color: white;
            box-sizing: border-box;
        }}
        .message {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            font-size: 14px;
            color: #666;
            line-height: 1.5;
            margin-bottom: 20px;
        }}
        .footer {{
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            font-size: 13px;
            color: #666;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{status_emoji} {status_text}</h1>
        </div>
        <div class="content">
            <div class="usage-section">
                <div class="usage-label">
                    <span>Monthly Usage</span>
                    <span class="usage-value">{format_tokens(monthly_tokens)} / {format_tokens(monthly_limit)} ({monthly_percent:.1f}%)</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {min(monthly_percent, 100)}%; background: {monthly_bar_color};">
                        {monthly_percent:.0f}%
                    </div>
                </div>
            </div>
            {"" if not daily_limit else f'''
            <div class="usage-section">
                <div class="usage-label">
                    <span>Daily Usage</span>
                    <span class="usage-value">{format_tokens(daily_tokens)} / {format_tokens(daily_limit)} ({daily_percent:.1f}%)</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {min(daily_percent, 100)}%; background: {daily_bar_color};">
                        {daily_percent:.0f}%
                    </div>
                </div>
            </div>
            '''}
            <div class="message">
                {html_module.escape(message) if message else ("Your access has been blocked due to quota limits." if is_blocked else "You're approaching your quota limit.")}
                {" Contact your administrator for assistance." if is_blocked else ""}
            </div>
        </div>
        <div class="footer">
            Return to your terminal to continue.
        </div>
    </div>
</body>
</html>"""

            # Start a brief HTTP server to serve the page
            parent = self
            page_served = {"done": False}

            class QuotaPageHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(html.encode())
                    page_served["done"] = True

                def log_message(self, format, *args):
                    pass  # Suppress logs

            # Use a different port for quota page (8401) to avoid conflict with auth
            quota_port = self.redirect_port + 1
            try:
                server = HTTPServer(("127.0.0.1", quota_port), QuotaPageHandler)
                server.timeout = 5  # 5 second timeout

                # Open browser
                webbrowser.open(f"http://localhost:{quota_port}/quota-status")

                # Wait for page to be served (or timeout)
                while not page_served["done"]:
                    server.handle_request()

                server.server_close()
            except OSError:
                # Port in use or other error - skip browser notification
                self._debug_print(f"Could not start quota notification server on port {quota_port}")

        except Exception as e:
            self._debug_print(f"Failed to show browser notification: {e}")

    def _handle_quota_warning(self, quota_result: dict):
        """Handle quota warning by showing notification without blocking.

        Args:
            quota_result: Result from quota check API
        """
        usage = quota_result.get("usage", {})
        monthly_percent = usage.get("monthly_percent", 0)
        daily_percent = usage.get("daily_percent", 0)

        # Only show warning for significant thresholds (80%+)
        if monthly_percent < 80 and daily_percent < 80:
            return

        # Show terminal warning
        print("\n" + "=" * 60, file=sys.stderr)
        print("QUOTA WARNING", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

        if usage:
            if "monthly_tokens" in usage and "monthly_limit" in usage:
                print(f"  Monthly: {usage['monthly_tokens']:,} / {usage['monthly_limit']:,} tokens ({monthly_percent:.1f}%)", file=sys.stderr)
            if "daily_tokens" in usage and "daily_limit" in usage:
                print(f"  Daily: {usage['daily_tokens']:,} / {usage['daily_limit']:,} tokens ({daily_percent:.1f}%)", file=sys.stderr)

        print("=" * 60 + "\n", file=sys.stderr)

        # Show browser notification
        self._show_quota_browser_notification(quota_result, is_blocked=False)

    # ===========================================
    # End Quota Check Methods
    # ===========================================

    def run(self):
        """Main execution flow"""
        try:
            # Check cache first
            cached = self.get_cached_credentials()
            if cached:
                # Periodic quota re-check even with cached credentials
                if self._should_recheck_quota():
                    self._debug_print("Performing periodic quota re-check...")
                    id_token = self.get_monitoring_token()
                    token_claims = self._get_cached_token_claims()
                    if id_token and token_claims:
                        quota_result = self._check_quota(token_claims, id_token)
                        self._save_quota_check_timestamp()
                        if not quota_result.get("allowed", True):
                            return self._handle_quota_blocked(quota_result)
                        else:
                            self._handle_quota_warning(quota_result)
                    else:
                        self._debug_print("No cached token for quota re-check, skipping")

                # Output cached credentials (intended behavior for AWS CLI)
                print(json.dumps(cached))  # noqa: S105
                return 0

            # Try to acquire port lock by testing if we can bind to it
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                test_socket.bind(("127.0.0.1", self.redirect_port))
                test_socket.close()
                # We got the port, we can proceed with authentication
                self._debug_print("Port available, proceeding with authentication")
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    # Port in use, another auth is in progress
                    self._debug_print("Another authentication is in progress, waiting...")
                    test_socket.close()

                    # Wait for the other process to complete
                    cached = self._wait_for_auth_completion()
                    if cached:
                        print(json.dumps(cached))
                        return 0
                    else:
                        # Only print error to stderr for actual failures
                        self._debug_print("Authentication timeout or failed in another process")
                        return 1
                else:
                    test_socket.close()
                    raise

            # Check cache again (another process might have just finished)
            cached = self.get_cached_credentials()
            if cached:
                # Output cached credentials (intended behavior for AWS CLI)
                print(json.dumps(cached))  # noqa: S105
                return 0

            # Authenticate with OIDC provider
            self._debug_print(f"Authenticating with {self.provider_config['name']} for profile '{self.profile}'...")
            id_token, token_claims = self.authenticate_oidc()

            # Check quota before issuing credentials (if configured)
            if self._should_check_quota():
                self._debug_print("Checking quota before credential issuance...")
                quota_result = self._check_quota(token_claims, id_token)
                self._save_quota_check_timestamp()  # Track when quota was checked
                if not quota_result.get("allowed", True):
                    return self._handle_quota_blocked(quota_result)
                else:
                    # Check for warning threshold (allowed but high usage)
                    self._handle_quota_warning(quota_result)

            # Get AWS credentials
            self._debug_print("Exchanging token for AWS credentials...")
            credentials = self.get_aws_credentials(id_token, token_claims)

            # Cache credentials
            self.save_credentials(credentials)

            # Save monitoring token (non-blocking, failures don't affect AWS auth)
            self.save_monitoring_token(id_token, token_claims)

            # Output credentials
            # CodeQL: This is not a security issue - this is an AWS credential provider
            # that must output credentials to stdout for AWS CLI to consume them.
            # This is the intended behavior and required for the tool to function.
            # nosec - Not logging, but outputting credentials as designed
            print(json.dumps(credentials))  # noqa: S105
            return 0

        except KeyboardInterrupt:
            # User cancelled - no output needed
            return 1
        except Exception as e:
            error_msg = str(e)
            # Only print actual errors to stderr
            if "timeout" not in error_msg.lower():
                print(f"Error: {error_msg}", file=sys.stderr)
            else:
                self._debug_print(f"Error: {error_msg}")

            # Provide specific guidance for common errors
            if "NotAuthorizedException" in error_msg and "Token is not from a supported provider" in error_msg:
                print("\nAuthentication failed: Token provider mismatch", file=sys.stderr)
                print("Identity pool expects tokens from a specific provider configuration.", file=sys.stderr)
                print("Please verify your Cognito Identity Pool is configured correctly.", file=sys.stderr)
            elif "timeout" in error_msg.lower():
                self._debug_print("\nAuthentication timed out. Possible causes:")
                self._debug_print("- Browser did not complete authentication")
                self._debug_print("- Network connectivity issues")
                self._debug_print("- Callback URL was not accessible on localhost:8400")
            elif "cognito_user_pool_id is required" in error_msg:
                print("\nConfiguration error: Missing Cognito User Pool ID", file=sys.stderr)
                print("Please run 'poetry run ccwb init' to reconfigure.", file=sys.stderr)

            return 1


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="AWS credential provider for OIDC + Cognito Identity Pool")
    # Check environment variable first, then use default
    default_profile = os.getenv("CCWB_PROFILE", "ClaudeCode")
    parser.add_argument("--profile", "-p", default=default_profile, help="Configuration profile to use")
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--get-monitoring-token", action="store_true", help="Get cached monitoring token instead of AWS credentials"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear cached credentials and force re-authentication"
    )
    parser.add_argument(
        "--check-expiration",
        action="store_true",
        help="Check if credentials need refresh (exit 0 if valid, 1 if expired)",
    )
    parser.add_argument(
        "--refresh-if-needed",
        action="store_true",
        help="Refresh credentials if expired (for cron jobs with session storage)",
    )

    args = parser.parse_args()

    auth = MultiProviderAuth(profile=args.profile)

    # Handle cache clearing request
    if args.clear_cache:
        cleared = auth.clear_cached_credentials()
        if cleared:
            print(f"Cleared cached credentials for profile '{args.profile}':", file=sys.stderr)
            for item in cleared:
                print(f"  • {item}", file=sys.stderr)
        else:
            print(f"No cached credentials found for profile '{args.profile}'", file=sys.stderr)
        sys.exit(0)

    # Handle monitoring token request
    if args.get_monitoring_token:
        token = auth.get_monitoring_token()
        if token:
            print(token)
            sys.exit(0)
        else:
            # No cached token, trigger authentication to get one
            auth._debug_print("No valid monitoring token found, triggering authentication...")
            # Use the new monitoring-specific authentication method
            token = auth.authenticate_for_monitoring()
            if token:
                print(token)
                sys.exit(0)
            else:
                # Authentication failed or was cancelled
                # Return failure exit code so OTEL helper knows auth failed
                # This prevents OTEL helper from using default/unknown values
                sys.exit(1)

    # Handle check-expiration request
    if args.check_expiration:
        is_expired = auth.check_credentials_file_expiration(args.profile)
        if is_expired:
            print(f"Credentials expired or missing for profile '{args.profile}'", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Credentials valid for profile '{args.profile}'", file=sys.stderr)
            sys.exit(0)

    # Handle refresh-if-needed request (for cron jobs with session storage)
    if args.refresh_if_needed:
        # Only works with session storage mode (credentials file)
        if auth.credential_storage != "session":
            print("Error: --refresh-if-needed only works with session storage mode", file=sys.stderr)
            sys.exit(1)

        is_expired = auth.check_credentials_file_expiration(args.profile)
        if not is_expired:
            # Credentials still valid, nothing to do
            auth._debug_print(f"Credentials still valid for profile '{args.profile}', no refresh needed")
            sys.exit(0)
        # Credentials expired, fall through to normal auth flow

    # Normal AWS credential flow (credential_process mode)
    # For session storage, this automatically uses ~/.aws/credentials
    sys.exit(auth.run())


if __name__ == "__main__":
    main()
