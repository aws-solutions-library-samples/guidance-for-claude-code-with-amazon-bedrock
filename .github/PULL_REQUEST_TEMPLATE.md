## Description

<!-- Provide a brief description of the changes in this PR -->

## Type of Change

<!-- Check all that apply -->

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Infrastructure/deployment change
- [ ] Dependency update

## Testing Checklist

<!-- 
IMPORTANT: To prevent breaking changes, all PRs affecting core functionality must include testing evidence.
Please check all applicable items and attach screenshots/logs as proof of testing.
-->

### Unit & Integration Tests

- [ ] All existing tests pass locally (`ccwb test`)
- [ ] Added new tests for this change (if applicable)
- [ ] Tests are attached/referenced: <!-- Link to test run output or GitHub Actions results -->

### CLI Testing (Required for code changes affecting ccwb commands)

Please test the affected commands and attach screenshots or terminal output:

- [ ] **`ccwb init`** - Tested initialization wizard
  - Screenshot/log: <!-- Attach here or link to comment below -->
  
- [ ] **`ccwb deploy`** - Tested deployment (auth, monitoring, or analytics stack)
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Stack deployed: <!-- auth / monitoring / analytics / landing-page / quota -->
  
- [ ] **`ccwb build`** - Tested building binaries
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Platform(s) tested: <!-- Windows / macOS / Linux -->
  
- [ ] **`ccwb package`** - Tested packaging for distribution
  - Screenshot/log: <!-- Attach here or link to comment below -->
  
- [ ] **`ccwb test`** - Tested Bedrock connectivity
  - Screenshot/log: <!-- Attach here or link to comment below -->

- [ ] **Binary Installation** - Tested `install.sh` or `install.bat`
  - Screenshot/log: <!-- Attach here or link to comment below -->
  - Platform tested: <!-- Windows / macOS / Linux -->

- [ ] **End-to-End** - Tested credential-process authentication with Claude Code
  - Screenshot/log: <!-- Attach here or link to comment below -->

### CloudFormation Template Changes

- [ ] Templates validated with `cfn-lint` (if modified)
- [ ] Stack deployed successfully in test AWS account
- [ ] Stack outputs verified: <!-- List key outputs tested -->

### Documentation

- [ ] Updated relevant documentation (README, QUICK_START, guides, etc.)
- [ ] Updated CHANGELOG.md (if user-facing change)
- [ ] Updated version in `source/pyproject.toml` (if applicable)

## Testing Evidence

<!-- 
REQUIRED: Attach screenshots or logs demonstrating that you've tested the changes.
You can either:
1. Paste screenshots directly in this section
2. Link to a comment below with testing evidence
3. Reference GitHub Actions workflow run (for automated tests)

Example:
- ccwb init: [Screenshot showing successful profile creation]
- ccwb deploy: [CloudFormation stack CREATE_COMPLETE]
- install.sh: [Terminal output showing successful installation]
-->

### Test Environment

- **AWS Region**: <!-- e.g., us-east-1 -->
- **Python Version**: <!-- e.g., 3.12 -->
- **Operating System**: <!-- e.g., macOS 14.0, Ubuntu 22.04, Windows 11 -->
- **Identity Provider**: <!-- e.g., Okta, Entra ID, Auth0, Cognito, None -->

### Test Results

<!-- Paste screenshots, logs, or link to testing evidence here -->

```
[Paste terminal output or link to screenshots]
```

## Breaking Changes

<!-- 
If this PR introduces breaking changes:
1. List all breaking changes
2. Provide migration instructions
3. Update major version in pyproject.toml
-->

- [ ] No breaking changes
- [ ] Breaking changes documented below:

<!-- 
Breaking change details:
- What breaks?
- How to migrate?
- Rollback plan?
-->

## Additional Notes

<!-- Any additional context, concerns, or areas requiring special review attention -->

---

## Reviewer Checklist

<!-- For maintainers reviewing this PR -->

- [ ] Code changes align with project architecture and style
- [ ] Testing evidence is sufficient and demonstrates working functionality
- [ ] No security vulnerabilities introduced (checked Bandit/Semgrep results)
- [ ] CloudFormation changes follow AWS best practices
- [ ] Documentation is clear and up-to-date
- [ ] CHANGELOG.md updated (if user-facing change)
- [ ] Version bump appropriate (if applicable)
