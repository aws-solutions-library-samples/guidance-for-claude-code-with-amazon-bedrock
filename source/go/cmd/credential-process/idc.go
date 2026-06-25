package main

// IAM Identity Center active SSO authentication.
//
// When config.json has auth_type=="idc" (or sso_enabled==false with idc_start_url
// populated), credential-process drives the SSO OIDC device-authorization flow
// itself (RegisterClient → StartDeviceAuthorization → browser approval →
// CreateToken), writing the resulting token to the SDK's standard cache. This
// means no AWS CLI / `aws sso login` dependency — the binary is self-contained.
//
// Flow:
//   1. Load SSO config from config.json (start_url, account, role)
//   2. Check for cached SSO token (~/.aws/sso/cache/)
//   3. If expired/missing → run device authorization (opens browser), then
//      persist the token to the cache in the SDK's on-disk format
//   4. Exchange SSO token for role credentials via STS
//   5. Perform quota check (SigV4-signed, via CheckWithIAM)
//   6. Write OTEL attribution cache (email from ARN session name)
//   7. Output credential_process JSON

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials/ssocreds"
	"github.com/aws/aws-sdk-go-v2/service/sso"
	"github.com/aws/aws-sdk-go-v2/service/ssooidc"
	ssooidctypes "github.com/aws/aws-sdk-go-v2/service/ssooidc/types"
	"github.com/aws/aws-sdk-go-v2/service/sts"

	"ccwb-go/internal/browser"
	"ccwb-go/internal/otel"
	"ccwb-go/internal/portlock"
	"ccwb-go/internal/quota"
)

// idcRefreshLockPort serializes the SSO refresh-token exchange across concurrent
// credential-process invocations. IAM Identity Center refresh tokens ROTATE:
// CreateToken(refresh_token) consumes the presented token and issues a new one,
// invalidating the old. Claude Code routinely fires several credential-process
// calls at once (e.g. the session-title model and the main model on the same
// turn). Without serialization, the first call rotates the token while the
// others still hold the consumed one -> InvalidGrantException, and the bricked
// cache then fails every subsequent call until an interactive re-login. Holding
// an exclusive local lock around the refresh means exactly one process rotates;
// the rest wait, then read the now-valid cached token (no second rotation).
// Distinct from the OIDC redirect port (default 8400) so the two never collide.
const idcRefreshLockPort = 8402

// idcSettings holds the validated IDC parameters and SSO clients needed by
// both the full credential flow (runIDC) and the login-only flow (runIDCLogin).
type idcSettings struct {
	region     string
	startURL   string
	accountID  string
	roleName   string
	tokenPath  string
	ssoClient  *sso.Client
	oidcClient *ssooidc.Client
}

// resolveIDCSettings validates the profile's IDC configuration and constructs
// the SSO clients. On any error it prints a user-facing message and returns a
// non-zero exit code (second return value); callers should propagate it.
func (a *credentialApp) resolveIDCSettings(ctx context.Context) (*idcSettings, int) {
	region := a.cfg.IDCRegion
	if region == "" {
		region = a.cfg.AWSRegion
	}
	if region == "" {
		fmt.Fprintln(os.Stderr, "Error: no region configured for IDC. Set idc_region or aws_region in config.json.")
		return nil, 1
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
		return nil, 1
	}

	debugPrint("IDC config: start_url=%s account=%s role=%s region=%s", startURL, accountID, roleName, region)

	// Load minimal AWS config for the SSO region.
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(region))
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to load AWS config for IDC: %v\n", err)
		return nil, 1
	}

	// Resolve the cached token file path for this SSO session.
	tokenPath, err := ssocreds.StandardCachedTokenFilepath(startURL)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: failed to resolve SSO token cache path: %v\n", err)
		return nil, 1
	}

	return &idcSettings{
		region:     region,
		startURL:   startURL,
		accountID:  accountID,
		roleName:   roleName,
		tokenPath:  tokenPath,
		ssoClient:  sso.NewFromConfig(awsCfg),
		oidcClient: ssooidc.NewFromConfig(awsCfg),
	}, 0
}

