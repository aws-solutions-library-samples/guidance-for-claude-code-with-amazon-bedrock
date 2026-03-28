package federation

import (
	"context"
	"fmt"
	"os"
	"regexp"
	"strings"

	"credential-process-go/internal/config"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sts"
	"github.com/golang-jwt/jwt/v5"
)

var sanitizeRegex = regexp.MustCompile(`[^\w+=,.@-]`)

// debugLog prints a debug message to stderr when debug mode is enabled.
func debugLog(debug bool, format string, args ...interface{}) {
	if debug {
		fmt.Fprintf(os.Stderr, "Debug: "+format+"\n", args...)
	}
}

// clearAWSEnvVars temporarily clears AWS credential environment variables
// and returns a function that restores them.
func clearAWSEnvVars() func() {
	envVars := []string{
		"AWS_PROFILE",
		"AWS_ACCESS_KEY_ID",
		"AWS_SECRET_ACCESS_KEY",
		"AWS_SESSION_TOKEN",
	}

	saved := make(map[string]string)
	for _, key := range envVars {
		if val, ok := os.LookupEnv(key); ok {
			saved[key] = val
		}
		os.Unsetenv(key)
	}

	return func() {
		for _, key := range envVars {
			if val, ok := saved[key]; ok {
				os.Setenv(key, val)
			}
		}
	}
}

// buildRoleSessionName constructs a sanitized role session name from JWT claims.
func buildRoleSessionName(claims jwt.MapClaims) string {
	// Try sub claim first
	if sub, ok := claims["sub"].(string); ok && sub != "" {
		truncated := sub
		if len(truncated) > 32 {
			truncated = truncated[:32]
		}
		sanitized := sanitizeRegex.ReplaceAllString(truncated, "-")
		return "claude-code-" + sanitized
	}

	// Fallback to email username part
	if email, ok := claims["email"].(string); ok && email != "" {
		parts := strings.SplitN(email, "@", 2)
		if len(parts) > 0 && parts[0] != "" {
			sanitized := sanitizeRegex.ReplaceAllString(parts[0], "-")
			return "claude-code-" + sanitized
		}
	}

	// Default
	return "claude-code"
}

// isInvalidCredentialError checks if an error indicates invalid/expired credentials.
func isInvalidCredentialError(err error) bool {
	errStr := err.Error()
	invalidPatterns := []string{
		"InvalidParameter",
		"NotAuthorized",
		"ValidationError",
		"Invalid AccessKeyId",
		"ExpiredToken",
		"Invalid JWT",
	}
	for _, pattern := range invalidPatterns {
		if strings.Contains(errStr, pattern) {
			return true
		}
	}
	return false
}

// wrapCredentialError wraps an error with a message indicating credentials were cleared.
func wrapCredentialError(err error) error {
	return fmt.Errorf("%w - credentials were invalid and have been cleared", err)
}

// getCredentialsDirect uses STS AssumeRoleWithWebIdentity to obtain AWS credentials.
func getCredentialsDirect(cfg *config.ProfileConfig, idToken string, claims jwt.MapClaims, debug bool) (map[string]interface{}, error) {
	// Clear AWS env vars to prevent interference
	restore := clearAWSEnvVars()
	defer restore()

	ctx := context.Background()

	debugLog(debug, "Using direct STS federation with role: %s", cfg.FederatedRoleARN)

	// Create STS client with the configured region
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(cfg.AWSRegion),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	stsClient := sts.NewFromConfig(awsCfg)

	// Build session name
	sessionName := buildRoleSessionName(claims)
	debugLog(debug, "Role session name: %s", sessionName)

	// Determine duration
	duration := int32(cfg.MaxSessionDuration)
	if duration == 0 {
		duration = 43200
	}
	debugLog(debug, "Session duration: %d seconds", duration)

	// Call AssumeRoleWithWebIdentity
	input := &sts.AssumeRoleWithWebIdentityInput{
		RoleArn:          aws.String(cfg.FederatedRoleARN),
		RoleSessionName:  aws.String(sessionName),
		WebIdentityToken: aws.String(idToken),
		DurationSeconds:  aws.Int32(duration),
	}

	result, err := stsClient.AssumeRoleWithWebIdentity(ctx, input)
	if err != nil {
		if isInvalidCredentialError(err) {
			return nil, wrapCredentialError(err)
		}
		return nil, fmt.Errorf("STS AssumeRoleWithWebIdentity failed: %w", err)
	}

	// Format the response
	credentials := map[string]interface{}{
		"Version":         1,
		"AccessKeyId":     aws.ToString(result.Credentials.AccessKeyId),
		"SecretAccessKey": aws.ToString(result.Credentials.SecretAccessKey),
		"SessionToken":    aws.ToString(result.Credentials.SessionToken),
		"Expiration":      result.Credentials.Expiration.Format("2006-01-02T15:04:05Z"),
	}

	debugLog(debug, "Successfully obtained STS credentials, expiring: %s", credentials["Expiration"])

	return credentials, nil
}
