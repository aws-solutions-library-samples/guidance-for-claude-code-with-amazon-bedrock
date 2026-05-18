package azure

import (
	"github.com/99designs/keyring"
)

const serviceName = "claude-code-with-bedrock"

func openKeyring() (keyring.Keyring, error) {
	return keyring.Open(keyring.Config{
		ServiceName:              serviceName,
		KeychainName:             "login",
		KeychainTrustApplication: true,
		LibSecretCollectionName:  serviceName,
		WinCredPrefix:            serviceName,
	})
}

// ReadClientSecret retrieves the client secret from the OS keyring.
func ReadClientSecret(profile string) (string, error) {
	kr, err := openKeyring()
	if err != nil {
		return "", err
	}

	item, err := kr.Get(profile + "-client-secret")
	if err != nil {
		return "", err
	}

	return string(item.Data), nil
}

// SaveClientSecret stores a client secret in the OS keyring.
func SaveClientSecret(profile, secret string) error {
	kr, err := openKeyring()
	if err != nil {
		return err
	}

	return kr.Set(keyring.Item{
		Key:  profile + "-client-secret",
		Data: []byte(secret),
	})
}

// DeleteClientSecret removes the client secret from the OS keyring.
func DeleteClientSecret(profile string) error {
	kr, err := openKeyring()
	if err != nil {
		return err
	}

	return kr.Remove(profile + "-client-secret")
}
