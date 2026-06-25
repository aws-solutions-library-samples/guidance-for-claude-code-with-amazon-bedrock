package main

// ABOUTME: Browser-based quota notification for visual feedback.
// ABOUTME: Serves an HTML page on localhost with progress bars showing quota usage.
// ABOUTME: Parity with Python credential-provider's _show_quota_browser_notification.

import (
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"time"

	"ccwb-go/internal/quota"
)

// pendingNotification holds a quota-status server that has been started and had
// its browser opened, but whose page may not yet have been fetched.
type pendingNotification struct {
	server *http.Server
	served chan struct{}
	url    string // for tests/diagnostics
}

var (
	pendingMu     sync.Mutex
	pendingNotifs []*pendingNotification

	// notificationWaitTimeout bounds how long the process lingers at exit
	// waiting for the browser to fetch the quota page. Mirrors the Python
	// implementation's server.timeout = 5. Var (not const) so tests can shrink it.
	notificationWaitTimeout = 5 * time.Second

	// openBrowserFunc is the indirection point for opening a browser, so tests
	// can substitute a no-op instead of launching a real browser.
	openBrowserFunc = openBrowser

	// isHeadlessFunc is the indirection point for headless detection, so tests
	// can force a non-headless environment regardless of CI's DISPLAY/SSH vars.
	isHeadlessFunc = isHeadless
)

// showQuotaBrowserNotification starts a localhost server showing quota status
// and opens the browser to it. It does NOT wait for the page to be fetched —
// the caller must invoke waitForQuotaNotification() before the process exits.
//
// Why this split: credential-process exits via os.Exit, which kills every
// goroutine immediately. A fire-and-forget server raced the process exit, so
// the browser frequently hit the socket after it was already gone and showed
// ERR_CONNECTION_REFUSED. By binding the listener synchronously here (the
// socket accepts connections into the kernel backlog the instant net.Listen
// returns) and deferring the wait to the exit path — after credentials are
// already on stdout — the server stays alive until the browser connects,
// without ever delaying credential delivery.
//
// Skipped when:
// - CCWB_NO_BROWSER_NOTIFICATION=1 is set
// - Running in a headless environment (no DISPLAY, SSH_CONNECTION set)
// - Usage data is nil
func showQuotaBrowserNotification(qr *quota.Result, isBlocked bool) {
	// Opt-out via environment variable
	if os.Getenv("CCWB_NO_BROWSER_NOTIFICATION") == "1" {
		debugPrint("Browser notification skipped (CCWB_NO_BROWSER_NOTIFICATION=1)")
		return
	}

	// Skip in headless environments
	if isHeadlessFunc() {
		debugPrint("Browser notification skipped (headless environment detected)")
		return
	}

	usage := qr.Usage
	if usage == nil {
		return
	}

	html := buildQuotaHTML(usage, qr.Message, isBlocked)

	// Bind the listener synchronously (8401 preferred, matching Python). Binding
	// before opening the browser is what closes the connection race: the socket
	// queues the browser's connection even before Serve() is scheduled.
	listener, err := net.Listen("tcp", "127.0.0.1:8401")
	if err != nil {
		// Try any available port
		listener, err = net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			debugPrint("Could not start quota notification server: %v", err)
			return
		}
	}

	port := listener.Addr().(*net.TCPAddr).Port
	served := make(chan struct{})
	var once sync.Once

	mux := http.NewServeMux()
	mux.HandleFunc("/quota-status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.Write([]byte(html))
		// once: a browser reload would hit this handler again; closing a
		// channel twice panics.
		once.Do(func() { close(served) })
	})

	server := &http.Server{Handler: mux}
	go server.Serve(listener)

	// Open browser
	url := fmt.Sprintf("http://localhost:%d/quota-status", port)
	openBrowserFunc(url)

	pendingMu.Lock()
	pendingNotifs = append(pendingNotifs, &pendingNotification{server: server, served: served, url: url})
	pendingMu.Unlock()
}

// waitForQuotaNotification blocks until any pending quota page has been fetched
// by the browser (or notificationWaitTimeout elapses), then shuts the server(s)
// down. Call this immediately before the process exits: credentials are already
// on stdout by then, so this only delays process teardown, never the AWS SDK.
func waitForQuotaNotification() {
	pendingMu.Lock()
	notifs := pendingNotifs
	pendingNotifs = nil
	pendingMu.Unlock()

	for _, n := range notifs {
		select {
		case <-n.served:
		case <-time.After(notificationWaitTimeout):
			debugPrint("Browser notification timed out")
		}
		n.server.Close()
	}
}

