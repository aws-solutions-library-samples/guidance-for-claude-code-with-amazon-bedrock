---
name: epcc-commit
description: Commit phase of EPCC workflow - finalize with confidence
version: 2.1.0
argument-hint: "[commit-message] [--amend|--squash]"
---

# EPCC Commit Command

You are in the **COMMIT** phase of the Explore-Plan-Code-Commit workflow. Finalize your work with a professional commit.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering sub-agent delegation for final validation, error handling verification, and clarification strategies

## Commit Context
$ARGUMENTS

### Commit Modes

Parse mode from arguments:
- `--amend`: Amend the previous commit (use with caution)
- `--squash`: Prepare commit message for squashing multiple commits
- **Default** (no flag): Create new commit

## 🎯 Interactive Commit Mode

This command uses **YOU (Claude Code) as the primary agent** to finalize the work:

### Your Role (Finalizing Implementation)

You handle the commit process interactively:
- ✅ Review all code quality checks
- ✅ Generate meaningful commit messages
- ✅ Create PR descriptions
- ✅ Run final validations
- ✅ Execute git commands
- ✅ Coordinate with user on any issues

### Specialized Subagents (Final Validators - Optional)

**About Subagents:** These are specialized Claude Code agents invoked using @-mention syntax (e.g., `@qa-engineer`). They run autonomously and return results.

**IMPORTANT - Context Isolation:** Sub-agents don't have access to your conversation history or EPCC documents. Each @-mention must include complete context:
- Files to review (with descriptions)
- Requirements from EPCC_PLAN.md
- Findings from EPCC_EXPLORE.md
- Specific deliverables expected

See: `../docs/EPCC_BEST_PRACTICES.md` → "Context Isolation Best Practices" for delegation guidance.

Use these agents for **final validation** before committing:

**@qa-engineer** - Final Quality Check
- **When**: Before commit (recommended for production code)
- **Purpose**: Run full test suite, validate quality metrics
- **Tools**: Read, Write, Edit, MultiEdit, Grep, Glob, Bash, BashOutput

**@security-reviewer** - Final Security Scan
- **When**: Before commit (critical for security-sensitive changes)
- **Purpose**: Final vulnerability scan
- **Tools**: Read, Grep, Glob, LS, Bash, BashOutput, WebSearch

**@documentation-agent** - Documentation Check
- **When**: If documentation was generated during CODE phase
- **Purpose**: Verify documentation complete
- **Tools**: Read, Write, Edit, MultiEdit, Grep, Glob, LS

**Full agent reference**: See `../docs/EPCC_BEST_PRACTICES.md` → "Agent Capabilities Overview" for all agents.

## Clarification Strategy

This phase is **highly automated** - focused on execution with minimal conversation. Most work is deterministic.

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Clarification Decision Framework" for complete guidance.

### COMMIT Phase Guidelines

**Expected questions**: 0-2 (typically 0)

**✅ Ask when:**
- Quality checks fail AND fix requires changing requirements
- Breaking changes discovered (need version/deprecation decision)
- Many TODOs found (3+) - remove vs keep vs create issues
- Security vulnerabilities with trade-offs

**❌ Don't ask when:**
- Tests failing (fix them yourself)
- Linting/formatting issues (auto-fix)
- Minor cleanup needed (remove debug code)
- Standard git operations (stage, commit, push automatically)

### Execution-First Pattern

