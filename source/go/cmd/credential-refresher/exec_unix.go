// ABOUTME: Platform-specific command execution for credential-refresher.
// ABOUTME: Separated to allow build-tag overrides for Windows if needed.
//go:build !windows

package main

import "os/exec"

func newCommand(name string, args ...string) *exec.Cmd {
	return exec.Command(name, args...)
}
