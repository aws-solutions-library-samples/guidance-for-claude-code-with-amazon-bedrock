---
name: epcc-commit
description: Commit phase of EPCC workflow - finalize with confidence
version: 3.1.0
argument-hint: "[commit-message] [--amend|--squash]"
---

# EPCC Commit Command

You are in the **COMMIT** phase of the Explore-Plan-Code-Commit workflow. Finalize implementation with quality validation, git commit, and optional PR creation.

**Opening Principle**: High-quality commits capture atomic units of work with clear intent, enabling confident deployment through systematic validation and reversibility.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering git workflows, quality gates, and deployment patterns

## Commit Target
$ARGUMENTS

## 🎯 Commit Philosophy

**Core Principle**: Validate quality → Git commit with safety → Document completion. Execute autonomously, only ask when genuinely blocked.

### Commit Modes

Parse mode from arguments:
- **Default**: Standard commit (quality checks → commit → document)
- **`--amend`**: Amend previous commit (use carefully - verify authorship first)
- **`--squash`**: Squash commits (interactive rebase preparation)

## Execution-First Pattern (Critical)

**This phase is heavily AUTOMATED. Execute with safety checks, don't ask permission for standard operations.**

### Auto-Execute Pattern

1. **Run quality checks** → Tests, coverage, linting, type checking, security
2. **Auto-fix** → Formatting, linting, simple bugs
3. **Re-run** → Verify fixes worked
4. **Stage changes** → Review diff, stage relevant files only
5. **Commit** → Generate message, create commit with safety checks
6. **Document** → Generate EPCC_COMMIT.md
7. **Ask only if blocked** → Quality gates failed after fixes, or user input needed

### When to Ask vs Execute