// isHeadless returns true if the environment appears to be headless (no GUI).
func isHeadless() bool {
	// SSH session — no local display
	if os.Getenv("SSH_CONNECTION") != "" || os.Getenv("SSH_TTY") != "" {
		return true
	}

	// Linux/Unix: check for display server
	if runtime.GOOS == "linux" {
		if os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == "" {
			return true
		}
	}

	// Windows and macOS always have a GUI available (if logged in)
	return false
}

func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	_ = cmd.Start()
}

func buildQuotaHTML(usage map[string]interface{}, message string, isBlocked bool) string {
	monthlyPercent, _ := usage["monthly_percent"].(float64)
	dailyPercent, _ := usage["daily_percent"].(float64)
	monthlyTokens, _ := usage["monthly_tokens"].(float64)
	monthlyLimit, _ := usage["monthly_limit"].(float64)
	dailyTokens, _ := usage["daily_tokens"].(float64)
	dailyLimit, _ := usage["daily_limit"].(float64)

	statusEmoji := "⚠️"
	statusText := "Quota Warning"
	statusColor := "#ffc107"
	headerBg := "#fff3cd"
	if isBlocked {
		statusEmoji = "🚫"
		statusText = "Access Blocked"
		statusColor = "#dc3545"
		headerBg = "#f8d7da"
	}

	barColor := func(pct float64) string {
		if pct >= 100 {
			return "#dc3545"
		} else if pct >= 90 {
			return "#fd7e14"
		} else if pct >= 80 {
			return "#ffc107"
		}
		return "#28a745"
	}

	clamp := func(v float64) float64 {
		if v > 100 {
			return 100
		}
		return v
	}

	var dailySection string
	if dailyLimit > 0 {
		dailySection = fmt.Sprintf(`
		<div class="usage-section">
			<div class="usage-label">
				<span>Daily Usage</span>
				<span class="usage-value">%s / %s (%.0f%%)</span>
			</div>
			<div class="progress-bar">
				<div class="progress-fill" style="width: %.0f%%; background: %s;"></div>
			</div>
		</div>`,
			humanizeNumber(int64(dailyTokens)), humanizeNumber(int64(dailyLimit)),
			dailyPercent, clamp(dailyPercent), barColor(dailyPercent))
	}

	var messageSection string
	if message != "" {
		messageSection = fmt.Sprintf(`<p class="message">%s</p>`, message)
	}

	var b strings.Builder
	fmt.Fprintf(&b, `<!DOCTYPE html>
<html>
<head>
    <title>Quota Status - Claude Code</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 40px; background: #f5f5f5; }
        .container { max-width: 500px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden; }
        .header { background: %s; padding: 30px; text-align: center; border-bottom: 1px solid rgba(0,0,0,0.1); }
        .header h1 { margin: 0; color: %s; font-size: 28px; }
        .content { padding: 30px; }
        .usage-section { margin-bottom: 25px; }
        .usage-label { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 14px; color: #666; }
        .usage-value { font-weight: 600; color: #333; }
        .progress-bar { height: 24px; background: #e9ecef; border-radius: 12px; overflow: hidden; }
        .progress-fill { height: 100%%; border-radius: 12px; transition: width 0.3s; }
        .message { color: #666; font-size: 14px; margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px; }
        .footer { text-align: center; padding: 15px; color: #999; font-size: 12px; }
    </style>
</head>
<body>
<div class="container">
    <div class="header"><h1>%s %s</h1></div>
    <div class="content">
        <div class="usage-section">
            <div class="usage-label">
                <span>Monthly Usage</span>
                <span class="usage-value">%s / %s (%.0f%%)</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: %.0f%%; background: %s;"></div>
            </div>
        </div>
        %s
        %s
    </div>
    <div class="footer">Claude Code with Amazon Bedrock — Quota Monitor</div>
</div>
</body>
</html>`,
		headerBg, statusColor,
		statusEmoji, statusText,
		humanizeNumber(int64(monthlyTokens)), humanizeNumber(int64(monthlyLimit)),
		monthlyPercent, clamp(monthlyPercent), barColor(monthlyPercent),
		dailySection, messageSection)

	return b.String()
}
