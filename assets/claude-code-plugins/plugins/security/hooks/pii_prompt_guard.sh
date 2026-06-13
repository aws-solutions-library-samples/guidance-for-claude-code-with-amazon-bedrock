#!/bin/bash
# =============================================================================
# PII & Secrets Guard Hook for Claude Code
# =============================================================================
# Hook version: 2.0.1
# Last updated: 2026-06-01
# Compatible with: claude-code 2.1.150+
# Dependencies: bash 4+, jq (preferred), grep, sed
# Maintainer: AWS Solutions Library (contributed via #494)
# Change log:
#   2.0.1 (2026-06-01) — fix false positive: hyphenated UUID segments no longer
#                         match CREDIT_CARD_16/AMEX or JP_MYNUMBER (boundary
#                         classes now exclude '-')
#   2.0.0 (2026-06-01) — multi-country national identifiers: US (SSN/ITIN),
#                         UK (NINO, NHS), Japan (My Number), South Korea (RRN),
#                         Singapore (NRIC/FIN), EU (IBAN), Australia (TFN, Medicare)
#   1.0.0 (2026-05-28) — initial release: 15 PII/secret patterns
# =============================================================================
# Note on false positives: purely-numeric national IDs (e.g. JP My Number,
# AU TFN/Medicare) are matched in their conventional separator-grouped form to
# limit false positives, since ERE (grep -E) has no lookahead. All patterns are
# configurable — comment out any LABEL:::REGEX line below to disable a region.
# =============================================================================
# Scans user prompts and tool inputs for sensitive data BEFORE they reach the
# model. Blocks the request if PII or secrets are detected.
#
# Hook events supported:
#   - UserPromptSubmit: scans user prompt text
#   - PreToolUse: scans tool_input (file content being written, commands, etc.)
#
# Exit codes:
#   0 = clean, allow through
#   2 = sensitive data detected, BLOCK (stderr shown to user)
#
# Default deploy: referenced from security_gates.json via $CLAUDE_PROJECT_DIR/hooks/
# Ownership: root:root 0755
# =============================================================================

set -u
input=$(cat)

# Extract the text to scan based on hook event
if command -v jq >/dev/null 2>&1; then
  event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
  case "$event" in
    UserPromptSubmit)
      text=$(printf '%s' "$input" | jq -r '.prompt // empty')
      ;;
    PreToolUse)
      # Scan the entire tool_input as a string (catches file content, commands, etc.)
      text=$(printf '%s' "$input" | jq -r '.tool_input | tostring')
      ;;
    *)
      exit 0
      ;;
  esac
else
  # Fallback without jq: scan entire input
  text="$input"
fi

