# ABOUTME: Provides secure URL validation for authentication providers
# ABOUTME: Prevents URL injection attacks by using proper hostname parsing

from urllib.parse import urlparse


def detect_provider_type_secure(domain: str) -> str:
    """
    Securely detect the authentication provider type from a domain.

    Uses proper URL parsing to prevent security vulnerabilities like:
    - Path injection (evil.com/okta.com)
    - Subdomain bypass (okta.com.evil.com)
    - Prefix attacks (not-okta.com)

    Args:
        domain: The provider domain URL or hostname

    Returns:
        Provider type: "okta", "auth0", "azure", "cognito", or "oidc"
    """
    if not domain:
        return "oidc"

    # Handle both full URLs and domain-only inputs
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"

    try:
        parsed = urlparse(domain)
        hostname = parsed.hostname

        if not hostname:
            return "oidc"

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
            return "cognito"
        else:
            return "oidc"
    except Exception:
        # Default to generic OIDC for any parsing errors
        return "oidc"
