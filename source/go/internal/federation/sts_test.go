package federation

import (
	"strings"
	"testing"

	"github.com/bluedoors/ccwb-binaries/internal/jwt"
)

func TestBuildSessionName(t *testing.T) {
	tests := []struct {
		name   string
		claims jwt.Claims
		want   string
	}{
		{
			name:   "email preferred over sub",
			claims: jwt.Claims{"email": "alice@acme.com", "sub": "00u123"},
			want:   "alice@acme.com",
		},
		{
			name:   "email with plus is preserved",
			claims: jwt.Claims{"email": "a.b+filter@example.co.uk"},
			want:   "a.b+filter@example.co.uk",
		},
		{
			name:   "email with invalid chars is sanitized to hyphens",
			claims: jwt.Claims{"email": "first name/ext@example.com"},
			want:   "first-name-ext@example.com",
		},
		{
			name:   "email over 64 chars is truncated",
			claims: jwt.Claims{"email": "a-very-long-local-part-that-exceeds-the-sixty-four-character-session-name-limit@example.com"},
			// 64-char cap, regardless of @ position
			want: "a-very-long-local-part-that-exceeds-the-sixty-four-character-ses",
		},
		{
			name:   "sub fallback when email missing, pipe sanitized",
			claims: jwt.Claims{"sub": "auth0|507f191e810c19729de860ea"},
			want:   "claude-code-auth0-507f191e810c19729de860ea",
		},
		{
			name:   "sub fallback truncated to 32 chars",
			claims: jwt.Claims{"sub": "this-sub-is-definitely-longer-than-thirty-two-characters"},
			want:   "claude-code-this-sub-is-definitely-longer-th",
		},
		{
			name:   "no identifying claims yields default",
			claims: jwt.Claims{},
			want:   "claude-code",
		},
		{
			name:   "empty email falls through to sub",
			claims: jwt.Claims{"email": "", "sub": "user-123"},
			want:   "claude-code-user-123",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := buildSessionName(tc.claims)
			if got != tc.want {
				t.Errorf("buildSessionName(%v) = %q, want %q", tc.claims, got, tc.want)
			}
			if len(got) > 64 {
				t.Errorf("session name %q exceeds STS 64-char limit (len=%d)", got, len(got))
			}
			if strings.ContainsAny(got, " /\\?#") {
				t.Errorf("session name %q contains characters STS would reject", got)
			}
		})
	}
}
