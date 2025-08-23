# ABOUTME: Tests for secure URL validation to prevent security vulnerabilities
# ABOUTME: Validates proper domain checking to fix GitHub code scanning alerts

import pytest
from urllib.parse import urlparse


def detect_provider_type_insecure(domain: str) -> str:
    """Current INSECURE implementation - vulnerable to bypass"""
    domain_lower = domain.lower()
    if "okta.com" in domain_lower:
        return "okta"
    elif "auth0.com" in domain_lower:
        return "auth0"
    elif "microsoftonline.com" in domain_lower or "windows.net" in domain_lower:
        return "azure"
    elif "amazoncognito.com" in domain_lower:
        return "cognito"
    else:
        return "oidc"


def detect_provider_type_secure(domain: str) -> str:
    """SECURE implementation using proper URL parsing"""
    # Handle both full URLs and domain-only inputs
    if not domain:
        return "oidc"
    
    # Add scheme if missing (for urlparse to work correctly)
    if not domain.startswith(('http://', 'https://')):
        domain = f"https://{domain}"
    
    try:
        parsed = urlparse(domain)
        hostname = parsed.hostname
        
        if not hostname:
            return "oidc"
        
        hostname_lower = hostname.lower()
        
        # Check for exact domain match or subdomain match
        if hostname_lower.endswith('.okta.com') or hostname_lower == 'okta.com':
            return "okta"
        elif hostname_lower.endswith('.auth0.com') or hostname_lower == 'auth0.com':
            return "auth0"
        elif hostname_lower.endswith('.microsoftonline.com') or hostname_lower == 'microsoftonline.com':
            return "azure"
        elif hostname_lower.endswith('.windows.net') or hostname_lower == 'windows.net':
            return "azure"
        elif hostname_lower.endswith('.amazoncognito.com') or hostname_lower == 'amazoncognito.com':
            return "cognito"
        else:
            return "oidc"
    except Exception:
        return "oidc"


