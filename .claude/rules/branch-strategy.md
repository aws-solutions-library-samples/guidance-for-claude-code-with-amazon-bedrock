# Branch Strategy

## Rule
- **Target branch: `beta`** (not `main`)
- Always rebase onto latest `upstream/beta` before opening a PR
- Feature branches: `feat/<name>` for large multi-PR features

## Why
`main` is release-only (`beta → main` promotion PRs). This keeps the release branch clean and allows for proper testing/validation in beta before public release.

## Examples
```bash
# ✅ Correct workflow
git checkout beta
git pull upstream beta
git checkout -b fix/issue-123
# ... make changes ...
git rebase upstream/beta  # before PR
gh pr create --base beta

# ❌ Wrong - targeting main
gh pr create --base main
```