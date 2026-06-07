# PR Standards

## Rule
- **One concern per PR.** If touching >3 files for different reasons, split it.
- **Maximum ~300 lines** for reviewability. Decompose larger changes.
- **Start description with "Why"** — the user impact, not just what changed.
- **Every fix MUST include a regression test** that would have caught the bug.
- **Credit external contributors** in commit messages and PR body.

## Why
Small, focused PRs are easier to review, less likely to introduce bugs, and faster to merge. Starting with "Why" helps reviewers understand the context and importance of the change.

## Examples
```markdown
# ✅ Good PR description
## Why
Users get 403 Forbidden when using Azure domains because we pass raw URLs instead of tenant GUIDs.

## What
Extract tenant GUID from domain URL before passing to CloudFormation.

# ❌ Bad PR description
Fixed Azure domain issue
```