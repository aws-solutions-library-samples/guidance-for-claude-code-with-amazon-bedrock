package provider

import (
	"net/url"
	"strings"
)

// Detect returns the provider type for a given domain or URL.
// Returns one of: "okta", "auth0", "azure", "cognito", "oidc".
func Detect(domain string) string {
	if domain == "" {
		return "oidc"
	}

	// Ensure it's a full URL for parsing
	u := domain
	if !strings.HasPrefix(u, "http://") && !strings.HasPrefix(u, "https://") {
		u = "https://" + u
	}

	parsed, err := url.Parse(u)
	if err != nil || parsed.Hostname() == "" {
		return "oidc"
	}

	h := strings.ToLower(parsed.Hostname())

	// Okta domains
	oktaDomains := []string{".okta.com", ".oktapreview.com", ".okta-emea.com"}
	oktaExact := []string{"okta.com", "oktapreview.com", "okta-emea.com"}
	for _, d := range oktaDomains {
		if strings.HasSuffix(h, d) {
			return "okta"
		}
	}
	for _, d := range oktaExact {
		if h == d {
			return "okta"
		}
	}

	// Auth0
	if strings.HasSuffix(h, ".auth0.com") || h == "auth0.com" {
		return "auth0"
	}

	// Azure / Microsoft
	if strings.HasSuffix(h, ".microsoftonline.com") || h == "microsoftonline.com" {
		return "azure"
	}
	if strings.HasSuffix(h, ".windows.net") || h == "windows.net" {
		return "azure"
	}

	// Cognito
	if strings.HasSuffix(h, ".amazoncognito.com") || h == "amazoncognito.com" {
		return "cognito"
	}
	if strings.HasPrefix(h, "cognito-idp.") && strings.Contains(h, ".amazonaws.com") {
		return "cognito"
	}

	return "oidc"
}
