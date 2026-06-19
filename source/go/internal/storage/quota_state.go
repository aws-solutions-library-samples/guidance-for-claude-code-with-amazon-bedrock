package storage

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

// QuotaState persists quota check timestamps so the credential-process
// can enforce periodic re-checks even when serving cached credentials.
type QuotaState struct {
	LastCheckUnix int64 `json:"last_check_unix"`
}

// quotaStatePath returns the path to the quota state file for a profile.
func quotaStatePath(profile string) string {
	home, err := os.UserHomeDir()
	if err != nil {
		return ""
	}
	return filepath.Join(home, "claude-code-with-bedrock", ".quota-state-"+profile+".json")
}

// ReadQuotaState reads the last quota check timestamp for a profile.
// Returns zero time if no state exists or on any error.
func ReadQuotaState(profile string) time.Time {
	path := quotaStatePath(profile)
	if path == "" {
		return time.Time{}
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return time.Time{}
	}
	var state QuotaState
	if err := json.Unmarshal(data, &state); err != nil {
		return time.Time{}
	}
	if state.LastCheckUnix == 0 {
		return time.Time{}
	}
	return time.Unix(state.LastCheckUnix, 0)
}

// SaveQuotaState persists the current time as the last quota check timestamp.
func SaveQuotaState(profile string) error {
	path := quotaStatePath(profile)
	if path == "" {
		return nil
	}
	state := QuotaState{LastCheckUnix: time.Now().Unix()}
	data, err := json.Marshal(state)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}
