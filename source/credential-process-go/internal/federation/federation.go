package federation

import (
	"credential-process-go/internal/config"

	"github.com/golang-jwt/jwt/v5"
)

// GetAWSCredentials routes to the appropriate federation method based on config.
func GetAWSCredentials(cfg *config.ProfileConfig, idToken string, claims jwt.MapClaims, debug bool) (map[string]interface{}, error) {
	if cfg.FederationType == "direct" {
		return getCredentialsDirect(cfg, idToken, claims, debug)
	}
	return getCredentialsCognito(cfg, idToken, claims, debug)
}
