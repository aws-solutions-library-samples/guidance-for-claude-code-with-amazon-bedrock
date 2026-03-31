#!/usr/bin/env bash
# PreToolUse hook: warns before editing critical config files
# Exit 0 = allow, Exit 2 = block

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.filePath // empty' 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Warn (but don't block) on single-source-of-truth files
case "$FILE_PATH" in
  */models.py)
    echo "WARNING: models.py is the single source of truth for Claude model IDs." >&2
    echo "Changes here affect all cross-region profiles and model selection." >&2
    echo "Ensure model ID format: {profile}.anthropic.{model}-{date}-v{version}:0" >&2
    ;;
  */config.py)
    echo "WARNING: config.py defines the profile configuration schema." >&2
    echo "Changes affect all stored profiles in ~/.ccwb/config.json." >&2
    echo "Consider backward compatibility with existing user configs." >&2
    ;;
  */credential_provider/__main__.py)
    echo "WARNING: This is the OAuth2/OIDC credential process." >&2
    echo "Security-critical: handles tokens, credentials, and browser auth." >&2
    echo "Never log tokens or credentials. Test with: poetry run ccwb test" >&2
    ;;
esac

exit 0
