## Description

<!-- Provide a clear and concise description of what this PR does -->

## Why is this change needed

<!-- Why is this change needed? What problem does it solve? -->
<!-- If it fixes an open issue, please link to the issue here -->

Fixes # (issue)

## Type of Change

<!-- Check all that apply -->

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Infrastructure/deployment change
- [ ] Dependency update
- [ ] Refactoring (no functional changes)
- [ ] CI/CD changes

## Changes Made

<!-- List the key changes in this PR -->

- 
- 
- 

## Breaking Changes

<!-- If this introduces breaking changes, describe them here -->

- [ ] No breaking changes
- [ ] Breaking changes described below

<!-- 
If breaking changes:
- What breaks?
- How to migrate?
- Rollback plan?
-->

## Documentation

<!-- Check all that apply -->

- [ ] Updated relevant documentation (README, QUICK_START, guides, etc.)
- [ ] Updated CHANGELOG.md (if user-facing change)
- [ ] Updated version in `source/pyproject.toml` (if applicable)
- [ ] Added/updated code comments and docstrings
- [ ] No documentation changes needed

## Screenshots / Logs

<!-- If applicable, add screenshots or logs to help explain your changes -->

## Additional Notes

<!-- Any additional context, concerns, or areas requiring special review attention -->

---

## Testing Checklist

<!-- 
IMPORTANT: To prevent breaking changes, all PRs affecting code must include testing evidence.
Please check all applicable items and attach screenshots/logs as proof of testing.

Documentation-only PRs are exempt from testing requirements.
-->

### Automated Tests

- [ ] All existing tests pass locally (`ccwb test` or CI checks)
- [ ] Added new tests for this change (if applicable)
- [ ] Test coverage maintained or improved
- [ ] Tests are referenced: <!-- Link to test run output or GitHub Actions results -->

### Manual Testing - CLI Commands

<!-- Test the affected commands and attach screenshots or terminal output -->

- [ ] **`ccwb init`** - Tested initialization wizard
  - Screenshot/log: <!-- Attach here or link to comment below -->
  
- [ ] **`ccwb deploy`** - Tested deployment
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Stack deployed: <!-- auth / monitoring / analytics / landing-page / quota -->
  - Stack status: <!-- CREATE_COMPLETE / UPDATE_COMPLETE -->
  
- [ ] **`ccwb build`** - Tested building binaries
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Platform(s) tested: <!-- Windows / macOS-arm64 / macOS-intel / linux-x64 / linux-arm64 -->
  
- [ ] **`ccwb package`** - Tested packaging for distribution
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Distribution method: <!-- manual / presigned-urls / landing-page -->
  
- [ ] **`ccwb test`** - Tested Bedrock connectivity
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Model tested: <!-- Haiku / Sonnet / Opus -->

- [ ] **Binary Installation** - Tested `install.sh` or `install.bat`
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Platform tested: <!-- Windows / macOS / Linux -->
  - Installation location: <!-- ~/.local/bin / /usr/local/bin / custom -->

- [ ] **End-to-End** - Tested full authentication flow with Claude Code
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Tested with: <!-- Claude Code CLI / Claude Desktop (Cowork) -->

### CloudFormation Changes

<!-- If you modified CloudFormation templates -->

- [ ] Templates validated with `cfn-lint`
- [ ] Stack deployed successfully in test AWS account
- [ ] Stack outputs verified
- [ ] Stack rollback tested (if critical change)
- [ ] Cross-region compatibility verified (if applicable)

### Security & Compliance

<!-- If your changes affect authentication, credentials, or data handling -->

- [ ] No secrets or credentials in code
- [ ] Input validation added/verified
- [ ] Error messages don't leak sensitive information
- [ ] Follows principle of least privilege
- [ ] Tested with Bandit/Semgrep (CI will run automatically)

## Testing Evidence

<!-- 
REQUIRED: Provide evidence that you've tested the changes.

You can:
1. Paste screenshots directly here
2. Paste terminal output in code blocks
3. Link to successful GitHub Actions run
4. Link to a comment below with testing evidence

Example:
```
$ ccwb deploy
✅ Stack CREATE_COMPLETE: BedrockCognitoAuthStack-test
```
-->

### Test Environment

- **AWS Region**: <!-- e.g., us-east-1 -->
- **AWS Partition**: <!-- aws / aws-us-gov -->
- **Python Version**: <!-- e.g., 3.12 -->
- **Operating System**: <!-- e.g., macOS 14.0, Ubuntu 22.04, Windows 11 -->
- **Identity Provider**: <!-- e.g., Okta, Entra ID, Auth0, Cognito User Pools, IAM Identity Center, None -->
- **Claude Code Version**: <!-- e.g., 0.13.0 -->

### Test Results

<!-- Paste screenshots, logs, or link to testing evidence below -->

```
[Paste terminal output, stack status, or test results here]
```

---

## Reviewer Checklist

<!-- For maintainers reviewing this PR -->

**Code Quality:**
- [ ] Code changes align with project architecture and style
- [ ] No unnecessary complexity or abstractions
- [ ] Error handling is appropriate
- [ ] Logging is adequate (not too verbose, not too quiet)

**Testing:**
- [ ] Testing evidence is sufficient and demonstrates working functionality
- [ ] Test coverage is adequate for the changes
- [ ] Edge cases are considered

**Security:**
- [ ] No security vulnerabilities introduced (checked Bandit/Semgrep/CodeQL results)
- [ ] Credentials and secrets handled securely
- [ ] Input validation present where needed

**Infrastructure:**
- [ ] CloudFormation changes follow AWS best practices
- [ ] IAM policies follow least privilege principle
- [ ] Resource naming follows conventions
- [ ] Tags applied appropriately

**Documentation:**
- [ ] Documentation is clear and up-to-date
- [ ] CHANGELOG.md updated (if user-facing change)
- [ ] Version bump appropriate (if applicable)
- [ ] Breaking changes clearly documented

**Deployment:**
- [ ] Changes are backward compatible OR migration path documented
- [ ] Rollback plan exists for risky changes
- [ ] No hardcoded values (region, account ID, etc.)
