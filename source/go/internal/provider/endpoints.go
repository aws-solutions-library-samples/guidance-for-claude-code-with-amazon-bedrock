package provider

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
}

// IsKnown returns true if providerType is a recognized provider.
func IsKnown(providerType string) bool {
	_, ok := Configs[providerType]
	return ok
}
