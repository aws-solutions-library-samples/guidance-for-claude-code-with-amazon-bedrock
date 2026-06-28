# Breaking Change Checklist

Run this checklist before submitting any PR that touches **Tier 1** files
(config.py, deploy.py, credential-process, otel-helper, bedrock-auth-*.yaml).

## Backward Compatibility

- [ ] Old `profile.json` files (without the new field) still load without error
- [ ] New config fields have default values that preserve existing behavior
- [ ] Existing CLI commands still work with no arguments (no new required params)
- [ ] Deployed stacks can be updated in-place (no resource replacement that breaks state)

## Cross-Component Parity

- [ ] Python `config.py` field mirrored in Go `config.go` (or justified skip)
- [ ] `--explain` JSON output updated if config shape changed
- [ ] `package.py` and `distribute.py` agree on binary names (contract test passes)
- [ ] Changes in deploy affect `VALID_STACKS`/`DESTROYABLE_STACKS` if new stack added

## Auth Mode Coverage

- [ ] Tested with **OIDC** (JWT Bearer token flow)
- [ ] Tested with **IDC** (IAM SigV4, no JWT)
- [ ] Tested with **none** (anonymous, hashed principal)
- [ ] Graceful error if feature requires a specific auth mode (not silent failure)

## Platform Coverage

- [ ] Windows CI passes (filepath, .exe resolution, PowerShell compat)
- [ ] macOS works (Keychain access, launchd paths)
- [ ] Linux works (no macOS-specific APIs assumed)

## Testing

- [ ] Regression test: fails without fix, passes with fix
- [ ] Edge cases: empty strings, None values, missing env vars
- [ ] Non-interactive mode works (no uncaught `questionary` or `input()` calls)

## CFN-Specific (if touching templates)

- [ ] `!Sub "arn:${AWS::Partition}:..."` (never hardcode `arn:aws:`)
- [ ] Conditions use positive names (`HasX`, not `NoX`)
- [ ] New parameters have `Default` values
- [ ] One route resource per route-key (no duplicate route conflicts)
- [ ] IAM actions are exact (no wildcards), scoped to specific resources
- [ ] `cfn-lint` passes on modified templates

## Pre-Push Verification

```bash
# Python
cd source && ruff check . && ruff format --check . && poetry run pytest tests/ -q

# Go
cd source/go && go test ./... -race -count=1 && go vet ./...

# CFN
cfn-lint deployment/infrastructure/*.yaml
```
