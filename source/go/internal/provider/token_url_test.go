package provider

import "testing"

// TestTokenEndpointURL_AzureNoDoubledVersion is the regression guard for the
// Azure refresh_token 404. Azure's provider_domain is stored WITH a trailing
// "/v2.0" while its token endpoint is "/oauth2/v2.0/token". A naive
// "https://" + domain + endpoint concatenation produced
// ".../v2.0/oauth2/v2.0/token" — a doubled version segment Azure rejects with
// HTTP 404. The browser auth flow stripped the suffix but the refresh path did
// not, so silent refresh (and therefore the quota recheck that depends on it)
// always 404'd for Azure and then wrongly cleared a valid refresh_token.
//
// TokenEndpointURL is the single shared builder both paths now use; this test
// pins its Azure output so the two can never drift apart again.
func TestTokenEndpointURL_AzureNoDoubledVersion(t *testing.T) {
	const tenant = "b39bc2da-e3c8-4f92-960e-4151a1ae16ad"
	domain := "login.microsoftonline.com/" + tenant + "/v2.0"

	got := TokenEndpointURL("azure", "", domain)
	want := "https://login.microsoftonline.com/" + tenant + "/oauth2/v2.0/token"
	if got != want {
		t.Errorf("TokenEndpointURL(azure) = %q, want %q", got, want)
	}
}

func TestTokenEndpointURL_PerProvider(t *testing.T) {
	tests := []struct {
		name         string
		providerType string
		oktaCASID    string
		domain       string
		want         string
	}{
		{
			name:         "okta org auth server",
			providerType: "okta",
			domain:       "myorg.okta.com",
			want:         "https://myorg.okta.com/oauth2/v1/token",
		},
		{
			name:         "okta custom auth server",
			providerType: "okta",
			oktaCASID:    "default",
			domain:       "myorg.okta.com",
			want:         "https://myorg.okta.com/oauth2/default/v1/token",
		},
		{
			name:         "auth0",
			providerType: "auth0",
			domain:       "myorg.auth0.com",
			want:         "https://myorg.auth0.com/oauth/token",
		},
		{
			name:         "cognito",
			providerType: "cognito",
			domain:       "myorg.auth.us-east-1.amazoncognito.com",
			want:         "https://myorg.auth.us-east-1.amazoncognito.com/oauth2/token",
		},
		{
			name:         "google uses absolute endpoint",
			providerType: "google",
			domain:       "accounts.google.com",
			want:         "https://oauth2.googleapis.com/token",
		},
		{
			name:         "unknown provider returns empty",
			providerType: "nope",
			domain:       "example.com",
			want:         "",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := TokenEndpointURL(tt.providerType, tt.oktaCASID, tt.domain); got != tt.want {
				t.Errorf("TokenEndpointURL(%q) = %q, want %q", tt.providerType, got, tt.want)
			}
		})
	}
}

func TestNormalizeDomain(t *testing.T) {
	tests := []struct {
		providerType string
		domain       string
		want         string
	}{
		{"azure", "login.microsoftonline.com/tenant/v2.0", "login.microsoftonline.com/tenant"},
		{"azure", "login.microsoftonline.com/tenant", "login.microsoftonline.com/tenant"}, // idempotent
		{"okta", "myorg.okta.com", "myorg.okta.com"},                                      // non-Azure untouched
		{"auth0", "myorg.auth0.com/v2.0", "myorg.auth0.com/v2.0"},                         // suffix only stripped for Azure
	}
	for _, tt := range tests {
		if got := NormalizeDomain(tt.providerType, tt.domain); got != tt.want {
			t.Errorf("NormalizeDomain(%q, %q) = %q, want %q", tt.providerType, tt.domain, got, tt.want)
		}
	}
}
