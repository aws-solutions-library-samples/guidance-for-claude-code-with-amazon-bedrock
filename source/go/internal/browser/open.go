package browser

import (
	"os"
	"os/exec"

	"github.com/pkg/browser"
)

// OpenURL opens a URL in the user's default browser.
// Respects $BROWSER env var, which is critical for WSL environments where
// xdg-open opens a Linux browser instead of the Windows host browser.
func OpenURL(url string) error {
	if b := os.Getenv("BROWSER"); b != "" {
		return exec.Command(b, url).Start()
	}
	return browser.OpenURL(url)
}