1. Run all quality checks
2. Auto-fix issues (linting, formatting, simple bugs)
3. Clean up (remove 1-2 TODOs/debug statements automatically)
4. Generate commit message and PR description
5. Create commit and push
6. **Only ask if genuinely blocked** (can't fix, requires user decision)

## Handling Ambiguity (CRITICAL)

**COMMIT phase is highly automated - avoid questions unless truly blocked on a decision.**

Before using AskUserQuestion, try to auto-fix the issue:

### Quality Validation Failures?

**Auto-fix pattern: Run → Fix → Re-run → Only ask if can't fix**

**✅ Auto-fixable (don't ask):**
- Linting errors → Run auto-formatter
- Test failures from typos/bugs → Debug and fix
- Missing imports → Add them
- Formatting inconsistencies → Apply project formatter
- Simple security issues → Apply recommended fix from @security-reviewer

**❌ Requires decision (ask user):**

```json
{
  "questions": [{
    "question": "Security scan found HIGH severity issue: API keys in code. How should I proceed?",
    "header": "Security",
    "multiSelect": false,
    "options": [
      {
        "label": "Move to env vars",
        "description": "Refactor to use environment variables (requires .env setup)"
      },
      {
        "label": "Use secrets manager",
        "description": "Integrate AWS Secrets Manager (larger scope change)"
      },
      {
        "label": "Commit with TODO",
        "description": "Document issue, create follow-up task (technical debt)"
      }
    ]
  }]
}
```

### Multiple TODOs Found?

**If 1-2 TODOs: Remove them yourself (fix or delete)**

**If 3+ TODOs: Ask how to handle**

```json
{
  "questions": [{
    "question": "Found 5 TODO comments in the code. How should these be handled before commit?",
    "header": "TODOs",
    "multiSelect": false,
    "options": [
      {
        "label": "Keep all",
        "description": "Leave TODOs in code as reminder comments"
      },
      {
        "label": "Remove all",
        "description": "Delete TODO comments before committing"
      },
      {
        "label": "Create issues",
        "description": "Create GitHub issues for each, remove from code"
      }
    ]
  }]
}
```

### Validation Requires Scope Change?

**Present impact analysis:**

```
⚠️ Test coverage validation failing:

**Current**: 78% coverage (target: 90% per EPCC_PLAN.md)
**Gap**: Missing tests for error handling paths (12 uncovered branches)

**Options**:
1. Add missing tests now (~30 min, delays commit)
2. Commit with coverage exception, create follow-up task
3. Lower coverage threshold to 75% (changes requirements)

**Recommendation**: Option 1 - add tests now (ensures quality)

Which approach should I take?
```

### Breaking Changes Discovered?

**ALWAYS ask about version/deprecation strategy:**

```json
{
  "questions": [{
    "question": "Implementation requires breaking API change (removes deprecated field 'userId'). How should this be versioned?",
    "header": "Breaking",
    "multiSelect": false,
    "options": [
      {
        "label": "Major version bump",
        "description": "v2.0.0 - breaking change, update all consumers"
      },
      {
        "label": "Deprecation period",
        "description": "Keep old field, mark deprecated, remove in v2.0.0"
      },
      {
        "label": "Redesign to avoid break",
        "description": "Keep backward compatibility, add new field instead"
      }
    ]
  }]
}
```

### Commit Message Ambiguity?

**Follow project conventions from EPCC_EXPLORE.md - don't ask unless conventions conflict:**

```
I found two different commit message formats in git history:

Format A (80% of commits, recent):
- "feat: add user authentication with JWT"
- "fix: resolve login redirect loop"

Format B (20% of commits, older):
- "Add user authentication feature"
- "Fix login bug"

Using Format A (appears to be current standard).
```

**See Also**: EPCC_BEST_PRACTICES.md "Clarification Decision Framework" (lines 2323-2475)

## 📝 Commit Objectives

1. **Run Final Checks**: All tests, linters, security scans passing
2. **Clean Code**: No debug statements, TODOs, or commented code
3. **Complete Documentation**: EPCC_COMMIT.md, README updates
4. **Meaningful Commit**: Clear, professional commit message following conventions
5. **PR Ready**: Complete description with links to EPCC docs

## Pre-Commit Workflow

### Step 1: Load Implementation Context

**Review what was done:**
- Read EPCC_CODE.md for implementation summary
- Check EPCC_PLAN.md for original requirements
- Verify EPCC_EXPLORE.md constraints followed

### Step 2: Run Quality Checks

**Execute all quality gates** (use tools from EPCC_EXPLORE.md):

```bash
# 1. Run tests
[test-command-from-EPCC_EXPLORE]  # e.g., pytest, npm test

# 2. Check coverage
[coverage-command-from-EPCC_EXPLORE]

# 3. Run linter
[linter-from-EPCC_EXPLORE]

# 4. Run type checker (if used)
[type-checker-from-EPCC_EXPLORE]

# 5. Run formatter check
[formatter-from-EPCC_EXPLORE]

# 6. Security scan (if applicable)
# npm audit, bandit, safety, etc.
```

**If any checks fail:**
- Do NOT proceed with commit
- Fix the issues
- Re-run checks
- Only commit when all pass

### Step 3: Final Code Cleanup

**Search for and remove:**

```bash
# Debug statements
grep -r "console.log\|debugger\|print(\|pdb" src/

# TODOs and FIXMEs
grep -r "TODO\|FIXME\|XXX" src/

# Hardcoded secrets
grep -ri "password\|secret\|api_key\|token" src/ --exclude="*test*"
```

If found, ask user whether to remove, keep, or convert to issues.

### Step 3.5: Validate Agent-Compatible Error Handling

**CRITICAL**: Verify all code uses agent-observable errors.

**Validation Checklist:**
- [ ] Scripts exit with 0 (success) or 2 (error)
- [ ] Errors go to stderr (sys.stderr, console.error)
- [ ] Error messages are clear and actionable
- [ ] Tests verify error paths and exit codes

**Quick test:**
```bash
$ script.py && echo $?                           # Should be 0
$ script.py --invalid 2>&1 | grep ERROR && echo $?  # Should show error + 2
```

**If validation fails**: Fix error handling before committing. Do NOT proceed with broken error observability.

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Agent-Compatible Error Handling" for complete validation guide and search patterns.

### Step 4: Launch Final Validation Agents IN PARALLEL (Optional)

⚠️ **COMMIT PHASE: Parallel Validators**

Final validators are **independent** - they don't need each other's output. Launch in parallel (all in same response):

```
# ✅ OPTIMAL: Parallel final validation
@qa-engineer Run final quality validation for authentication feature implementation.

Changes in this commit (from EPCC_CODE.md):
- src/services/auth_service.py (JWT authentication logic)
- src/middleware/auth.py (token validation middleware)
- src/api/auth_routes.py (login/logout/refresh endpoints)
- tests/test_auth_service.py (unit tests)
- tests/test_auth_integration.py (API integration tests)

Quality requirements from EPCC_PLAN.md:
- Test coverage target: >90%
- All tests must pass
- No flaky tests
- Performance: login endpoint <200ms

Run full test suite, verify coverage, check for flaky tests.
Report: test results, coverage %, quality issues, PASS/FAIL recommendation.

@security-reviewer Perform final security scan for authentication implementation.

Changes in this commit (from EPCC_CODE.md):
- src/services/auth_service.py (authentication logic, password hashing)
- src/middleware/auth.py (JWT validation)
- src/api/auth_routes.py (authentication endpoints)

Security requirements from EPCC_PLAN.md:
- Password hashing with bcrypt
- JWT secret protection
- Rate limiting on login (5 attempts per 15 min)
- Input validation and sanitization

Scan for: OWASP Top 10, dependency vulnerabilities, auth/authz issues, secret exposure.
Report: vulnerabilities found with severity, PASS/FAIL recommendation, remediation steps.

@documentation-agent Verify documentation completeness for authentication feature.

Files implemented (from EPCC_CODE.md):
- src/services/auth_service.py
- src/middleware/auth.py
- src/api/auth_routes.py

Documentation standards from EPCC_EXPLORE.md:
- Google-style docstrings required
- Type hints in all public APIs
- Usage examples for each endpoint
- README section for setup

Check for: missing docstrings, incomplete API docs, missing usage examples, undocumented endpoints.
Report: documentation coverage %, missing sections, PASS/FAIL recommendation, files needing updates.

# All three agents run concurrently
```

### Sub-Agent Context Isolation (CRITICAL)

⚠️ **Sub-agents are isolated** - no access to conversation, EPCC docs, or commit history.

**For qa-engineer and security-reviewer, include:**
- Changes in this commit (from EPCC_CODE.md or git diff)
- Security/quality requirements (from EPCC_PLAN.md)
- Files to review with specific checks
- Expected deliverable format

**See**: `../docs/EPCC_BEST_PRACTICES.md` → "Context Isolation Best Practices" for complete delegation guidance and examples.

### Step 5: Generate EPCC_COMMIT.md

**Document the complete change:**

```markdown
# Commit Documentation

## Commit Summary
**Feature**: [Name]
**Date**: [Date]
**Mode**: [from CODE phase]
**Status**: Ready for Commit

## Changes Overview
### What Changed
[From EPCC_CODE.md]

### Why It Changed
[From EPCC_PLAN.md]

### How It Changed
[Technical approach]

## Files Changed
### Created
[List with descriptions]

### Modified
[List with what changed]

### Deleted
[List with reasons]

## Quality Validation
### Tests
- Unit: [X/Y passing]
- Integration: [X/Y passing]
- Coverage: [X%] (target: [Y%])
- Status: ✅ PASS / ❌ FAIL

### Code Quality
- Linting: ✅ / ❌
- Type Checking: ✅ / ❌
- Formatting: ✅ / ❌
- No Debug Code: ✅
- No TODOs: ✅

### Security (if scanned)
- Vulnerability Scan: ✅ / ❌
- Critical Issues: [count]
- High Issues: [count]

## Documentation Updates
- [x] Code comments
- [x] API docs (if applicable)
- [x] README.md (if applicable)
- [x] CHANGELOG.md (if applicable)

## Commit Message
[Generated message below]

## Pull Request Description
[Generated description below]
```

### Step 6: Generate Commit Message

**Follow conventional commit format:**

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types**: feat, fix, docs, style, refactor, perf, test, chore

**Example**:
```
feat(auth): implement JWT-based user authentication

Add complete authentication system with login, token refresh, and logout.

Features:
- JWT token generation and validation
- Secure password hashing (bcrypt)
- Rate limiting (5 attempts / 15 min)
- Comprehensive test coverage (94%)

Security:
- No vulnerabilities found
- OWASP Top 10 compliance

Tests: 23 added (18 unit, 5 integration)
Coverage: 94% (target: 90%)

Based on:
- Exploration: EPCC_EXPLORE.md
- Plan: EPCC_PLAN.md
- Implementation: EPCC_CODE.md

Closes #[issue-number]
```

**Note**: Per CLAUDE.md, do NOT include Claude Code attribution or co-author tags.

### Step 7: Generate Pull Request Description

**Create comprehensive PR description:**

```markdown
## Summary
[Brief 2-3 sentence description]

## Changes Made
[Bullet list from EPCC_CODE.md]

## Technical Approach
[From EPCC_PLAN.md]

## Testing
**How to test:**
[Step-by-step instructions]

**Test Results:**
- Unit: [X/Y]
- Integration: [X/Y]
- Coverage: [X%]

## Security Considerations
[From EPCC_CODE.md if available]

## Performance Impact
[If measured]

## Related Issues
- Closes #[issue]

## EPCC Documentation
- [EPCC_EXPLORE.md](./EPCC_EXPLORE.md)
- [EPCC_PLAN.md](./EPCC_PLAN.md)
- [EPCC_CODE.md](./EPCC_CODE.md)
- [EPCC_COMMIT.md](./EPCC_COMMIT.md)

## Checklist
- [ ] Tests added/updated
- [ ] Coverage meets target
- [ ] Documentation updated
- [ ] No breaking changes
- [ ] Code style followed
- [ ] Security reviewed
```

### Step 8: Create Git Commit

**Pre-flight Safety Checks:**

```bash
# 1. Verify current branch (don't commit directly to main/master)
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
    echo "⚠️  WARNING: On protected branch '$CURRENT_BRANCH'"
    echo "   Create feature branch first: git checkout -b feature/[name]"
    # Ask user if they want to proceed or create branch
else
    echo "✅ On feature branch: $CURRENT_BRANCH"
fi

# 2. Check for uncommitted changes in untracked areas
git status --short

# 3. Verify clean working state
if git diff --quiet && git diff --staged --quiet; then
    echo "⚠️  No changes to commit"
else
    echo "✅ Changes ready to commit"
fi
```

**Stage files and commit:**

```bash
# Show full status
git status

# Stage files (from EPCC_CODE.md - be specific, not 'git add .')
git add [relevant-files]

# Verify what's staged (review changes one more time)
git status
git diff --staged --stat

# Commit with generated message (using heredoc for proper formatting)
git commit -m "$(cat <<'EOF'
[generated-commit-message]
EOF
)"

# Verify commit
git log -1 --stat
```

### Step 9: Push and Create PR

**Push Safety Checks:**

```bash
# 1. Verify not pushing to protected branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" = "main" ] || [ "$CURRENT_BRANCH" = "master" ]; then
    echo "🛑 STOP: Attempting to push to protected branch '$CURRENT_BRANCH'"
    echo "   This is dangerous. Create feature branch first."
    exit 1
fi

# 2. Check if remote tracking branch exists
if git rev-parse --abbrev-ref --symbolic-full-name @{u} > /dev/null 2>&1; then
    echo "✅ Remote tracking branch exists"
    git push origin $CURRENT_BRANCH
else
    echo "✅ Creating new remote branch"
    git push -u origin $CURRENT_BRANCH
fi

# 3. Verify push succeeded
if [ $? -eq 0 ]; then
    echo "✅ Push successful"
else
    echo "❌ Push failed - check errors above"
    exit 1
fi
```

**Create Pull Request:**

```bash
# Create PR using GitHub CLI
gh pr create --title "[title]" --body "$(cat <<'EOF'
[generated-PR-description]
EOF
)"

# Or provide manual PR URL if gh unavailable
echo "Create PR at: https://github.com/[owner]/[repo]/compare/[branch]"
```

### Step 9.5: Optional Deployment (Using deployment-agent)

**When to deploy immediately**:
- Hotfixes to production
- Automated staging deployments
- Continuous deployment workflows

**Launch deployment-agent** (optional):

```
@deployment-agent Deploy authentication feature to staging environment.

Changes in this PR (from EPCC_CODE.md):
- src/services/auth_service.py (JWT authentication logic)
- src/middleware/auth.py (token validation middleware)
- src/api/auth_routes.py (login/logout/refresh endpoints)
- Database migration: migrations/002_add_users_table.sql

Deployment requirements from EPCC_PLAN.md:
- Target environment: staging
- Health checks: GET /health, GET /api/auth/status
- Success criteria: All health checks pass, error rate <0.1%
- Rollback trigger: Error rate >1% or health check failures

Infrastructure context from EPCC_EXPLORE.md:
- Platform: AWS ECS with Fargate
- Container: Docker image built in CI
- Database: RDS PostgreSQL (auto-migration on deploy)
- Load balancer: ALB with health checks every 30s

Deployment strategy:
- Progressive rollout: Canary deployment (10% → 50% → 100%)
- Monitor: Error rates, response times, health check status
- Rollback procedure: Automatic if error rate exceeds threshold

Return:
- Deployment status (success/failed/rolled-back)
- Health check results
- Error rate metrics
- Rollback procedure (if issues detected)
```

**Note**: Most teams deploy after PR merge via CI/CD. Skip this step if:
- Deployment happens automatically after merge
- Manual deployment approval required
- Deployment is handled by ops team

**If deployment-agent reports issues**:
1. Review deployment logs
2. Check health check failures
3. Execute rollback if necessary
4. Fix issues and re-deploy

### Step 10: Final Checklist

- [ ] All tests passing
- [ ] Coverage meets target
- [ ] Linting passed
- [ ] Security scan passed (if run)
- [ ] No debug code
- [ ] No TODOs
- [ ] Documentation complete
- [ ] EPCC_COMMIT.md generated
- [ ] Commit message follows conventions
- [ ] PR description complete
- [ ] Commit created
- [ ] Pushed to remote
- [ ] PR created
- [ ] Deployment completed (if applicable)

## Commit Best Practices

### Good vs Bad Commit Messages

✅ **Good**:
```
feat: add user authentication with JWT

- Implement login/logout endpoints
- Add JWT generation and validation
- Include refresh token mechanism
- 94% test coverage

Closes #123
```

❌ **Bad**:
```
Fixed stuff
WIP
Update code
```

### When to Use --amend

✅ **Use --amend when:**
- Last commit is yours
- Commit not pushed yet
- Small fix (typo, forgot file)

❌ **Do NOT amend when:**
- Commit from someone else
- Already pushed to remote
- Multiple people on branch

### When to Use --squash

✅ **Use --squash for:**
- Multiple WIP commits
- Cleaning up before merge
- One logical change across commits

## Post-Commit Actions

### After Committing

1. Verify PR created
2. Request code review
3. Monitor CI checks
4. Address review feedback
5. Merge when approved
6. Delete feature branch

### Clean Up EPCC Files

**Option 1: Archive** (recommended)
```bash
mkdir -p .epcc-archive/[feature-name]
mv EPCC_*.md .epcc-archive/[feature-name]/
git add .epcc-archive/
```

**Option 2: Keep** (for reference)
```bash
git add EPCC_*.md
```

**Option 3: Delete** (if not needed)
```bash
rm EPCC_*.md
```

## Final Output

Upon completion:

```markdown
✅ Commit finalized successfully!

Summary:
- Commit: [hash]
- Branch: [name]
- PR: [URL]
- CI: Pending

EPCC Documentation:
- EPCC_COMMIT.md generated
- Quality checks passed
- Ready for review

Next steps:
1. Monitor CI
2. Respond to feedback
3. Merge when approved
```

## Usage Examples

```bash
# Standard commit
/epcc-commit

# With custom message
/epcc-commit "feat: add payment processing"

# Amend last commit
/epcc-commit --amend

# Prepare squash message
/epcc-commit --squash
```

---

## Success Metrics

### How to Know COMMIT Phase Succeeded

**✅ All Validation Gates Passed**:
- [ ] @security-reviewer: 0 CRITICAL, 0 HIGH vulnerabilities → PASS
- [ ] @qa-engineer: Release recommendation GO
- [ ] @documentation-agent: 100% API coverage confirmed
- [ ] All tests passing (no failures, no skipped tests)
- [ ] Code coverage meets target (typically 90%+)
- [ ] Linting/formatting clean (no violations)

**✅ Commit Created Successfully**:
- [ ] Git commit created with well-formed message
- [ ] All intended files staged and committed
- [ ] Commit message follows project conventions
- [ ] No unintended files included
- [ ] Commit verified with `git log -1 --stat`

**✅ PR Created (if applicable)**:
- [ ] Branch pushed to remote successfully
- [ ] Pull request created with complete description
- [ ] PR includes: summary, test plan, breaking changes (if any)
- [ ] PR linked to relevant issues/tickets
- [ ] CI/CD checks triggered automatically

**✅ Deployment Completed (if applicable)**:
- [ ] @deployment-agent: Deployment successful
- [ ] Health checks passing
- [ ] Error rate within acceptable threshold
- [ ] No rollback triggered
- [ ] Monitoring confirms stable deployment

### Commit Quality Indicators

| Indicator | Good | Excellent |
|-----------|------|-----------|
| Validation Time | < 10 min | < 5 min |
| Security Issues | 0 HIGH | 0 MEDIUM |
| Test Failures | 0 | 0 |
| Coverage | ≥ 90% | ≥ 95% |
| Commit Clarity | Clear message | Message + context |
| PR Description | Complete | Complete + examples |

### When to Block Commit

**❌ DO NOT commit if:**
- Security scan has CRITICAL or HIGH vulnerabilities
- QA recommendation is NO-GO
- Tests are failing (even if "just flaky")
- Coverage dropped below minimum threshold
- Breaking changes without migration plan
- Unreviewed code (if team requires review)

**⏸️ Pause and fix if:**
- Medium security issues without remediation plan
- Performance regression without justification
- Documentation incomplete
- Lint warnings accumulating

**✅ Safe to commit when:**
- All validation agents approve
- All quality thresholds met
- High confidence in production readiness
- Team review passed (if required)

### Success Celebration Criteria

**🎉 Outstanding commit:**
- Zero issues found by any validator
- Coverage increased
- Performance improved
- Documentation exemplary
- Clean, focused changes
- Clear, helpful commit message

---

## Remember

**YOU handle the commit:**
- ✅ Run quality checks
- ✅ Generate commit messages
- ✅ Create PR descriptions
- ✅ Execute git commands
- ✅ Coordinate with user

**Agents validate (optional):**
- @qa-engineer: Quality check
- @security-reviewer: Security scan
- @documentation-agent: Docs completeness

**A good commit:**
- Passes all checks
- Tells the story clearly
- Includes complete docs
- Is ready for review

🚀 **EPCC workflow complete!**
