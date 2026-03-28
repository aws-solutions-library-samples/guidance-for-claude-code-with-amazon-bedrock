package federation

import (
	"context"
	"fmt"
	"strings"

	"credential-process-go/internal/config"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/cognitoidentity"
	"github.com/golang-jwt/jwt/v5"
)

// getLoginKey determines the Cognito Identity login key based on provider configuration.
func getLoginKey(cfg *config.ProfileConfig, claims jwt.MapClaims) string {
	if cfg.ProviderType == "cognito" {
		// Try iss claim first, strip https://
		if iss, ok := claims["iss"].(string); ok && iss != "" {
			loginKey := strings.TrimPrefix(iss, "https://")
			loginKey = strings.TrimPrefix(loginKey, "http://")
			return loginKey
		}
		// Fallback: construct from cognito_user_pool_id
		if cfg.CognitoUserPoolID != "" {
			// Format: cognito-idp.{region}.amazonaws.com/{pool_id}
			parts := strings.SplitN(cfg.CognitoUserPoolID, "_", 2)
			if len(parts) == 2 {
				region := parts[0]
				return fmt.Sprintf("cognito-idp.%s.amazonaws.com/%s", region, cfg.CognitoUserPoolID)
			}
		}
	}

	// Default: use provider_domain
	return cfg.ProviderDomain
}

// getCredentialsCognito uses Cognito Identity Pool to obtain AWS credentials.
func getCredentialsCognito(cfg *config.ProfileConfig, idToken string, claims jwt.MapClaims, debug bool) (map[string]interface{}, error) {
	// Clear AWS env vars to prevent interference
	restore := clearAWSEnvVars()
	defer restore()

	ctx := context.Background()

	debugLog(debug, "Using Cognito Identity Pool federation: %s", cfg.IdentityPoolID)

	// Determine the login key
	loginKey := getLoginKey(cfg, claims)
	debugLog(debug, "Cognito login key: %s", loginKey)

	logins := map[string]string{
		loginKey: idToken,
	}

	// Create Cognito Identity client with anonymous credentials (no signing needed)
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx,
		awsconfig.WithRegion(cfg.AWSRegion),
		awsconfig.WithCredentialsProvider(aws.NewCredentialsCache(
			credentials.NewStaticCredentialsProvider("", "", ""),
		)),
	)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	// Use anonymous credentials for the Cognito Identity client
	cognitoClient := cognitoidentity.NewFromConfig(awsCfg, func(o *cognitoidentity.Options) {
		o.Credentials = aws.AnonymousCredentials{}
	})

	// Step 1: GetId
	debugLog(debug, "Calling Cognito GetId for identity pool: %s", cfg.IdentityPoolID)
	getIdOutput, err := cognitoClient.GetId(ctx, &cognitoidentity.GetIdInput{
		IdentityPoolId: aws.String(cfg.IdentityPoolID),
		Logins:         logins,
	})
	if err != nil {
		if isInvalidCredentialError(err) {
			return nil, wrapCredentialError(err)
		}
		return nil, fmt.Errorf("Cognito GetId failed: %w", err)
	}

	identityID := aws.ToString(getIdOutput.IdentityId)
	debugLog(debug, "Obtained Cognito identity ID: %s", identityID)

	// Step 2: GetCredentialsForIdentity
	debugLog(debug, "Calling Cognito GetCredentialsForIdentity")
	credsOutput, err := cognitoClient.GetCredentialsForIdentity(ctx, &cognitoidentity.GetCredentialsForIdentityInput{
		IdentityId: aws.String(identityID),
		Logins:     logins,
	})
	if err != nil {
		if isInvalidCredentialError(err) {
			return nil, wrapCredentialError(err)
		}
		return nil, fmt.Errorf("Cognito GetCredentialsForIdentity failed: %w", err)
	}

	// Note: Cognito returns SecretKey, not SecretAccessKey
	creds := map[string]interface{}{
		"Version":         1,
		"AccessKeyId":     aws.ToString(credsOutput.Credentials.AccessKeyId),
		"SecretAccessKey": aws.ToString(credsOutput.Credentials.SecretKey),
		"SessionToken":    aws.ToString(credsOutput.Credentials.SessionToken),
		"Expiration":      credsOutput.Credentials.Expiration.Format("2006-01-02T15:04:05Z"),
	}

	debugLog(debug, "Successfully obtained Cognito credentials, expiring: %s", creds["Expiration"])

	return creds, nil
}
