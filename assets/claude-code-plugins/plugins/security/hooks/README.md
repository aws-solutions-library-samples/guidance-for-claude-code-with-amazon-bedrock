# Security Hooks

This plugin ships two complementary hook configurations. They can be used independently or together.

## `security_gates.json` — advisory file/command validation

The original hooks: `security_check.py` (PreToolUse on Write/Edit/MultiEdit — sensitive-file and secret-in-content checks) and `command_security_check.sh` (PreToolUse on Bash — dangerous-command blocking). See that file's `usage` block.

## `fail_closed_gates.json` — fail-closed enforcement

Adds three enforcement hooks plus a telemetry shim. Every hook is invoked through `hook_wrapper.sh`, which converts a silent hook crash or timeout into an explicit `exit 2` (denial) — a broken control fails *safe*, not *open*.

| Hook | Events | Enforces |
|---|---|---|
| `pii_prompt_guard.sh` | UserPromptSubmit, PreToolUse | Blocks prompts/tool inputs containing secrets (AWS keys, private keys, JWTs, DB connection strings, credit cards) and national identifiers (US SSN/ITIN, UK NINO/NHS, JP My Number, KR RRN, SG NRIC/FIN, EU IBAN, AU TFN/Medicare) **before they reach the model**. Each pattern is individually disable-able. |
| `audit_chain_logger.sh` | UserPromptSubmit, PostToolUse | Tamper-evident **HMAC-SHA256 hash-chained** JSONL audit log. Any post-hoc edit/delete/reorder/insert breaks the chain forward. Optional dual-write to the CloudWatch logging this guidance already provisions. |
| `token_budget_guard.sh` | PreToolUse, PostToolUse | Per-session circuit breaker: blocks further tool calls once a token or call budget is exceeded — a backstop against runaway agent loops. |
| `hook_wrapper.sh` | (wraps the above) | Telemetry + fail-closed shim. |
| `chain_verify.sh` | (operator tool) | Verifies an audit log's hash chain; `exit 0` = intact, `exit 1` = tampered. |

### Quick start

```bash
# 1. Make hooks executable
chmod +x hooks/*.sh

# 2. Provide an HMAC key for the tamper-evident audit chain
export AUDIT_HMAC_KEY="$(openssl rand -hex 32)"   # or provision /etc/claude-code/audit-key

# 3. Reference fail_closed_gates.json hooks from your .claude/settings.json
#    (see the file's usage.setup_instructions)

# 4. Verify the audit chain at any time
bash hooks/chain_verify.sh ~/.claude/claude-code-security/audit.jsonl
```

### CloudWatch dual-write

`audit_chain_logger.sh` can ship audit events to CloudWatch alongside the metrics this guidance already exports:

```bash
export CLAUDE_AUDIT_CLOUDWATCH_GROUP=/aws/claude-code/audit
# instance/user role needs logs:CreateLogStream + logs:PutLogEvents on that group
# optional: export CLAUDE_AUDIT_SIEM_REQUIRED=1   # refuse to run without a working forwarder
```

### Per-project vs. fleet enforcement

Installed per-project, these hooks run with **your** user permissions and can be removed by the user — fine for evaluation and individual developers. For **un-removable, fleet-wide** enforcement, deploy the same hooks via `managed-settings.json` with root-owned paths. The hook logic is identical; only the trust boundary and default paths change.

### Attribution

Contributed via [issue #494](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues/494). Upstream source and a 76-assertion test suite: [timwukp/claude-code-on-aws-bedrock-best-practices](https://github.com/timwukp/claude-code-on-aws-bedrock-best-practices) (Apache-2.0; this copy relicensed MIT-0 to match the repository).