// runIDCLogin runs the interactive sign-in step only: it ensures a valid SSO
// token is cached (running device authorization if needed), then exits without
// emitting credentials. This is the recommended first step on headless/SSH
// hosts, where the AWS SDK would otherwise capture the device-auth prompt when
// credential-process is invoked non-interactively by Claude Code.
func (a *credentialApp) runIDCLogin() int {
	debugPrint("IDC login (sign-in only) for profile '%s'", a.profile)

	// Generous timeout: the user must approve in a browser, possibly on another
	// device, before this returns.
	ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
	defer cancel()

	s, code := a.resolveIDCSettings(ctx)
	if code != 0 {
		return code
	}

	if tokenValid(s.tokenPath) {
		fmt.Fprintln(os.Stderr, "Already signed in to IAM Identity Center — cached session is still valid.")
		return 0
	}

	// Expired access token with refresh material present: try the silent refresh
	// before prompting. tokenRefreshable only confirms the fields EXIST — it
	// cannot tell whether the refresh token is still accepted by AWS (a rotated/
	// consumed or genuinely expired refresh token returns InvalidGrantException).
	// So we must actually attempt the refresh: success means the session is still
	// alive (no prompt needed); failure means we fall through to interactive
	// device auth rather than falsely reporting "already signed in".
	if tokenRefreshable(s.tokenPath) {
		if err := a.refreshIDCTokenLocked(ctx, s.oidcClient, s.tokenPath); err == nil {
			fmt.Fprintln(os.Stderr, "Already signed in to IAM Identity Center — session refreshed.")
			return 0
		} else {
			debugPrint("Silent refresh failed (%v); falling through to interactive sign-in", err)
		}
	}

	if err := a.runDeviceAuthorization(ctx, s.oidcClient, s.startURL, s.tokenPath); err != nil {
		fmt.Fprintf(os.Stderr, "Error: IDC sign-in failed: %v\n", err)
		return 1
	}

	fmt.Fprintln(os.Stderr, "Signed in to IAM Identity Center. Claude Code can now run without further prompts until the session expires.")
	return 0
}

