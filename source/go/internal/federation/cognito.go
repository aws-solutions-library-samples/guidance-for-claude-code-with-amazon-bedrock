package federation

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/cognitoidentity"
	"github.com/bluedoors/ccwb-binaries/internal/jwt"
)

// GetCredentialsViaCognito exchanges an OIDC token for AWS credentials via Cognito Identity Pool.
func GetCredentialsViaCognito(region, identityPoolID, providerDomain, providerType, idToken string, claims jwt.Claims) (*AWSCredentials, error) {
	// Clear AWS env vars
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

	client := cognitoidentity.NewFromConfig(cfg)

	// Determine login key
	loginKey := determineLoginKey(providerType, providerDomain, claims)

	// GetId
	getIDOutput, err := client.GetId(ctx, &cognitoidentity.GetIdInput{
		IdentityPoolId: aws.String(identityPoolID),
		Logins:         map[string]string{loginKey: idToken},
	})
	if err != nil {
		return nil, fmt.Errorf("Cognito GetId failed: %w", err)
	}

	identityID := aws.ToString(getIDOutput.IdentityId)

	// GetCredentialsForIdentity
	credsOutput, err := client.GetCredentialsForIdentity(ctx, &cognitoidentity.GetCredentialsForIdentityInput{
		IdentityId: aws.String(identityID),
		Logins:     map[string]string{loginKey: idToken},
	})
	if err != nil {
		return nil, fmt.Errorf("Cognito GetCredentialsForIdentity failed: %w", err)
	}

	creds := credsOutput.Credentials
	expiration := ""
	if creds.Expiration != nil {
		expiration = creds.Expiration.Format(time.RFC3339)
	}

	return &AWSCredentials{
		Version:         1,
		AccessKeyID:     aws.ToString(creds.AccessKeyId),
		SecretAccessKey: aws.ToString(creds.SecretKey),
		SessionToken:    aws.ToString(creds.SessionToken),
		Expiration:      expiration,
	}, nil
}

func determineLoginKey(providerType, providerDomain string, claims jwt.Claims) string {
	if providerType == "cognito" {
		// Use issuer from token to ensure case matches
		if iss := claims.GetString("iss"); iss != "" {
			return strings.TrimPrefix(iss, "https://")
		}
		// Fallback: construct from config
		return providerDomain
	}
	return providerDomain
}

// IsRetryableAuthError returns true if the error indicates invalid cached credentials
// that should be cleared.
func IsRetryableAuthError(err error) bool {
	if err == nil {
		return false
	}
	errStr := err.Error()
	patterns := []string{
		"InvalidParameterException",
		"NotAuthorizedException",
		"ValidationError",
		"Invalid AccessKeyId",
		"ExpiredToken",
		"Invalid JWT",
		"Token is not from a supported provider",
	}
	for _, p := range patterns {
		if strings.Contains(errStr, p) {
			return true
		}
	}
	return false
}

// TemporaryEnvClear clears AWS env vars and returns a restore function.
func TemporaryEnvClear() func() {
	vars := []string{"AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}
	saved := make(map[string]string)
	for _, v := range vars {
		if val, ok := os.LookupEnv(v); ok {
			saved[v] = val
			os.Unsetenv(v)
		}
	}
	return func() {
		for k, v := range saved {
			os.Setenv(k, v)
		}
	}
}
