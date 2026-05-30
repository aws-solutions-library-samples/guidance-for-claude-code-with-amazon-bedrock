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
		Scopes:            "openid profile email",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
	"auth0": {
		Name:              "Auth0",
		AuthorizeEndpoint: "/authorize",
		TokenEndpoint:     "/oauth/token",
		Scopes:            "openid profile email",
		ResponseType:      "code",
		ResponseMode:      "query",
	},
	"azure": {
		Name:              "Azure AD",
		AuthorizeEndpoint: "/oauth2/v2.0/authorize",
		TokenEndpoint:     "/oauth2/v2.0/token",
		Scopes:            "openid profile email",
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
	"generic": {
		Name:              "Generic OIDC",
		AuthorizeEndpoint: "", // Unused — full URLs come from ProfileConfig
		TokenEndpoint:     "", // Unused — full URLs come from ProfileConfig
		Scopes:            "openid profile email",
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