**✅ Ask when:**
- Critical/High security vulnerabilities can't be auto-fixed
- Tests failing after multiple fix attempts (can't resolve)
- Breaking changes detected (user needs to approve)
- PR creation (user decides whether to push/create PR)
- Commit message unclear from context (what to describe?)

**❌ Don't ask when:**
- Quality checks failed with clear errors (auto-fix)
- Linting/formatting issues (run auto-fix tools)
- Coverage slightly below target (document in commit)
- Standard git operations (execute with safety checks)
- Generating commit message (draft from EPCC_PLAN.md + changes)

## Quality Validation Workflow

### Phase 1: Run Quality Checks

Execute checks from EPCC_EXPLORE.md (or sensible defaults if greenfield):

```bash
# Tests
[test-command]  # pytest, npm test, cargo test, etc.

# Coverage
[coverage-command]  # pytest --cov, npm run coverage, etc.

# Linting
[linter-command]  # ruff check, eslint, clippy, etc.

# Type checking
[type-check-command]  # mypy, tsc, etc.

# Security scan (if security-reviewer ran in CODE phase)
# Results already in EPCC_CODE.md
```

**Auto-fix pattern**: Run → fix issues → re-run → proceed when all pass

**Quality gates** (must pass before commit):
- ✅ All tests passing
- ✅ Coverage meets target (from EPCC_EXPLORE.md or ≥80% default)
- ✅ No linting errors (warnings OK)
- ✅ Type checking clean
- ✅ No CRITICAL/HIGH security vulnerabilities

### Phase 2: Handle Failures

**Automatic fixes** (no user input):
- Formatting issues → Run formatter (black, prettier, rustfmt)
- Import issues → Run import organizer
- Linting auto-fixes → Run linter with --fix
- Simple type errors → Add type annotations

**Ask user when:**
- Can't fix after 2-3 attempts
- Fix requires changing requirements/approach
- Security vulnerability needs architectural change
- Tests fail with unclear root cause

### Commit Blockers

**🛑 Never commit when:**
- CRITICAL or HIGH security vulnerabilities unfixed
- Tests failing (even if "just flaky" - fix or skip properly with markers)
- On main/master branch (create feature branch first)
- Committing to someone else's commit without permission (check authorship)

**⏸️ Pause to fix when:**
- Coverage dropped below target (add tests or document why)
- Multiple TODO/FIXME/DEBUG statements (clean up or track as issues)
- Linting failures (auto-fix or suppress with comments explaining why)
- Type errors (add annotations or use proper types)

**Principle**: Don't commit broken code. Fix or block commit.

## Git Workflow Decision Heuristics

**Never:**
- Commit to main/master without PR (creates deployment risk)
- Use `git add .` blindly (stages unrelated changes, breaks atomicity)
- Push without local verification (CI is not your test environment)
- Amend pushed commits (rewrites history others depend on)
- Skip safety checks (shortcuts create production incidents)
- Commit secrets, API keys, credentials (.env files, config with keys)

### Stage Explicitly, Not Globally

**When to stage:**
- After reviewing changes with `git diff` (understand what you're committing)
- Files that share a logical change unit (related functionality)
- When you can describe the change in one sentence (atomicity test)

**Staging heuristic**: Stage files by purpose, not by convenience. If staging file X requires explaining file Y, they should be separate commits.

**Anti-patterns to avoid**:
- ❌ `git add .` (stages everything—debug code, temp files, unrelated changes)
- ❌ Staging unrelated changes together (breaks atomic commit principle)
- ❌ Staging without reviewing diff (commits things you didn't intend)

**Pattern**: `git add path/to/related/file1.py path/to/related/file2.py`, then `git diff --staged` to verify.

### Commit When Atomic and Complete

**Commit heuristic**: Can you describe the change in one sentence? Would reverting this commit leave the codebase in a working state? If yes to both, commit.

**When to commit:**
- Change completes one logical unit (feature, fix, refactor)
- Build and tests pass after this commit (verify before committing)
- Message can be drafted from context (EPCC_PLAN.md + EPCC_CODE.md + git diff)
- All quality gates passed (or explicitly deferred with reasoning)

**Commit message pattern** (Conventional Commits or project convention):
```
type(scope): what changed

why it matters (not how—code shows how)

Refs: EPCC_PLAN.md, EPCC_CODE.md
Closes #123
```

**Draft message from**:
- EPCC_PLAN.md: Feature description, user value
- EPCC_CODE.md: Implementation decisions, tradeoffs
- `git diff`: Files changed, their purposes
- User requirements: What problem this solves

**Types**: feat (new feature), fix (bug fix), refactor (no behavior change), docs, test, perf, chore

### Push After Local Verification

**When to push:**
- After verifying commit locally (tests pass, no obvious issues)
- User approves push (ask: "Push to remote?" or "Push and create PR?")
- On feature branch, never main/master (safety check)
- Remote tracking configured (first push: `git push -u origin branch-name`)

**Push heuristic**: Push when commits tell a coherent story. If you wouldn't want team to see this commit history, squash or amend locally first.

**Safety verification before push**:
- ✅ `git branch --show-current` ≠ main/master (block if true)
- ✅ Tests pass locally (don't use CI as test environment)
- ✅ No secrets in diff (`git diff` check for API keys, passwords)
- ✅ Commit message is clear (teammates can understand intent)

**Ask user pattern**:
```
✅ Commit succeeded: [SHA]

Options:
1. Push to remote and create PR
2. Push to remote only
3. Leave local (manual push later)
```

### Create PR When Story is Coherent

**When to create PR:**
- User requests it (don't assume—ask first)
- Commits tell coherent story (not "wip", "fix", "fix2", "actually fix")
- Quality metrics documented (coverage, tests, security scan)
- PR body can be drafted from EPCC context

**PR body dimensions** (draft from EPCC_CODE.md):
- **Summary**: What changed, why it matters (1-2 sentences from EPCC_PLAN.md)
- **Changes**: Key files modified, new functionality (from EPCC_CODE.md)
- **Testing**: Test results, coverage metrics (from quality validation)
- **Quality**: Security scan, linting, type checking results

**PR title pattern**: `[type](scope): brief description` (matches commit message)

**Use `gh` CLI**: `gh pr create --title "..." --body "$(cat <<'EOF' ... EOF)"`

### Safety Checks Are Non-Negotiable

**Before commit**:
- ✅ On feature branch (`git branch --show-current`)
- ✅ No secrets in diff (`git diff | grep -i "api_key\|password\|secret"`)
- ✅ Tests pass (`pytest` or equivalent)
- ✅ Changes are relevant (no accidental debug code, temp files)

**Before push**:
- ✅ Not pushing to main/master (warn and block)
- ✅ Commits are atomic (each commit = working codebase state)
- ✅ Remote tracking exists (`git branch -vv`)

**Before PR**:
- ✅ Quality gates passed (tests, coverage, security)
- ✅ PR body documents changes and testing
- ✅ Commit history is clean (squash "fix typo" commits if needed)

### Git Command Reference (Appendix)

**Review**: `git status`, `git diff`, `git diff --staged`, `git branch --show-current`
**Stage**: `git add path/to/file.py`, `git diff --staged` (verify)
**Commit**: `git commit -m "$(cat <<'EOF'\n[message]\nEOF\n)"`, `git log -1 --oneline` (verify)
**Push**: `git push` or `git push -u origin branch-name` (first time)
**PR**: `gh pr create --title "..." --body "..."` (via heredoc for multi-line)

**See**: Git documentation for command details. These heuristics focus on when/why, not command syntax.

## Documentation

### Phase 9: Generate EPCC_COMMIT.md

**Forbidden patterns**:
- ❌ Comprehensive report for trivial commits (typo fix ≠ detailed documentation)
- ❌ Documenting passed quality checks in detail (default: all passed, only document failures or notable findings)
- ❌ Ceremonial "Next Steps" for simple commits (default: merge when approved)
- ❌ PR information when PR not created (omit section if not applicable)

**Documentation structure - 4 core dimensions**:

```markdown
# Commit: [Feature Name]

**SHA**: [SHA] | **Branch**: [branch] | **Status**: [Committed/Pushed/PR]

## 1. Summary ([X files], [+Y -Z lines])
[1-2 sentences: what changed and why]

**Files**: [file:line] - [Purpose]
**Commit**: [type(scope): subject]

## 2. Validation (Tests [X%] | Quality [Clean/Findings] | Security [Clean/Findings])
**Tests**: [Status and coverage] - [X unit, Y integration]
**Quality**: [Linting/typing/formatting status]
**Security**: [Scan results or "Clean"]

## 3. Changes Detail
[Only for non-trivial commits - what's different from before]

**Behavioral changes**: [New functionality or modified behavior]
**Breaking changes**: [None / Describe]

## 4. Completion
**PR**: [URL if created, otherwise "Local commit only"]
**Next**: [Deploy / Merge / Review / Specific action needed]
```

**Depth heuristic**:
- **Trivial commit** (~100-200 tokens): Typo, formatting, simple fix
  - Example: "Fixed typo in README (1 file, +1 -1 lines). SHA: abc123. All checks passed."

- **Standard commit** (~250-400 tokens): Feature, bug fix, refactor
  - Example: All 4 dimensions with moderate detail - summary + validation results + key files + completion status

- **Complex commit** (~500-700 tokens): Multi-file feature, architecture change
  - Example: All 4 dimensions with comprehensive detail - full file breakdown + detailed validation + behavioral changes + PR information

**Completeness heuristic**: Documentation is sufficient when you can answer:
- ✅ What was committed? (Summary with SHA)
- ✅ Does it meet quality gates? (Validation results)
- ✅ What changed specifically? (File breakdown)
- ✅ What happens next? (Completion status)

**Anti-patterns**:
- ❌ **Typo fix with 600-token report** → Violates proportionality
- ❌ **Major feature with 150-token summary** → Missing critical detail
- ❌ **Listing every quality check when all passed** → Document only failures or notable items
- ❌ **"Next: Standard deployment process"** → Generic, specify actual next action

---

**Remember**: Match documentation depth to commit significance. Skip for trivial commits, comprehensive for complex ones.

## Common Pitfalls (Anti-Patterns)

### ❌ Asking About Every Quality Failure
**Don't**: "Tests failed, should I fix?" → **Do**: Auto-fix and re-run

### ❌ Following Template Rigidly
**Don't**: Generate 200-line doc for 1-line fix → **Do**: Match detail to change size

### ❌ Over-Documenting Simple Commits
**Don't**: Essay about typo fix → **Do**: Brief commit message, skip EPCC_COMMIT.md for trivial changes

### ❌ Asking About Standard Git Operations
**Don't**: "Should I run git status?" → **Do**: Execute with safety checks

### ❌ Committing Without Quality Checks
**Don't**: Skip tests to "ship faster" → **Do**: Run checks, fix failures, then commit

### ❌ Using git add . Blindly
**Don't**: Stage everything → **Do**: Review and stage specific files

## Second-Order Convergence Warnings

Even with this guidance, you may default to:

- ❌ **Asking about every quality check failure** (auto-fix first - linting, formatting, simple bugs)
- ❌ **Following template structure rigidly** (adapt to change size - typo ≠ feature)
- ❌ **Over-documenting simple commits** (1-line fix doesn't need comprehensive EPCC_COMMIT.md)
- ❌ **Asking permission for standard git operations** (execute with safety checks - git status, git diff, git commit)
- ❌ **Stopping at first test pass** (verify coverage, check for regression in other tests)
- ❌ **Committing on main/master** (always feature branch - warn if attempting main commit)

## Error Recovery

### Tests Failed

```bash
# Run tests to see failures
[test-command]

# Read error messages carefully
# Common auto-fixes:
# - Import errors → fix imports
# - Syntax errors → fix syntax
# - Type errors → add annotations
# - Assertion failures → fix logic or update expected values

# Re-run after fix
[test-command]

# If still failing after 2-3 attempts, ask user
```

### Coverage Below Target

```bash
# Generate coverage report
[coverage-command]

# Identify uncovered lines
# Add tests for critical paths
# Or document why coverage acceptable in EPCC_COMMIT.md

# Re-run coverage
[coverage-command]
```

### Linting/Formatting Issues

```bash
# Auto-fix
[linter-command] --fix
[formatter-command]

# Re-run checks
[linter-command]

# If failures persist, check if legitimate exceptions
# Add suppression comments with explanations
```

### Security Vulnerabilities

```bash
# Review findings from CODE phase (in EPCC_CODE.md)
# If new vulnerabilities detected:

# Low/Medium: Document, create follow-up issue
# High: Fix before commit
# Critical: Block commit, fix immediately

# Re-run security scan if fixes applied
```

## Git Safety Principles

**Before committing**:
- ✅ Verify on feature branch (not main/master)
- ✅ Review staged changes (git diff --staged)
- ✅ Check for sensitive data (no passwords, API keys, tokens)
- ✅ Stage relevant files only (explicit paths, not git add .)

**Before pushing**:
- ✅ Verify not pushing to protected branch
- ✅ Create remote tracking if new branch (git push -u origin branch)
- ✅ Verify push succeeded (git status shows "up to date")

**Before amending**:
- ✅ Check authorship (git log -1 --format='%an %ae' - only amend your own commits)
- ✅ Check not pushed (git status shows "ahead" not "up to date with origin")
- ✅ Never amend commits from other developers

**Use git commands with safety checks**. Don't push to main/master without explicit user approval and warning.

## Remember

**Your role**: Automated quality validation and git workflow execution.

**Work pattern**: Check → Fix → Verify → Commit → Document. Ask only when blocked.

**Quality gates**: All checks pass before commit. No exceptions for broken code.

**Git safety**: Feature branch, review changes, stage explicitly, commit with clear message.

**Flexibility**: Adapt documentation detail to change size. Simple fix = simple commit.

🎯 **Commit finalized. Implementation complete. Ready for review or deployment.**