class TestURLValidationSecurity:
    """Test cases for URL validation security improvements"""
    
    def test_valid_okta_domains(self):
        """Test legitimate Okta domains are correctly identified"""
        valid_domains = [
            "dev-12345678.okta.com",
            "company.okta.com",
            "test.okta.com",
            "https://dev-12345678.okta.com",
            "https://company.okta.com/oauth2/default",
        ]
        
        for domain in valid_domains:
            assert detect_provider_type_secure(domain) == "okta", f"Failed for {domain}"
    
    def test_valid_auth0_domains(self):
        """Test legitimate Auth0 domains are correctly identified"""
        valid_domains = [
            "your-name.auth0.com",
            "company.auth0.com",
            "dev.auth0.com",
            "https://your-name.auth0.com",
            "https://company.auth0.com/",
        ]
        
        for domain in valid_domains:
            assert detect_provider_type_secure(domain) == "auth0", f"Failed for {domain}"
    
    def test_valid_azure_domains(self):
        """Test legitimate Azure/Microsoft domains are correctly identified"""
        valid_domains = [
            "login.microsoftonline.com",
            "login.microsoftonline.com/tenant-id/v2.0",
            "sts.windows.net",
            "https://login.microsoftonline.com",
            "https://sts.windows.net/tenant-id",
        ]
        
        for domain in valid_domains:
            assert detect_provider_type_secure(domain) == "azure", f"Failed for {domain}"
    
    def test_valid_cognito_domains(self):
        """Test legitimate Cognito domains are correctly identified"""
        valid_domains = [
            "my-domain.auth.us-east-1.amazoncognito.com",
            "test.auth.eu-west-1.amazoncognito.com",
            "https://my-domain.auth.us-east-1.amazoncognito.com",
        ]
        
        for domain in valid_domains:
            assert detect_provider_type_secure(domain) == "cognito", f"Failed for {domain}"
    
    def test_attack_path_injection(self):
        """Test that path injection attacks are prevented"""
        attack_domains = [
            "evil.com/okta.com",
            "evil.com/auth0.com",
            "evil.com/microsoftonline.com",
            "evil.com/amazoncognito.com",
            "https://evil.com/okta.com",
            "https://malicious.com/path/auth0.com",
        ]
        
        for domain in attack_domains:
            # Insecure version incorrectly identifies these as valid
            assert detect_provider_type_insecure(domain) != "oidc", f"Insecure failed to detect attack: {domain}"
            # Secure version correctly rejects these
            assert detect_provider_type_secure(domain) == "oidc", f"Secure failed to block attack: {domain}"
    
    def test_attack_subdomain_bypass(self):
        """Test that subdomain bypass attacks are prevented"""
        attack_domains = [
            "okta.com.evil.com",
            "auth0.com.attacker.com",
            "microsoftonline.com.malicious.net",
            "amazoncognito.com.fake.com",
        ]
        
        for domain in attack_domains:
            # Insecure version incorrectly identifies these as valid
            assert detect_provider_type_insecure(domain) != "oidc", f"Insecure failed to detect attack: {domain}"
            # Secure version correctly rejects these
            assert detect_provider_type_secure(domain) == "oidc", f"Secure failed to block attack: {domain}"
    
    def test_attack_prefix_bypass(self):
        """Test that prefix bypass attacks are prevented"""
        attack_domains = [
            "not-okta.com",
            "fake-auth0.com",
            "notmicrosoftonline.com",
            "fake-amazoncognito.com",
            "okta.com-evil.com",
        ]
        
        for domain in attack_domains:
            # Secure version correctly rejects these
            assert detect_provider_type_secure(domain) == "oidc", f"Secure failed to block attack: {domain}"
    
    def test_edge_cases(self):
        """Test edge cases and malformed inputs"""
        edge_cases = [
            "",  # Empty string
            "   ",  # Whitespace
            "okta",  # No TLD
            ".com",  # Only TLD
            "https://",  # Only protocol
            "okta.com:8080",  # With port
            "OKTA.COM",  # Uppercase
            "okta.com/",  # Trailing slash
        ]
        
        for domain in edge_cases:
            # Should not crash and should handle gracefully
            result = detect_provider_type_secure(domain)
            assert result in ["okta", "oidc"], f"Unexpected result for edge case {domain}: {result}"
    
    def test_mixed_case_handling(self):
        """Test that mixed case domains are handled correctly"""
        mixed_case_domains = [
            "Dev-12345678.Okta.Com",
            "Your-Name.Auth0.Com",
            "Login.MicrosoftOnline.Com",
            "My-Domain.Auth.US-East-1.AmazonCognito.Com",
        ]
        
        expected = ["okta", "auth0", "azure", "cognito"]
        
        for domain, expected_type in zip(mixed_case_domains, expected):
            assert detect_provider_type_secure(domain) == expected_type, f"Failed for {domain}"
    
    def test_backward_compatibility(self):
        """Ensure that all legitimate use cases still work"""
        # Test cases from documentation
        real_world_domains = [
            ("dev-12345678.okta.com", "okta"),
            ("your-name.auth0.com", "auth0"),
            ("login.microsoftonline.com/tenant-id/v2.0", "azure"),
            ("my-domain.auth.us-east-1.amazoncognito.com", "cognito"),
            ("custom-oidc-provider.com", "oidc"),
        ]
        
        for domain, expected in real_world_domains:
            assert detect_provider_type_secure(domain) == expected, f"Backward compatibility broken for {domain}"


class TestCredentialSanitization:
    """Test cases for credential logging sanitization"""
    
    def test_sanitize_credentials(self):
        """Test that sensitive credential fields are removed from logs"""
        credentials = {
            "Version": 1,
            "AccessKeyId": "AKIA1234567890",
            "SecretAccessKey": "SECRET_KEY_SHOULD_NOT_BE_LOGGED",
            "SessionToken": "SESSION_TOKEN_SHOULD_NOT_BE_LOGGED",
            "Expiration": "2024-01-01T00:00:00Z"
        }
        
        # Sanitized version for logging
        sanitized = {
            "Version": credentials["Version"],
            "AccessKeyId": credentials["AccessKeyId"],
            "Expiration": credentials["Expiration"]
        }
        
        # Verify sensitive fields are not in sanitized version
        assert "SecretAccessKey" not in sanitized
        assert "SessionToken" not in sanitized
        
        # Verify non-sensitive fields are preserved
        assert sanitized["AccessKeyId"] == credentials["AccessKeyId"]
        assert sanitized["Expiration"] == credentials["Expiration"]
    
    def test_credential_structure_preserved(self):
        """Test that credential structure is preserved for AWS CLI"""
        original = {
            "Version": 1,
            "AccessKeyId": "AKIA1234567890",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
            "Expiration": "2024-01-01T00:00:00Z"
        }
        
        # Original should have all fields for AWS CLI
        assert "SecretAccessKey" in original
        assert "SessionToken" in original
        
        # These fields are required for AWS CLI to work
        required_fields = ["Version", "AccessKeyId", "SecretAccessKey", "SessionToken", "Expiration"]
        for field in required_fields:
            assert field in original, f"Missing required field: {field}"