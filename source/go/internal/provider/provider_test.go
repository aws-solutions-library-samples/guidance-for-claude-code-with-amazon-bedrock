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

func TestConfigFor_OktaOrgASWhenNoCASSet(t *testing.T) {
	// Empty okta_auth_server_id means "upstream shape, no CAS" -- endpoints
	// hit the Okta Org Authorization Server at /oauth2/v1/... and produce
	// JWTs with iss=https://<domain>, matching the bare OIDC provider URL
	// the CFN template registers when isolation is off.
	want := Configs["okta"]
	got := ConfigFor("okta", "")
	if got.AuthorizeEndpoint != want.AuthorizeEndpoint || got.TokenEndpoint != want.TokenEndpoint {
		t.Errorf("ConfigFor(okta, \"\"): endpoints diverged from Org AS default\nauthorize = %q\ntoken     = %q",
			got.AuthorizeEndpoint, got.TokenEndpoint)
	}
	if want.AuthorizeEndpoint != "/oauth2/v1/authorize" {
		t.Errorf("Org AS authorize endpoint drift: %q", want.AuthorizeEndpoint)
	}
}

func TestConfigFor_OktaDefaultCAS(t *testing.T) {
	// Explicit "default" means "use the pre-provisioned default CAS" --
	// endpoints become /oauth2/default/v1/... so JWTs carry
	// iss=https://<domain>/oauth2/default. This is the shape required by
	// zone isolation / cost attribution and matches the CFN OIDC provider
	// URL when EnforceProjectIsolation=true.
	got := ConfigFor("okta", "default")
	if got.AuthorizeEndpoint != "/oauth2/default/v1/authorize" {
		t.Errorf("authorize endpoint = %q, want /oauth2/default/v1/authorize", got.AuthorizeEndpoint)
	}
	if got.TokenEndpoint != "/oauth2/default/v1/token" {
		t.Errorf("token endpoint = %q, want /oauth2/default/v1/token", got.TokenEndpoint)
	}
}

func TestConfigFor_OktaCustomCAS(t *testing.T) {
	got := ConfigFor("okta", "myCAS")
	if got.AuthorizeEndpoint != "/oauth2/myCAS/v1/authorize" {
		t.Errorf("authorize endpoint = %q, want /oauth2/myCAS/v1/authorize", got.AuthorizeEndpoint)
	}
	if got.TokenEndpoint != "/oauth2/myCAS/v1/token" {
		t.Errorf("token endpoint = %q, want /oauth2/myCAS/v1/token", got.TokenEndpoint)
	}
	// Non-path fields are copied verbatim.
	if got.Scopes != Configs["okta"].Scopes {
		t.Errorf("scopes changed unexpectedly: %q", got.Scopes)
	}
}

func TestConfigFor_OktaCASWhitespaceTrimmed(t *testing.T) {
	// Trailing whitespace in the config shouldn't produce a different
	// endpoint than the bare id.
	got := ConfigFor("okta", "  myCAS  ")
	if got.AuthorizeEndpoint != "/oauth2/myCAS/v1/authorize" {
		t.Errorf("whitespace not trimmed: %q", got.AuthorizeEndpoint)
	}
}

func TestConfigFor_NonOktaIgnoresCASID(t *testing.T) {
	// Auth0 / Azure / Cognito have no CAS concept; the CAS id must be
	// ignored (NOT substituted into their endpoints, which don't contain
	// /oauth2/default/ anyway). Regression test against accidentally
	// generic substitution.
	for _, providerType := range []string{"auth0", "azure", "cognito"} {
		want := Configs[providerType]
		got := ConfigFor(providerType, "notUsed")
		if got != want {
			t.Errorf("ConfigFor(%q, ...) = %+v, want %+v (CAS id must be ignored for non-Okta)", providerType, got, want)
		}
	}
}

func TestConfigFor_UnknownProvider(t *testing.T) {
	got := ConfigFor("saml", "default")
	if got.Name != "" || got.AuthorizeEndpoint != "" {
		t.Errorf("ConfigFor(unknown): expected zero-value Config, got %+v", got)
	}
}

func TestConfigFor_DoesNotMutateConfigsMap(t *testing.T) {
	// ConfigFor returns a value copy; the package-level map must remain
	// pristine so concurrent calls with different CAS ids don't race.
	before := Configs["okta"].AuthorizeEndpoint
	_ = ConfigFor("okta", "somethingElse")
	after := Configs["okta"].AuthorizeEndpoint
	if before != after {
		t.Errorf("Configs[okta] was mutated: before=%q after=%q", before, after)
	}
}

func TestIsKnown_Generic(t *testing.T) {
	if !IsKnown("generic") {
		t.Error("IsKnown(\"generic\") = false, want true")
	}
}

func TestConfigFor_GenericProvider(t *testing.T) {
	got := ConfigFor("generic", "")
	if got.Name != "Generic OIDC" {
		t.Errorf("ConfigFor(generic).Name = %q, want \"Generic OIDC\"", got.Name)
	}
	if got.Scopes != "openid profile email" {
		t.Errorf("ConfigFor(generic).Scopes = %q, want \"openid profile email\"", got.Scopes)
	}
	if got.ResponseType != "code" {
		t.Errorf("ConfigFor(generic).ResponseType = %q, want \"code\"", got.ResponseType)
	}
}

func TestDetect_CyberArk(t *testing.T) {
	// CyberArk Identity domains should not match any named provider
	domains := []string{
		"abc1234.id.cyberark.cloud",
		"company.my.idaptive.app",
		"auth.cyberark.com",
	}
	for _, d := range domains {
		got := Detect(d)
		if got != "oidc" {
			t.Errorf("Detect(%q) = %q, want \"oidc\" (should not match a named provider)", d, got)
		}
	}
}
