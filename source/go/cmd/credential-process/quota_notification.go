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
	"time"

	"ccwb-go/internal/quota"
)

// showQuotaBrowserNotification opens a browser window showing quota status.
// Runs asynchronously (goroutine) to avoid blocking credential output.
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
	if isHeadless() {
		debugPrint("Browser notification skipped (headless environment detected)")
		return
	}

	usage := qr.Usage
	if usage == nil {
		return
	}

	// Run asynchronously to avoid blocking credential output
	go func() {
		html := buildQuotaHTML(usage, qr.Message, isBlocked)

		// Find an available port (8401 preferred, matching Python implementation)
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

		mux := http.NewServeMux()
		mux.HandleFunc("/quota-status", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.Write([]byte(html))
			close(served)
		})

		server := &http.Server{Handler: mux}
		go server.Serve(listener)

		// Open browser
		url := fmt.Sprintf("http://localhost:%d/quota-status", port)
		openBrowser(url)

		// Wait for page to be served or timeout after 5 seconds
		select {
		case <-served:
		case <-time.After(5 * time.Second):
			debugPrint("Browser notification timed out")
		}

		server.Close()
	}()

	// Give the goroutine a moment to start the server before the process might exit
	time.Sleep(100 * time.Millisecond)
}

// isHeadless returns true if the environment appears to have no usable local
// browser — i.e. we should show a copy-to-another-device prompt rather than try
// to open a browser. Used by both the quota browser-notification flow and the
// IDC device-authorization flow.
func isHeadless() bool {
	// An explicit $BROWSER means the user has told us how to open a browser
	// (e.g. WSL forwarding to the Windows host) — honor it.
	if os.Getenv("BROWSER") != "" {
		return false
	}
	// SSH session — no local display, on any OS.
	if os.Getenv("SSH_CONNECTION") != "" || os.Getenv("SSH_TTY") != "" || os.Getenv("SSH_CLIENT") != "" {
		return true
	}
	switch runtime.GOOS {
	case "windows", "darwin":
		// Assume a desktop browser unless in an SSH session (handled above).
		return false
	default:
		// Linux/BSD: a GUI session exposes DISPLAY (X11) or WAYLAND_DISPLAY.
		return os.Getenv("DISPLAY") == "" && os.Getenv("WAYLAND_DISPLAY") == ""
	}
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
