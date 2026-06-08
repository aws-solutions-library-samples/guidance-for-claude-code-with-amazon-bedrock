package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

// TestPassthroughOutputShape locks down the JSON contract of the passthrough
// path. The AWS credential-process spec is strict about field names and
// requires Version=1; this test guards against a future refactor breaking
// any consumer (boto3, aws-sdk-go, aws-sdk-js, etc.).
func TestPassthroughOutputShape(t *testing.T) {
	t.Run("with_session_token_and_expiration", func(t *testing.T) {
		exp := time.Date(2026, 6, 7, 23, 0, 0, 0, time.UTC).Format(time.RFC3339)
		out := passthroughOutput{
			Version:         1,
			AccessKeyID:     "ASIATEST",
			SecretAccessKey: "secret",
			SessionToken:    "FwoGZXIvYX",
			Expiration:      exp,
		}
		data, err := json.Marshal(out)
		if err != nil {
			t.Fatalf("marshal failed: %v", err)
		}
		got := string(data)
		for _, want := range []string{
			`"Version":1`,
			`"AccessKeyId":"ASIATEST"`,
			`"SecretAccessKey":"secret"`,
			`"SessionToken":"FwoGZXIvYX"`,
			`"Expiration":"2026-06-07T23:00:00Z"`,
		} {
			if !strings.Contains(got, want) {
				t.Errorf("expected output to contain %q, got: %s", want, got)
			}
		}
	})

	t.Run("static_iam_user_omits_session_token_and_expiration", func(t *testing.T) {
		// Static IAM user creds have no SessionToken and CanExpire=false,
		// so we leave both fields out of the JSON. omitempty is what makes
		// the AWS SDK treat the credentials as non-expiring.
		out := passthroughOutput{
			Version:         1,
			AccessKeyID:     "AKIATEST",
			SecretAccessKey: "secret",
		}
		data, err := json.Marshal(out)
		if err != nil {
			t.Fatalf("marshal failed: %v", err)
		}
		got := string(data)
		if strings.Contains(got, "SessionToken") {
			t.Errorf("expected SessionToken omitted for static creds, got: %s", got)
		}
		if strings.Contains(got, "Expiration") {
			t.Errorf("expected Expiration omitted for non-expiring creds, got: %s", got)
		}
	})

	t.Run("must_use_credential_process_field_names", func(t *testing.T) {
		// AWS spec requires AccessKeyId (not AccessKeyID); a refactor changing
		// the JSON tag would silently break every consumer.
		out := passthroughOutput{Version: 1, AccessKeyID: "AKIA", SecretAccessKey: "s"}
		data, _ := json.Marshal(out)
		got := string(data)
		if !strings.Contains(got, `"AccessKeyId"`) {
			t.Errorf("expected AccessKeyId in output (per AWS credential-process spec), got: %s", got)
		}
		if strings.Contains(got, `"AccessKeyID"`) {
			t.Errorf("AccessKeyID would break SDK consumers; expected AccessKeyId, got: %s", got)
		}
	})
}
