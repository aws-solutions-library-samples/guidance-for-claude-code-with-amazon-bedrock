package main

// SSO-disabled (passthrough) mode for the Go credential-process binary.
//
// When config.json sets `sso_enabled: false`, the credential helper bypasses
// OIDC entirely and emits AWS credentials from the ambient credential chain
// (IAM Identity Center, env vars, instance profile, ECS/EKS task role, etc.).
// This mirrors the Python `_run_passthrough` introduced in PR #303 (commit
// f8ff052). See issue tracking the missing Go-side parity.

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/config"
)

// passthroughOutput is the credential_process output format used by the
// passthrough path. Expiration is intentionally omitempty: per the AWS
// credential-process spec, an absent Expiration field tells the SDK that
// credentials do not expire (the SDK will retry on first failure). We use
// a separate type from federation.AWSCredentials to avoid altering the
// JSON shape of the OIDC happy path, which always emits a concrete
// Expiration timestamp.
type passthroughOutput struct {
	Version         int    `json:"Version"`
	AccessKeyID     string `json:"AccessKeyId"`
	SecretAccessKey string `json:"SecretAccessKey"`
	SessionToken    string `json:"SessionToken,omitempty"`
	Expiration      string `json:"Expiration,omitempty"`
}

// runPassthrough resolves AWS credentials from the default credential chain
// and prints them in credential_process JSON format. Returns the process
// exit code: 0 on success, 1 on any failure to resolve credentials.
//
// The caller must guarantee `cfg.IsSsoEnabled() == false` before invoking
// this; we don't re-check here so the call site stays explicit at main.go.
func (a *credentialApp) runPassthrough() int {
	debugPrint("SSO disabled for profile '%s'; using ambient AWS credential chain", a.profile)

	region := a.cfg.AWSRegion
	loadOpts := []func(*config.LoadOptions) error{}
	if region != "" {
		loadOpts = append(loadOpts, config.WithRegion(region))
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	awsCfg, err := config.LoadDefaultConfig(ctx, loadOpts...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to load AWS configuration: %v\n", err)
		fmt.Fprintln(os.Stderr, "Hint: log in via 'aws sso login' or set AWS credentials in your environment.")
		return 1
	}

	creds, err := awsCfg.Credentials.Retrieve(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: sso_enabled=false but no ambient AWS credentials found: %v\n", err)
		fmt.Fprintln(os.Stderr, "Hint: log in via 'aws sso login' or set AWS credentials in your environment.")
		return 1
	}

	if creds.AccessKeyID == "" {
		fmt.Fprintln(os.Stderr, "Error: ambient credentials resolved but access key is empty.")
		fmt.Fprintln(os.Stderr, "Hint: check your AWS CLI configuration or run 'aws sso login'.")
		return 1
	}

	out := passthroughOutput{
		Version:         1,
		AccessKeyID:     creds.AccessKeyID,
		SecretAccessKey: creds.SecretAccessKey,
		SessionToken:    creds.SessionToken,
	}
	// AWS SDK reports CanExpire=true for SSO/STS-derived creds and
	// CanExpire=false for static IAM users. Surface a real expiration when we
	// have one so the SDK can refresh through us; omit it otherwise.
	if creds.CanExpire {
		out.Expiration = creds.Expires.UTC().Format(time.RFC3339)
	}

	data, err := json.Marshal(out)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to marshal credentials: %v\n", err)
		return 1
	}
	fmt.Println(string(data))
	return 0
}
