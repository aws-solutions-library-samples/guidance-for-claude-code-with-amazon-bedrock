package federation

import (
	"context"
	"fmt"
	"os"
	"regexp"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sts"
	"github.com/bluedoors/ccwb-binaries/internal/jwt"
)

// AWSCredentials is the credential_process output format.
type AWSCredentials struct {
	Version         int    `json:"Version"`
	AccessKeyID     string `json:"AccessKeyId"`
	SecretAccessKey string `json:"SecretAccessKey"`
	SessionToken    string `json:"SessionToken"`
	Expiration      string `json:"Expiration"`
}

var sanitizeRe = regexp.MustCompile(`[^\w+=,.@\-]`)

// AssumeRoleWithWebIdentity exchanges an OIDC token for AWS credentials via direct STS.
func AssumeRoleWithWebIdentity(region, roleARN, idToken string, claims jwt.Claims, maxDuration int) (*AWSCredentials, error) {
	// Clear AWS env vars to prevent recursive credential resolution
	savedEnv := clearAWSEnv()
	defer restoreEnv(savedEnv)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	cfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(region),
		awsconfig.WithCredentialsProvider(aws.AnonymousCredentials{}),
	)
	if err != nil {
		return nil, fmt.Errorf("loading AWS config: %w", err)
	}

	client := sts.NewFromConfig(cfg)

	// Build session name
	sessionName := buildSessionName(claims)

	input := &sts.AssumeRoleWithWebIdentityInput{
		RoleArn:          aws.String(roleARN),
		RoleSessionName:  aws.String(sessionName),
		WebIdentityToken: aws.String(idToken),
		DurationSeconds:  aws.Int32(int32(maxDuration)),
	}

	result, err := client.AssumeRoleWithWebIdentity(ctx, input)
	if err != nil {
		return nil, fmt.Errorf("AssumeRoleWithWebIdentity failed: %w", err)
	}

	creds := result.Credentials
	expiration := ""
	if creds.Expiration != nil {
		expiration = creds.Expiration.Format(time.RFC3339)
	}

	return &AWSCredentials{
		Version:         1,
		AccessKeyID:     aws.ToString(creds.AccessKeyId),
		SecretAccessKey: aws.ToString(creds.SecretAccessKey),
		SessionToken:    aws.ToString(creds.SessionToken),
		Expiration:      expiration,
	}, nil
}

// buildSessionName derives an STS RoleSessionName from OIDC claims.
//
// The resulting principal ARN (assumed-role/RoleName/<session-name>) is what
// appears in the CUR 2.0 line_item_iam_principal column, enabling per-user
// Bedrock cost visibility without IdP-side session tag configuration. To
// produce readable rows like assumed-role/RoleName/alice@acme.com, we use
// the full email when available and fall back to sub only when email is
// absent (e.g. some Entra ID configurations).
//
// AWS STS RoleSessionName regex: [\w+=,.@-]*, max length 64.
func buildSessionName(claims jwt.Claims) string {
	if email := claims.GetString("email"); email != "" {
		sanitized := sanitizeRe.ReplaceAllString(email, "-")
		if len(sanitized) > 64 {
			sanitized = sanitized[:64]
		}
		return sanitized
	}
	if sub := claims.GetString("sub"); sub != "" {
		// Auth0 often uses pipe-delimited sub (e.g. auth0|12345); sanitize first.
		sanitized := sanitizeRe.ReplaceAllString(sub, "-")
		if len(sanitized) > 32 {
			sanitized = sanitized[:32]
		}
		return "claude-code-" + sanitized
	}
	return "claude-code"
}

func clearAWSEnv() map[string]string {
	vars := []string{"AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}
	saved := make(map[string]string)
	for _, v := range vars {
		if val, ok := os.LookupEnv(v); ok {
			saved[v] = val
			os.Unsetenv(v)
		}
	}
	return saved
}

func restoreEnv(saved map[string]string) {
	for k, v := range saved {
		os.Setenv(k, v)
	}
}