// runIDC performs active SSO authentication for IAM Identity Center users.
// It drives the device-authorization flow itself when needed (see idc device
// auth helpers below), caches the SSO token, then exchanges it for role
// credentials via STS.
func (a *credentialApp) runIDC() int {
	debugPrint("IDC active SSO mode for profile '%s'", a.profile)

	// 120s timeout allows time for user to approve in browser.
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	s, code := a.resolveIDCSettings(ctx)
	if code != 0 {
		return code
	}
	region := s.region
	startURL := s.startURL
	accountID := s.accountID
	roleName := s.roleName
	tokenPath := s.tokenPath
	ssoClient := s.ssoClient
	oidcClient := s.oidcClient

	// Ensure a usable SSO token exists in ~/.aws/sso/cache/. The SDK's
	// ssocreds.SSOTokenProvider only READS (and refreshes via refresh_token)
	// an existing cached token — it does NOT perform device authorization.
	// On a machine that has never run the device-auth flow, the cache file is
	// absent and Retrieve() fails with "failed to read cached SSO token file".
	// We drive the device-auth flow ourselves (browser approval) so end users
	// never need the AWS CLI / `aws sso login`.
	if err := a.ensureIDCToken(ctx, oidcClient, startURL, tokenPath); err != nil {
		fmt.Fprintf(os.Stderr, "Error: IDC authentication failed: %v\n", err)
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "If authentication did not complete, ensure:")
		fmt.Fprintln(os.Stderr, "  - idc_start_url is correct in config.json")
		fmt.Fprintln(os.Stderr, "  - Your network can reach the SSO portal")
		fmt.Fprintln(os.Stderr, "  - You approved the request in your browser")
		return 1
	}

	// Create SSO role credentials provider with token lifecycle management.
	// The SSOTokenProvider reads the cached token written above (and silently
	// refreshes it via refresh_token when expired).
	credProvider := ssocreds.New(ssoClient, accountID, roleName, startURL, func(opts *ssocreds.Options) {
		opts.SSOTokenProvider = ssocreds.NewSSOTokenProvider(oidcClient, tokenPath)
	})

	// Exchange the SSO token for role credentials via STS.
	debugPrint("Retrieving IDC role credentials...")
	creds, err := credProvider.Retrieve(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: IDC authentication failed: %v\n", err)
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintln(os.Stderr, "If credential retrieval failed, ensure:")
		fmt.Fprintln(os.Stderr, "  - idc_account_id and idc_permission_set_name are correct in config.json")
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

// ssoCachedToken mirrors the on-disk format the AWS SDK's ssocreds package
// reads from ~/.aws/sso/cache/<sha1(startURL)>.json. We write the same shape
// so the SDK's SSOTokenProvider can read it back (and refresh it via
// refresh_token when expired). Field names and the RFC3339 expiresAt format
// must match the SDK exactly.
type ssoCachedToken struct {
	AccessToken  string `json:"accessToken"`
	ExpiresAt    string `json:"expiresAt"`
	RefreshToken string `json:"refreshToken,omitempty"`
	ClientID     string `json:"clientId,omitempty"`
	ClientSecret string `json:"clientSecret,omitempty"`
	Region       string `json:"region,omitempty"`
	StartURL     string `json:"startUrl,omitempty"`
}

// ensureIDCToken guarantees a non-expired SSO access token exists at tokenPath.
// If the cached token is present and unexpired, it returns immediately. Otherwise
// it runs the OIDC device-authorization flow (opening the user's browser) and
// persists the resulting token in the SDK's cache format.
func (a *credentialApp) ensureIDCToken(ctx context.Context, oidcClient *ssooidc.Client, startURL, tokenPath string) error {
	if tokenValid(tokenPath) {
		debugPrint("Existing SSO token cache is valid: %s", tokenPath)
		return nil
	}
	// Access token expired but the cache can be refreshed silently
	// (refresh_token + client creds present). Perform the refresh under an
	// exclusive lock so concurrent credential-process invocations don't each
	// try to redeem the rotating refresh token (see idcRefreshLockPort).
	if tokenRefreshable(tokenPath) {
		debugPrint("SSO access token expired but refreshable; refreshing under lock")
		return a.refreshIDCTokenLocked(ctx, oidcClient, tokenPath)
	}
	debugPrint("No valid or refreshable SSO token cache; starting device authorization")
	return a.runDeviceAuthorization(ctx, oidcClient, startURL, tokenPath)
}

// refreshIDCTokenLocked refreshes the SSO access token (via the rotating
// refresh-token grant) while holding an exclusive local lock, so that only one
// of several concurrent credential-process invocations performs the rotation.
// The rest wait and then read the freshly-refreshed cached token instead of
// presenting the now-consumed refresh token (which AWS rejects with
// InvalidGrantException, bricking the cache for every later call).
func (a *credentialApp) refreshIDCTokenLocked(ctx context.Context, oidcClient *ssooidc.Client, tokenPath string) error {
	ln, _ := portlock.TryAcquire(idcRefreshLockPort)
	if ln == nil {
		// Another process is refreshing. Wait for it, then use its result.
		debugPrint("Another process is refreshing the SSO token; waiting...")
		portlock.WaitForRelease(idcRefreshLockPort, 30*time.Second)
		if tokenValid(tokenPath) {
			debugPrint("Concurrent refresh completed; using refreshed token")
			return nil
		}
		// The other process didn't leave a valid token (it failed, or its token
		// also expired). Try to take the lock and refresh ourselves.
		ln, _ = portlock.TryAcquire(idcRefreshLockPort)
		if ln == nil {
			// Still contended — fall back to an unlocked refresh attempt rather
			// than block indefinitely. Worst case this races, which is the
			// pre-fix behavior, not a regression.
			debugPrint("Refresh lock still contended; attempting refresh without lock")
			return a.doIDCRefresh(ctx, oidcClient, tokenPath)
		}
	}
	defer ln.Close()

	// Re-check under the lock: a winner may have refreshed between our initial
	// check and acquiring the lock, in which case there's nothing to do.
	if tokenValid(tokenPath) {
		debugPrint("Token already refreshed by another process; skipping refresh")
		return nil
	}
	return a.doIDCRefresh(ctx, oidcClient, tokenPath)
}

// doIDCRefresh performs the actual refresh-token exchange via the SDK's token
// provider, which redeems the refresh token and writes the rotated token back
// to the cache. Run only by the lock holder in the normal path.
func (a *credentialApp) doIDCRefresh(ctx context.Context, oidcClient *ssooidc.Client, tokenPath string) error {
	provider := ssocreds.NewSSOTokenProvider(oidcClient, tokenPath)
	if _, err := provider.RetrieveBearerToken(ctx); err != nil {
		return fmt.Errorf("refreshing SSO token: %w", err)
	}
	return nil
}

// tokenValid reports whether tokenPath holds a cached token that is present and
// not yet expired. A missing/unreadable/expired token returns false, which
// triggers a fresh device-authorization flow. (We intentionally don't try to
// refresh here — the SDK's SSOTokenProvider handles refresh_token when the
// token is merely expired but refreshable; this gate is for the "no usable
// session at all" case.)
func tokenValid(tokenPath string) bool {
	data, err := os.ReadFile(tokenPath) // #nosec G304 -- path derived from SDK helper, not user input
	if err != nil {
		return false
	}
	var t ssoCachedToken
	if err := json.Unmarshal(data, &t); err != nil {
		return false
	}
	if t.AccessToken == "" || t.ExpiresAt == "" {
		return false
	}
	expiresAt, err := time.Parse(time.RFC3339, t.ExpiresAt)
	if err != nil {
		return false
	}
	// Require a small safety margin so we don't hand back a token that expires
	// mid-request.
	return time.Now().Add(60 * time.Second).Before(expiresAt)
}

// tokenRefreshable reports whether the cached token carries the material the
// SDK's SSOTokenProvider needs to silently exchange an EXPIRED access token for
// a fresh one (refresh_token grant): a refresh token plus the client id/secret
// from RegisterClient. When this is true we must NOT force interactive
// device-authorization just because the short-lived access token expired — the
// SSO *session* (represented by the refresh token, typically hours/days) is
// still alive, so letting credProvider.Retrieve run performs a no-browser
// refresh. Gating device-auth on tokenValid alone caused premature "sign-in
// required" at the ~1h access-token boundary.
func tokenRefreshable(tokenPath string) bool {
	data, err := os.ReadFile(tokenPath) // #nosec G304 -- path derived from SDK helper, not user input
	if err != nil {
		return false
	}
	var t ssoCachedToken
	if err := json.Unmarshal(data, &t); err != nil {
		return false
	}
	return t.RefreshToken != "" && t.ClientID != "" && t.ClientSecret != ""
}

// isHeadless is defined in quota_notification.go (shared by the quota
// browser-notification flow and this IDC device-auth flow): it reports whether
// there's no usable local browser, so the flow shows a copy-to-another-device
// prompt instead of trying to launch a browser the user can't see.

// stderrIsTerminal reports whether stderr is attached to an interactive
// terminal. When false, our device-auth prompt is being captured (e.g. by the
// AWS SDK's credential_process handling, or by Claude Code's awsAuthRefresh
// which only displays output AFTER the command exits) rather than shown live —
// so a blocking poll would never surface the verification URL to the user.
func stderrIsTerminal() bool {
	fi, err := os.Stderr.Stat()
	if err != nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0
}

// launcherPath returns the absolute path to the claude-bedrock launcher, which
// lives in the same directory as this binary — so we derive it from
// os.Executable() rather than assuming it's on the user's PATH. Falls back to
// the bare command name if the executable path can't be resolved (works if it
// happens to be on PATH).
func (a *credentialApp) launcherPath() string {
	launcherName := "claude-bedrock"
	if runtime.GOOS == "windows" {
		launcherName = "claude-bedrock.cmd"
	}
	exe, err := os.Executable()
	if err != nil {
		return launcherName
	}
	return filepath.Join(filepath.Dir(exe), launcherName)
}

// runDeviceAuthorization performs the full SSO OIDC device-authorization flow
// and writes the resulting token to tokenPath in the SDK's cache format.
func (a *credentialApp) runDeviceAuthorization(ctx context.Context, oidcClient *ssooidc.Client, startURL, tokenPath string) error {
	// Fail fast whenever stderr is not an interactive terminal — i.e. we're being
	// run non-interactively (the Claude Code credential-hook case on every OS).
	// Device authorization needs the user to read a verification URL/code live,
	// but when stderr is captured we can't surface it, so polling would just
	// block for the full timeout and then fail. Exit immediately with an
	// actionable instruction instead of hanging.
	//
	// This intentionally does NOT also require isHeadless(): that heuristic
	// can't detect a headless WINDOWS host (no DISPLAY equivalent; the switch
	// assumes Windows/macOS have a desktop browser), so gating on it left
	// non-SSH headless Windows (SSM Session Manager, services, containers) able
	// to reach the blocking poll and hang. stderrIsTerminal alone is the correct
	// signal — even if a browser could open, a captured-stderr caller can't show
	// the user the code to verify. isHeadless() is used only below, to decide
	// whether attempting browser.OpenURL is worthwhile in the interactive path.
	if !stderrIsTerminal() {
		// Plain-language message: no AWS jargon, explicit absolute path, and a
		// clear "exit Claude Code, run this in your shell" instruction (the old
		// "quit ... from your terminal" was ambiguous about WHAT to quit).
		// We offer ONLY the launcher: it both signs in and reopens Claude Code,
		// which is the one path that reliably recovers. Running the bare --login
		// from another terminal refreshes the cache but does NOT reliably unstick
		// an already-failed session, so surfacing it here would mislead.
		launcher := a.launcherPath()
		return fmt.Errorf(
			"Your AWS sign-in session has expired. Renewing it requires a web browser, "+
				"which Claude Code can't open on its own from here.\n"+
				"To sign in again:\n"+
				"  1. Exit Claude Code (press Ctrl-C, or type /quit).\n"+
				"  2. At your command prompt, run:\n"+
				"       %s\n"+
				"     It shows a sign-in link to open in any browser, then reopens Claude Code.", launcher)
	}

	// 1. Register a public client capable of the device-code + refresh grants.
	reg, err := oidcClient.RegisterClient(ctx, &ssooidc.RegisterClientInput{
		ClientName: aws.String("claude-code-with-bedrock"),
		ClientType: aws.String("public"),
		Scopes:     []string{"sso:account:access"},
		GrantTypes: []string{"urn:ietf:params:oauth:grant-type:device_code", "refresh_token"},
	})
	if err != nil {
		return fmt.Errorf("registering SSO OIDC client: %w", err)
	}

	// 2. Start device authorization to obtain a user code + verification URL.
	devAuth, err := oidcClient.StartDeviceAuthorization(ctx, &ssooidc.StartDeviceAuthorizationInput{
		ClientId:     reg.ClientId,
		ClientSecret: reg.ClientSecret,
		StartUrl:     aws.String(startURL),
	})
	if err != nil {
		return fmt.Errorf("starting device authorization: %w", err)
	}

	// 3. Direct the user to approve. Prefer the complete URL (code pre-filled);
	//    print instructions to stderr (stdout is reserved for the credential JSON).
	verificationURI := aws.ToString(devAuth.VerificationUriComplete)
	if verificationURI == "" {
		verificationURI = aws.ToString(devAuth.VerificationUri)
	}
	userCode := aws.ToString(devAuth.UserCode)

	fmt.Fprintln(os.Stderr, "")
	if isHeadless() {
		// No local browser (SSH/headless): the user opens the URL on another
		// device. Don't attempt to open a browser here — it would fail or, worse,
		// launch a browser the user can't see. Show the plain verification URL +
		// code so it works regardless of which device they use.
		plainURI := aws.ToString(devAuth.VerificationUri)
		if plainURI == "" {
			plainURI = verificationURI
		}
		fmt.Fprintln(os.Stderr, "To sign in to IAM Identity Center, open this URL on any device with a browser:")
		fmt.Fprintf(os.Stderr, "  %s\n", plainURI)
		fmt.Fprintf(os.Stderr, "and enter this code: %s\n", userCode)
		fmt.Fprintln(os.Stderr, "")
		fmt.Fprintf(os.Stderr, "(Or open the direct link with the code pre-filled: %s )\n", verificationURI)
		debugPrint("Headless environment detected; skipping browser open")
	} else {
		fmt.Fprintln(os.Stderr, "Opening your browser to sign in to IAM Identity Center.")
		fmt.Fprintln(os.Stderr, "If it does not open, paste this URL into a browser:")
		fmt.Fprintf(os.Stderr, "  %s\n", verificationURI)
		fmt.Fprintf(os.Stderr, "and verify this code is shown: %s\n", userCode)
		if err := browser.OpenURL(verificationURI); err != nil {
			debugPrint("Could not open browser automatically: %v (continuing — user can open the URL manually)", err)
		}
	}
	fmt.Fprintln(os.Stderr, "")
	fmt.Fprintln(os.Stderr, "Waiting for approval...")

	// 4. Poll CreateToken until the user approves (or the device code expires).
	token, err := pollForToken(ctx, oidcClient, reg, devAuth)
	if err != nil {
		return err
	}

	// 5. Persist the token in the SDK's cache format so SSOTokenProvider can use it.
	expiresAt := time.Now().Add(time.Duration(token.ExpiresIn) * time.Second)
	cached := ssoCachedToken{
		AccessToken:  aws.ToString(token.AccessToken),
		ExpiresAt:    expiresAt.UTC().Format(time.RFC3339),
		RefreshToken: aws.ToString(token.RefreshToken),
		ClientID:     aws.ToString(reg.ClientId),
		ClientSecret: aws.ToString(reg.ClientSecret),
		StartURL:     startURL,
	}
	if err := writeSSOTokenCache(tokenPath, cached); err != nil {
		return fmt.Errorf("writing SSO token cache: %w", err)
	}
	debugPrint("Device authorization complete; token cached at %s", tokenPath)
	return nil
}

// pollForToken repeatedly calls CreateToken with the device code, honoring the
// service's polling interval and slow-down signals, until the user approves.
func pollForToken(
	ctx context.Context,
	oidcClient *ssooidc.Client,
	reg *ssooidc.RegisterClientOutput,
	devAuth *ssooidc.StartDeviceAuthorizationOutput,
) (*ssooidc.CreateTokenOutput, error) {
	interval := time.Duration(devAuth.Interval) * time.Second
	if interval <= 0 {
		interval = 5 * time.Second
	}

	for {
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("timed out waiting for browser approval: %w", ctx.Err())
		case <-time.After(interval):
		}

		out, err := oidcClient.CreateToken(ctx, &ssooidc.CreateTokenInput{
			ClientId:     reg.ClientId,
			ClientSecret: reg.ClientSecret,
			DeviceCode:   devAuth.DeviceCode,
			GrantType:    aws.String("urn:ietf:params:oauth:grant-type:device_code"),
		})
		if err == nil {
			return out, nil
		}

		// Still waiting for the user to approve — keep polling.
		var pending *ssooidctypes.AuthorizationPendingException
		if errors.As(err, &pending) {
			debugPrint("Authorization pending; continuing to poll")
			continue
		}
		// Service asked us to back off — increase the interval and keep polling.
		var slowDown *ssooidctypes.SlowDownException
		if errors.As(err, &slowDown) {
			interval += 5 * time.Second
			debugPrint("Slow down requested; polling interval now %s", interval)
			continue
		}
		// Anything else (expired device code, access denied, etc.) is terminal.
		return nil, fmt.Errorf("device authorization failed: %w", err)
	}
}

// writeSSOTokenCache writes the cached token JSON to path, creating the cache
// directory if needed. The file is written 0600 (user-only) since it contains
// bearer credentials; the directory is 0700.
func writeSSOTokenCache(path string, token ssoCachedToken) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("creating SSO cache directory: %w", err)
	}
	data, err := json.Marshal(token)
	if err != nil {
		return fmt.Errorf("marshaling SSO token: %w", err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		return fmt.Errorf("writing SSO token file: %w", err)
	}
	return nil
}
