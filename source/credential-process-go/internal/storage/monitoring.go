package storage

import "os"

// GetMonitoringTokenFromEnvOrStore checks the environment variable first,
// then falls back to the store. Returns empty string if expired or not found.
func GetMonitoringTokenFromEnvOrStore(store Store, profile string) string {
	// Check environment variable first
	if envToken := os.Getenv("CLAUDE_CODE_MONITORING_TOKEN"); envToken != "" {
		return envToken
	}

	// Fall back to store
	token, err := store.GetMonitoringToken(profile)
	if err != nil {
		return ""
	}

	if IsMonitoringTokenExpired(token) {
		return ""
	}

	return token.Token
}
