package main

// IAM Identity Center active SSO authentication.
//
// When config.json has auth_type=="idc" (or sso_enabled==false with idc_start_url
// populated), credential-process drives the SSO OIDC device-authorization flow
// directly via the AWS SDK. This opens the user's browser for approval — no
// manual `aws sso login` required.
//
// Flow:
//   1. Load SSO config from config.json (start_url, account, role)
//   2. Check for cached SSO token (~/.aws/sso/cache/)
//   3. If expired/missing → initiate SSO OIDC device auth (opens browser)
//   4. Exchange SSO token for role credentials via STS
//   5. Perform quota check (SigV4-signed, via CheckWithIAM)
//   6. Write OTEL attribution cache (email from ARN session name)
//   7. Output credential_process JSON

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials/ssocreds"
	"github.com/aws/aws-sdk-go-v2/service/sso"
	"github.com/aws/aws-sdk-go-v2/service/ssooidc"
	"github.com/aws/aws-sdk-go-v2/service/sts"

	"ccwb-go/internal/otel"
	"ccwb-go/internal/quota"
)

// runIDC performs active SSO authentication for IAM Identity Center users.
// It uses the AWS SDK's ssocreds package to manage the SSO token lifecycle
// (including opening the browser for device authorization when needed).
func (a *credentialApp) runIDC() int {
	debugPrint("IDC active SSO mode for profile '%s'", a.profile)

	region := a.cfg.IDCRegion
	if region == "" {
		region = a.cfg.AWSRegion
	}
	if region == "" {
		fmt.Fprintln(os.Stderr, "Error: no region configured for IDC. Set idc_region or aws_region in config.json.")
		return 1
	}

	startURL := a.cfg.IDCStartURL
	accountID := a.cfg.IDCAccountID
	roleName := a.cfg.IDCPermissionSetName

	if startURL == "" || accountID == "" || roleName == "" {
		fmt.Fprintln(os.Stderr, "Error: incomplete IDC configuration in config.json.")
		if startURL == "" {
			fmt.Fprintln(os.Stderr, "  Missing: idc_start_url (e.g. https://d-xxxxxxxxxx.awsapps.com/start)")
		}
		if accountID == "" {
			fmt.Fprintln(os.Stderr, "  Missing: idc_account_id (AWS account ID for role assumption)")
		}
		if roleName == "" {
			fmt.Fprintln(os.Stderr, "  Missing: idc_permission_set_name (IAM role / permission set name)")
		}
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "Run 'ccwb init' to reconfigure, or edit config.json directly.")
		return 1
	}

	debugPrint("IDC config: start_url=%s account=%s role=%s region=%s", startURL, accountID, roleName, region)

	// 120s timeout allows time for user to approve in browser.
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	// Load minimal AWS config for the SSO region.
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(region))
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to load AWS config for IDC: %v\n", err)
		return 1
	}

	// Resolve the cached token file path for this SSO session.
	tokenPath, err := ssocreds.StandardCachedTokenFilepath(startURL)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to resolve SSO token cache path: %v\n", err)
		return 1
	}

	// Create SSO clients.
	ssoClient := sso.NewFromConfig(awsCfg)
	oidcClient := ssooidc.NewFromConfig(awsCfg)

	// Create SSO role credentials provider with token lifecycle management.
	// The SSOTokenProvider handles the full device-auth flow: checks
	// ~/.aws/sso/cache/ for a valid token, and if expired/missing, initiates
	// OIDC device authorization (opens browser for user approval).
	credProvider := ssocreds.New(ssoClient, accountID, roleName, startURL, func(opts *ssocreds.Options) {
		opts.SSOTokenProvider = ssocreds.NewSSOTokenProvider(oidcClient, tokenPath)
	})

	// Retrieve credentials — opens browser if SSO session expired.
	debugPrint("Retrieving IDC credentials (may open browser for auth)...")
	creds, err := credProvider.Retrieve(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: IDC authentication failed: %v\n", err)
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "If your browser did not open, ensure:")
		fmt.Fprintln(os.Stderr, "  - idc_start_url is correct in config.json")
		fmt.Fprintln(os.Stderr, "  - Your network can reach the SSO portal")
		fmt.Fprintln(os.Stderr, "  - You have permission to assume the configured role")
		return 1
	}

	debugPrint("IDC credentials retrieved successfully (key=%s...)", creds.AccessKeyID[:8])

	// Quota check (SigV4-signed with the IDC credentials we just resolved).
	if a.cfg.QuotaAPIEndpoint != "" {
		debugPrint("Performing quota check via SigV4 with IDC credentials...")
		qr := quota.CheckWithResolvedCreds(
			a.cfg.QuotaAPIEndpoint,
			creds,
			region,
			a.cfg.QuotaCheckTimeout,
			a.cfg.QuotaFailMode,
		)
		if !qr.Allowed {
			printQuotaBlocked(qr)
			return 1
		}
		printQuotaWarning(qr)
	}

	// Write OTEL attribution cache using the just-obtained IDC credentials.
	// We pass creds explicitly to avoid LoadDefaultConfig resolving via
	// credential_process (which would recurse back into this binary).
	a.writeOtelCacheFromIDC(creds, region)

	// Output credential_process JSON.
	out := passthroughOutput{
		Version:         1,
		AccessKeyID:     creds.AccessKeyID,
		SecretAccessKey: creds.SecretAccessKey,
		SessionToken:    creds.SessionToken,
	}
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

// writeOtelCacheFromIDC resolves user identity via STS GetCallerIdentity
// using the just-obtained IDC credentials (passed explicitly to avoid
// LoadDefaultConfig resolving via credential_process recursion).
func (a *credentialApp) writeOtelCacheFromIDC(creds aws.Credentials, region string) {
	ctx := context.Background()
	cfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(region),
		awsconfig.WithCredentialsProvider(
			aws.CredentialsProviderFunc(func(ctx context.Context) (aws.Credentials, error) {
				return creds, nil
			}),
		),
	)
	if err != nil {
		debugPrint("writeOtelCacheFromIDC: failed to load AWS config: %v", err)
		return
	}

	stsClient := sts.NewFromConfig(cfg)
	identity, err := stsClient.GetCallerIdentity(ctx, &sts.GetCallerIdentityInput{})
	if err != nil {
		debugPrint("writeOtelCacheFromIDC: GetCallerIdentity failed: %v", err)
		return
	}

	arn := ""
	if identity.Arn != nil {
		arn = *identity.Arn
	}
	email := extractEmailFromARN(arn)
	if email == "" {
		debugPrint("writeOtelCacheFromIDC: could not extract identity from ARN: %s", arn)
		return
	}

	debugPrint("writeOtelCacheFromIDC: resolved identity: %s", email)

	userInfo := otel.UserInfo{Email: email}
	headers := otel.FormatHeaders(userInfo)
	expiry := time.Now().Add(1 * time.Hour).Unix()
	if err := otel.WriteCachedHeaders(a.profile, headers, expiry); err != nil {
		debugPrint("writeOtelCacheFromIDC: cache write failed: %v", err)
	}
}
