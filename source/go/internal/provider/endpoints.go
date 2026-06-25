package provider

import "strings"

// Config holds OIDC endpoint paths and scopes for a provider.
type Config struct {
	Name              string
	AuthorizeEndpoint string
	TokenEndpoint     string
	Scopes            string
	ResponseType      string
	ResponseMode      string
}

// Configs maps provider type to its OIDC configuration.
//
// Okta defaults to the Org Authorization Server endpoints (/oauth2/v1/...),
// which match the CFN template's bare https://<domain> OIDC provider URL.
// This is the historical upstream behavior and keeps IAM's
// InvalidIdentityToken check happy for deployments that haven't opted into
// zone isolation or a non-default CAS.
//
// ConfigFor() rewrites the endpoints to /oauth2/<cas-id>/v1/... when the
// caller supplies a non-empty okta_auth_server_id in the profile -- that
// value is only set by `ccwb init` when the operator turns on zone
// isolation (or explicitly picks a CAS). Only a Custom Authorization
// Server can host admin-defined claims like the
// https://aws.amazon.com/tags/principal_tags/* session-tag claim that
// drives per-project cost attribution and zone isolation.
var Configs = map[string]Config{
	"okta": {
		Name:              "Okta",
		AuthorizeEndpoint: "/oauth2/v1/authorize",
		TokenEndpoint:     "/oauth2/v1/token",
		Scopes:            "openid profile email offline_access",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
	"auth0": {
		Name:              "Auth0",
		AuthorizeEndpoint: "/authorize",
		TokenEndpoint:     "/oauth/token",
		Scopes:            "openid profile email offline_access",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
	"azure": {
		Name:              "Azure AD",
		AuthorizeEndpoint: "/oauth2/v2.0/authorize",
		TokenEndpoint:     "/oauth2/v2.0/token",
		Scopes:            "openid profile email offline_access",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
	"cognito": {
		Name:              "AWS Cognito User Pool",
		AuthorizeEndpoint: "/oauth2/authorize",
		TokenEndpoint:     "/oauth2/token",
		Scopes:            "openid email",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
	"google": {
		Name:              "Google",
		AuthorizeEndpoint: "/o/oauth2/v2/auth",
		TokenEndpoint:     "https://oauth2.googleapis.com/token",
		Scopes:            "openid email profile",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
	"generic": {
		Name:              "Generic OIDC",
		AuthorizeEndpoint: "", // Unused — full URLs come from ProfileConfig
		TokenEndpoint:     "", // Unused — full URLs come from ProfileConfig
		Scopes:            "openid profile email offline_access",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
}

// ConfigFor returns the OIDC configuration for a provider, applying per-
// profile customizations.
//
// The Okta endpoints default to the Org Authorization Server
// (/oauth2/v1/...). Callers that need Custom Authorization Server claims
// (cost attribution, zone isolation) set okta_auth_server_id in the
// profile; any non-empty value -- including the string "default" for the
// pre-provisioned CAS -- rewrites the paths to /oauth2/<id>/v1/...
//
// Empty / unset okta_auth_server_id keeps the Org AS path and matches
// upstream's historical shape. Non-Okta providers ignore the argument.
// Returns a zero-value Config when providerType is unknown.
func ConfigFor(providerType, oktaAuthServerID string) Config {
	cfg, ok := Configs[providerType]
	if !ok {
		return Config{}
	}
	if providerType != "okta" {
		return cfg
	}
	id := strings.TrimSpace(oktaAuthServerID)
	if id == "" {
		return cfg
	}
	const oldSeg = "/oauth2/"
	newSeg := "/oauth2/" + id + "/"
	cfg.AuthorizeEndpoint = strings.Replace(cfg.AuthorizeEndpoint, oldSeg, newSeg, 1)
	cfg.TokenEndpoint = strings.Replace(cfg.TokenEndpoint, oldSeg, newSeg, 1)
	return cfg
}

// IsKnown returns true if providerType is a recognized provider.
func IsKnown(providerType string) bool {
	_, ok := Configs[providerType]
	return ok
}

// NormalizeDomain returns the provider domain with any provider-specific
// suffix removed so that ConfigFor().TokenEndpoint / .AuthorizeEndpoint can be
// appended without duplication.
//
// Azure AD's provider_domain is stored with a trailing "/v2.0"
// (e.g. "login.microsoftonline.com/<tenant>/v2.0") while its endpoints already
// carry the version segment ("/oauth2/v2.0/token"). Concatenating the two
// verbatim yields ".../v2.0/oauth2/v2.0/token" — a doubled segment the IdP
// rejects with HTTP 404. Stripping the trailing "/v2.0" here keeps the auth
// and refresh paths building identical URLs.
func NormalizeDomain(providerType, providerDomain string) string {
	if providerType == "azure" {
		return strings.TrimSuffix(providerDomain, "/v2.0")
	}
	return providerDomain
}

// TokenEndpointURL returns the absolute token endpoint URL for a named provider
// given its configured provider_domain. It centralizes the domain
// normalization + endpoint concatenation that the authorization-code flow and
// the refresh_token exchange must share — keeping them in lockstep so an Azure
// (or future provider) URL quirk can't be fixed in one path and missed in the
// other. Returns "" for an unknown provider type.
//
// Generic providers are intentionally not handled here: they supply absolute
// endpoint URLs directly via ProfileConfig, with no domain to normalize.
func TokenEndpointURL(providerType, oktaAuthServerID, providerDomain string) string {
	cfg := ConfigFor(providerType, oktaAuthServerID)
	if cfg.Name == "" {
		return ""
	}
	if strings.HasPrefix(cfg.TokenEndpoint, "https://") {
		return cfg.TokenEndpoint
	}
	domain := NormalizeDomain(providerType, providerDomain)
	return "https://" + domain + cfg.TokenEndpoint
}
