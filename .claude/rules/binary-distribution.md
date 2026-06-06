# Binary Distribution

## Rule
- macOS: Gatekeeper quarantines unsigned binaries
- Windows: Defender/SmartScreen blocks unsigned
- Cold start target: <100ms (Go binary)
- Don't add heavy imports that regress startup

## Why
Unsigned binaries trigger security warnings and performance issues. Users expect fast startup times for credential processes.

## Platform-Specific Issues
- **macOS:** Unsigned binaries get quarantined by Gatekeeper. Document `xattr -cr` workaround.
- **Windows:** Unsigned PyInstaller executables trigger Defender/SmartScreen. Document exclusion path.
- **Performance:** Heavy Python imports regressed cold start from <100ms to 10s with PyInstaller.

## Solutions
- Use Go binary for credential process (fast startup)
- Document security exclusion procedures
- Avoid heavy imports in performance-critical paths
- Target <100ms cold start time

## Related Issues
#27, #145, #223, #237, #395