# If text is empty or too short, skip
if [[ ${#text} -lt 8 ]]; then
  exit 0
fi

# =============================================================================
# DETECTION PATTERNS
# Each pattern: "LABEL:::REGEX"
# =============================================================================
patterns=(
  # Credit card numbers — Visa/MC/Discover/JCB (16 digit, 4-4-4-4) and Amex (15 digit, 4-6-5)
  # Standard: ISO/IEC 7812-1 (issuer numbering + Luhn/mod-10 check); industry rule PCI DSS.
  # Boundaries exclude '-' so hyphenated UUID segments (8-4-4-4-12) don't false-match.
  "CREDIT_CARD_16:::(^|[^0-9-])[3-6][0-9]{3}[- ]?[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}([^0-9-]|$)"
  "CREDIT_CARD_AMEX:::(^|[^0-9-])3[47][0-9]{2}[- ]?[0-9]{6}[- ]?[0-9]{5}([^0-9-]|$)"

  # AWS Access Key ID
  "AWS_ACCESS_KEY:::AKIA[0-9A-Z]{16}"

  # AWS Secret Access Key (40 chars base64-ish after common prefixes)
  "AWS_SECRET_KEY:::['\"][0-9a-zA-Z/+=]{40}['\"]"

  # Generic API key patterns. NOTE: putting '-' at end of class avoids ERE range parse.
  "API_KEY_ASSIGNMENT:::(api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token|secret[_-]?key)[ ]*[:=][ ]*['\"]?[A-Za-z0-9_/.+=-]{20,}['\"]?"

  # Private key header
  "PRIVATE_KEY:::-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"

  # JWT token (3 base64url segments separated by dots). '-' placed at end of class.
  "JWT_TOKEN:::eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"

  # Database connection strings
  "DB_CONNECTION_STRING:::(mongodb(\+srv)?|postgres(ql)?|mysql|mssql|redis|amqp)://[^ '\"]{10,}"

  # Password in common assignment formats
  "PASSWORD_ASSIGNMENT:::(password|passwd|pwd|pass)[ ]*[:=][ ]*['\"]?[^ '\"]{8,}['\"]?"

  # --- National identifiers (multi-country) --------------------------------
  # Each line can be disabled by commenting it out. Format authority cited per
  # region (the body that issues/defines the number). Full compliance mapping
  # (data-protection & financial regulators) is in README.md. These patterns
  # validate FORMAT only (digit count / grouping), not government check-digit
  # algorithms — several of which (AU TFN/Medicare, SG NRIC, KR RRN) are not
  # officially published. Links are official sources; re-verify before relying.

  # United States — SSN (AAA-GG-SSSS), no check digit.
  # Authority: Social Security Administration — ssa.gov/employer/structure.html
  # (legal basis 20 CFR 422.103). Require grouping to avoid bare 9-digit IDs.
  "US_SSN:::(^|[^0-9])[0-9]{3}[- ][0-9]{2}[- ][0-9]{4}([^0-9]|$)"
  # United States — ITIN (9XX-7X/8X-XXXX).
  # Authority: IRS, Instructions for Form W-7 — irs.gov/instructions/iw7
  "US_ITIN:::(^|[^0-9])9[0-9]{2}[- ](7[0-9]|8[0-8])[- ][0-9]{4}([^0-9]|$)"

  # United Kingdom — National Insurance Number (2 letters, 6 digits, suffix A-D).
  # Authority: HMRC/DWP via GOV.UK — gov.uk/national-insurance/your-national-insurance-number
  "UK_NINO:::(^|[^A-Za-z0-9])[A-CEGHJ-PR-TW-Z]{2}[0-9]{6}[A-D]([^A-Za-z0-9]|$)"
  # United Kingdom — NHS number (10 digits, 3-3-4; Modulus-11 check, published).
  # Authority: NHS England Data Dictionary — datadictionary.nhs.uk/attributes/nhs_number.html
  "UK_NHS:::(^|[^0-9])[0-9]{3}[- ][0-9]{3}[- ][0-9]{4}([^0-9]|$)"

  # Japan — My Number (個人番号), 12 digits, conventionally grouped 4-4-4.
  # Authority: Digital Agency / J-LIS — digital.go.jp/policies/mynumber
  # Boundaries exclude '-' so hyphenated UUID segments don't false-match.
  "JP_MYNUMBER:::(^|[^0-9-])[0-9]{4}[- ][0-9]{4}[- ][0-9]{4}([^0-9-]|$)"

  # South Korea — Resident Registration Number (RRN), YYMMDD-Sxxxxxx (13 digits).
  # Authority: Ministry of the Interior and Safety (MOIS) — mois.go.kr
  "KR_RRN:::(^|[^0-9])[0-9]{6}[- ][1-4][0-9]{6}([^0-9]|$)"

  # Singapore — NRIC/FIN (prefix + 7 digits + check letter).
  # Authority: Immigration & Checkpoints Authority (ICA) — ica.gov.sg
  "SG_NRIC:::[STFGM][0-9]{7}[A-Z]"

  # European Union — IBAN (country code + 2 check digits + BBAN; mod-97 published).
  # Standard: ISO 13616, registry by SWIFT — swift.com/standards/data-standards/iban-international-bank-account-number
  "EU_IBAN:::(^|[^A-Za-z0-9])(AT|BE|BG|HR|CY|CZ|DK|EE|FI|FR|DE|GR|HU|IE|IT|LV|LT|LU|MT|NL|PL|PT|RO|SK|SI|ES|SE)[0-9]{2}[ ]?([0-9A-Z]{4}[ ]?){2,7}[0-9A-Z]{1,4}"

  # Australia — Tax File Number (8-9 digits, 3-3-3) and Medicare (10 digits, 4-5-1).
  # Authority: Australian Taxation Office — ato.gov.au/individuals-and-families/tax-file-number
  #            Services Australia — servicesaustralia.gov.au/your-medicare-card
  "AU_TFN:::(^|[^0-9])[0-9]{3}[- ][0-9]{3}[- ][0-9]{3}([^0-9]|$)"
  "AU_MEDICARE:::(^|[^0-9])[0-9]{4}[- ][0-9]{5}[- ][0-9]([^0-9]|$)"

  # Email
  "EMAIL_ADDRESS:::[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"

  # Phone numbers (international, allows internal spaces or hyphens between digit groups)
  "PHONE_INTL:::\+[0-9]{1,3}([-. ][0-9]{2,5}){2,4}"

  # Passport numbers
  "PASSPORT_NUMBER:::[A-Z]{1,2}[0-9]{6,9}"

  # GitHub/GitLab tokens
  "GIT_TOKEN:::(ghp_[A-Za-z0-9]{36}|glpat-[A-Za-z0-9-]{20,})"

  # Slack tokens
  "SLACK_TOKEN:::xox[bpras]-[0-9]{10,}-[A-Za-z0-9-]+"

  # Generic hex secrets — 32+ hex chars containing at least one a-f letter
  # (rejects pure-decimal IDs and 0b binary literals which would otherwise match [0-9a-f]+).
  "HEX_SECRET:::(^|[^A-Za-z0-9_])[0-9a-f]*[a-f][0-9a-f]*[a-f][0-9a-f]{28,}([^A-Za-z0-9_]|$)"
)

# =============================================================================
# SCAN
# =============================================================================
detected=()

for entry in "${patterns[@]}"; do
  label="${entry%%:::*}"
  regex="${entry#*:::}"
  # Identifiers whose letters are defined uppercase — match case-sensitive to
  # avoid e.g. lowercase IBAN country prefixes inflating false positives.
  case "$label" in
    PASSPORT_NUMBER|SG_NRIC|AWS_ACCESS_KEY|UK_NINO|EU_IBAN)
      if echo "$text" | grep -qE -- "$regex"; then
        detected+=("$label")
      fi
      ;;
    *)
      if echo "$text" | grep -qiE -- "$regex"; then
        detected+=("$label")
      fi
      ;;
  esac
done

# =============================================================================
# RESULT
# =============================================================================
if [[ ${#detected[@]} -gt 0 ]]; then
  matches=$(IFS=', '; echo "${detected[*]}")
  cat >&2 <<EOF
🚨 PII/SECRETS GUARD: Sensitive data detected — request BLOCKED before reaching the model.

Detected patterns: $matches

This content contains what appears to be sensitive information (credentials,
PII, or secrets). To protect against data leakage, this request has been
blocked at the hook layer and was NOT sent to the AI model.

Actions:
  • Remove the sensitive data from your prompt or file content
  • Use environment variables or secret references instead of literal values
  • If this is a false positive, contact your IT security team to adjust
    the detection patterns in the PII guard hook

Hook: pii_prompt_guard.sh | Event: $event
EOF
  exit 2
fi

exit 0
