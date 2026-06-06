package storage

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// refreshTokenData is the on-disk format for a cached refresh token.
type refreshTokenData struct {
	Token     string `json:"refresh_token"`
	Profile   string `json:"profile"`
	UpdatedAt int64  `json:"updated_at"`
}

// SaveRefreshToken persists the OIDC refresh_token for a profile.
// Stored alongside session files at ~/.claude-code-session/{profile}-refresh.json
// with user-only permissions (0600).
func SaveRefreshToken(profile, credentialStorage, token string) error {
	if token == "" {
		return nil // IdP didn't issue a refresh token — nothing to store
	}

	dir := sessionDir()
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}

	data := refreshTokenData{
		Token:     token,
		Profile:   profile,
		UpdatedAt: time.Now().Unix(),
	}

	jsonBytes, err := json.Marshal(data)
	if err != nil {
		return err
	}

	path := filepath.Join(dir, profile+"-refresh.json")

	// Write atomically via temp file + rename
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, jsonBytes, 0600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// LoadRefreshToken retrieves the cached refresh_token for a profile.
// Returns empty string if no token is cached (not an error).
func LoadRefreshToken(profile, credentialStorage string) string {
	path := filepath.Join(sessionDir(), profile+"-refresh.json")

	raw, err := os.ReadFile(path)
	if err != nil {
		return ""
	}

	var data refreshTokenData
	if err := json.Unmarshal(raw, &data); err != nil {
		return ""
	}

	return data.Token
}

// ClearRefreshToken removes the cached refresh_token for a profile.
func ClearRefreshToken(profile string) {
	path := filepath.Join(sessionDir(), profile+"-refresh.json")
	os.Remove(path)
}

// sessionDir returns the session directory path.
func sessionDir() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".claude-code-session")
}
