// ABOUTME: Unix process helpers for collector sidecar management —
// ABOUTME: liveness check via signal 0 and session detach via Setsid.
//go:build !windows

package main

import "syscall"

// isProcessAlive reports whether a process with the given PID exists.
// EPERM means the process exists but belongs to another user — still alive.
func isProcessAlive(pid int) bool {
	err := syscall.Kill(pid, 0)
	return err == nil || err == syscall.EPERM
}

// detachedSysProcAttr detaches the collector into its own session so it
// survives the short-lived otel-helper process exiting.
func detachedSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setsid: true}
}
