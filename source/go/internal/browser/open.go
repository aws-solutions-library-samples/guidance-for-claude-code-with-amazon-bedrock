package browser

import (
	"github.com/pkg/browser"
)

// OpenURL opens a URL in the user's default browser.
func OpenURL(url string) error {
	return browser.OpenURL(url)
}
