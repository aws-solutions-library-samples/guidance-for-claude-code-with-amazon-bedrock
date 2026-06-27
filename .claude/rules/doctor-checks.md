---
description: When adding new config fields or install artifacts, update ccwb doctor
---
- When adding a new binary to the install directory (e.g., otel-helper, otelcol), add a corresponding health check in `commands/doctor.py`
- When adding new config.json fields that affect runtime behavior, consider whether `doctor` should validate their presence
- When adding new settings.json keys, update the settings check to verify them
- Doctor checks must be graceful: missing optional components → SKIP or WARN, not FAIL
- Only FAIL for conditions that will definitely break the user experience
- Keep checks local (no network calls) — doctor runs on user machines without connectivity guarantees
