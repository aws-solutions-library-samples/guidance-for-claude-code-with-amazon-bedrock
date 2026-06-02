// ABOUTME: Platform-specific command execution for Windows.
//go:build windows

package main

import "os/exec"

func newCommand(name string, args ...string) *exec.Cmd {
	return exec.Command(name, args...)
}
