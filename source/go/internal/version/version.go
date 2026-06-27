package version

// Version is set via -ldflags at build time.
var Version = "dev"

// Commit is set via -ldflags at build time (short SHA).
var Commit = "unknown"
