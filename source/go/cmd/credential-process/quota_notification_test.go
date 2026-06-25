package main

// ABOUTME: Regression tests for the quota browser notification exit race.
// ABOUTME: The server must outlive credential output and stay reachable until
// ABOUTME: the browser connects — previously os.Exit killed it first (refused).

import (
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"ccwb-go/internal/quota"
)

// TestMain installs a no-op browser opener for the whole test binary so that
// tests touching the quota notification path (e.g. printQuotaWarning in
// quota_warning_test.go) never launch a real browser on a developer machine
// where isHeadless() returns false. Individual tests may still override
// openBrowserFunc via setupNotificationTest; they restore it to this no-op.
func TestMain(m *testing.M) {
	openBrowserFunc = func(string) {}
	os.Exit(m.Run())
}

// resetPending clears global notification state and installs a no-op browser
// opener so tests never launch a real browser. It returns a cleanup func.
func setupNotificationTest(t *testing.T) {
	t.Helper()
	pendingMu.Lock()
	pendingNotifs = nil
	pendingMu.Unlock()

	origOpen := openBrowserFunc
	origTimeout := notificationWaitTimeout
	origHeadless := isHeadlessFunc
	openBrowserFunc = func(string) {}             // no real browser
	isHeadlessFunc = func() bool { return false } // force non-headless (CI has no DISPLAY)
	notificationWaitTimeout = 2 * time.Second

	t.Cleanup(func() {
		openBrowserFunc = origOpen
		notificationWaitTimeout = origTimeout
		isHeadlessFunc = origHeadless
		pendingMu.Lock()
		pendingNotifs = nil
		pendingMu.Unlock()
	})
}

func warningResult() *quota.Result {
	return &quota.Result{
		Allowed: true,
		Reason:  "within_limits",
		Message: "Access granted - enforcement mode is alert-only",
		Usage: map[string]interface{}{
			"monthly_percent": float64(22),
			"daily_percent":   float64(153),
			"monthly_tokens":  float64(8826347),
			"monthly_limit":   float64(40000000),
			"daily_tokens":    float64(8438308),
			"daily_limit":     float64(5500000),
		},
	}
}

func pendingURL(t *testing.T) string {
	t.Helper()
	pendingMu.Lock()
	defer pendingMu.Unlock()
	if len(pendingNotifs) != 1 {
		t.Fatalf("expected exactly 1 pending notification, got %d", len(pendingNotifs))
	}
	return pendingNotifs[0].url
}

// TestNotificationServerReachableAfterReturn is the core regression test:
// after showQuotaBrowserNotification returns (credentials would already be on
// stdout at this point), the server must still be reachable. The old
// fire-and-forget implementation only kept the socket alive for a 100ms sleep
// and then lost it to os.Exit, producing ERR_CONNECTION_REFUSED.
func TestNotificationServerReachableAfterReturn(t *testing.T) {
	setupNotificationTest(t)

	showQuotaBrowserNotification(warningResult(), false)
	url := pendingURL(t)

	// Simulate the real browser connecting AFTER the function returned. The
	// server must answer rather than refuse the connection.
	resp, err := http.Get(url)
	if err != nil {
		t.Fatalf("server should be reachable after return, got: %v", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if !strings.Contains(string(body), "Quota Warning") {
		t.Errorf("expected quota page HTML, got: %q", string(body))
	}

	// The wait must now return promptly because the page was served.
	done := make(chan struct{})
	go func() { waitForQuotaNotification(); close(done) }()
	select {
	case <-done:
	case <-time.After(notificationWaitTimeout + time.Second):
		t.Fatal("waitForQuotaNotification did not return after page was served")
	}
}

// TestWaitTimesOutWhenBrowserNeverConnects verifies the exit path does not hang
// forever when the browser never fetches the page — it must fall back to the
// timeout and shut down.
func TestWaitTimesOutWhenBrowserNeverConnects(t *testing.T) {
	setupNotificationTest(t)
	notificationWaitTimeout = 200 * time.Millisecond

	showQuotaBrowserNotification(warningResult(), false)
	_ = pendingURL(t) // server started, but we never connect

	start := time.Now()
	waitForQuotaNotification()
	elapsed := time.Since(start)

	if elapsed < notificationWaitTimeout {
		t.Errorf("wait returned too early (%v), expected to block ~%v", elapsed, notificationWaitTimeout)
	}
	if elapsed > 2*time.Second {
		t.Errorf("wait blocked too long (%v), timeout not honored", elapsed)
	}
}

// TestReloadDoesNotPanic verifies a browser reload (a second GET to the served
// page) does not double-close the served channel and panic.
func TestReloadDoesNotPanic(t *testing.T) {
	setupNotificationTest(t)

	showQuotaBrowserNotification(warningResult(), false)
	url := pendingURL(t)

	for i := 0; i < 3; i++ {
		resp, err := http.Get(url)
		if err != nil {
			t.Fatalf("request %d failed: %v", i, err)
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}

	waitForQuotaNotification() // must not panic
}

// TestOptOutSkipsServer verifies CCWB_NO_BROWSER_NOTIFICATION=1 starts no server.
func TestOptOutSkipsServer(t *testing.T) {
	setupNotificationTest(t)
	t.Setenv("CCWB_NO_BROWSER_NOTIFICATION", "1")

	showQuotaBrowserNotification(warningResult(), false)

	pendingMu.Lock()
	n := len(pendingNotifs)
	pendingMu.Unlock()
	if n != 0 {
		t.Errorf("opt-out should start no notification, got %d pending", n)
	}
	waitForQuotaNotification() // no-op, must not block or panic
}

// TestNilUsageSkipsServer verifies a nil usage map starts no server.
func TestNilUsageSkipsServer(t *testing.T) {
	setupNotificationTest(t)

	showQuotaBrowserNotification(&quota.Result{Allowed: true, Usage: nil}, false)

	pendingMu.Lock()
	n := len(pendingNotifs)
	pendingMu.Unlock()
	if n != 0 {
		t.Errorf("nil usage should start no notification, got %d pending", n)
	}
}

// TestWaitWithNoPendingIsNoop verifies the exit path is safe when no
// notification was ever shown (the common case).
func TestWaitWithNoPendingIsNoop(t *testing.T) {
	setupNotificationTest(t)

	var wg sync.WaitGroup
	wg.Add(1)
	go func() { defer wg.Done(); waitForQuotaNotification() }()

	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("waitForQuotaNotification blocked with nothing pending")
	}
}
