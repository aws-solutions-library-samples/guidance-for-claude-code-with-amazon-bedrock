package provider

import "testing"

func TestDetect(t *testing.T) {
	tests := []struct {
		domain   string
		expected string
	}{
		// Okta
		{"dev-12345.okta.com", "okta"},
		{"myorg.okta.com", "okta"},
		{"myorg.oktapreview.com", "okta"},
		{"myorg.okta-emea.com", "okta"},
		{"https://dev-12345.okta.com", "okta"},
		{"https://myorg.oktapreview.com/oauth2/v1/authorize", "okta"},

		// Auth0
		{"myorg.auth0.com", "auth0"},
		{"https://myorg.auth0.com", "auth0"},

		// Azure
		{"login.microsoftonline.com", "azure"},
		{"login.microsoftonline.com/tenantid", "azure"},
		{"sts.windows.net", "azure"},
		{"https://login.microsoftonline.com/tenant-id/v2.0", "azure"},

		// Cognito
		{"myapp.auth.us-east-1.amazoncognito.com", "cognito"},
		{"cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123", "cognito"},
		{"cognito-idp.eu-west-1.amazonaws.com", "cognito"},

		// Unknown
		{"example.com", "oidc"},
		{"", "oidc"},
		{"some-random-domain.io", "oidc"},

		// Security: bypass attempts
		{"evil.com/okta.com", "oidc"},           // path injection
		{"okta.com.evil.com", "oidc"},            // subdomain spoof
		{"not-okta.com", "oidc"},                 // prefix attack
		{"evil.com?host=okta.com", "oidc"},       // query param injection
	}

	for _, tt := range tests {
		t.Run(tt.domain, func(t *testing.T) {
			result := Detect(tt.domain)
			if result != tt.expected {
				t.Errorf("Detect(%q) = %q, want %q", tt.domain, result, tt.expected)
			}
		})
	}
}
