package storage

import (
	"encoding/base64"
	"encoding/json"
	"testing"
	"time"
)

func makeMonitoringJWT(claims map[string]interface{}) string {
	header := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"RS256","typ":"JWT"}`))
	payload, _ := json.Marshal(claims)
	payloadB64 := base64.RawURLEncoding.EncodeToString(payload)
	return header + "." + payloadB64 + ".signature"
}

// TestGetMonitoringToken_EnvExpired is the regression guard for #561: an
// expired token in CLAUDE_CODE_MONITORING_TOKEN must NOT be returned. On the
// unfixed code the env branch returned the token on truthiness alone, so this
// fails there and passes once the expiry check is applied.
func TestGetMonitoringToken_EnvExpired(t *testing.T) {
	expired := makeMonitoringJWT(map[string]interface{}{
		"exp": float64(time.Now().Unix() - 3600),
	})
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", expired)

	// "file" storage with no cache file on disk: a valid env token would be
	// returned; an expired one must be dropped. After dropping it, the call
	// falls through to a (missing) file read, so an error here is expected —
	// the contract under test is that NO token is returned.
	token, _ := GetMonitoringToken("nonexistent-profile-561", "file")
	if token != "" {
		t.Errorf("expected expired env token to be dropped, got non-empty token")
	}
}

// TestGetMonitoringToken_EnvValid confirms the normal path is unchanged: a
// fresh env token is still returned directly.
func TestGetMonitoringToken_EnvValid(t *testing.T) {
	valid := makeMonitoringJWT(map[string]interface{}{
		"exp": float64(time.Now().Unix() + 3600),
	})
	t.Setenv("CLAUDE_CODE_MONITORING_TOKEN", valid)

	token, err := GetMonitoringToken("nonexistent-profile-561", "file")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if token != valid {
		t.Errorf("expected valid env token to be returned unchanged")
	}
}
