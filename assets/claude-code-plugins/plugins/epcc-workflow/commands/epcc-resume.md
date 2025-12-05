---
name: epcc-resume
description: Resume multi-session work - runs startup checklist and identifies next action
version: 1.1.0
argument-hint: "[--status|--feature F001|--validate]"
---

# EPCC Resume Command

You are in the **RESUME** phase of the EPCC workflow. Your mission is to quickly orient and identify the next action for continuing multi-session work.

**Opening Principle**: Every session starts with clear context. No progress is lost when handoffs are done right.

@../docs/EPCC_BEST_PRACTICES.md - Comprehensive guide covering clarification strategies, error handling patterns, sub-agent delegation, and EPCC workflow optimization

## Arguments
$ARGUMENTS

### Resume Modes

Parse mode from arguments:
- **Default** (no flags): Full startup checklist + recommended action
- `--status`: Quick progress summary only (no action recommendation)
- `--feature F001`: Focus on specific feature, show its detailed status
- `--validate`: Run E2E checks on all "verified" features

## Prerequisites Check

Before proceeding, verify progress tracking exists:

```bash
# Check for EPCC state files
if [ ! -f "epcc-features.json" ] && [ ! -f "epcc-progress.md" ]; then
    # Check for legacy setup
    if [ -f "PRD.md" ]; then
        # Legacy repo detected - trigger migration flow
        trigger_legacy_migration()
    else
        echo "No EPCC progress tracking found."
        echo "Start a new tracked project with: /prd or /epcc-plan"
        exit 0
    fi
fi
```

If no state files exist, inform user and suggest starting with `/prd` or `/epcc-plan`.

---

## Legacy Repo Detection (Migration to EPCC v3)

If `PRD.md` exists but `epcc-features.json` does NOT exist, this is a legacy EPCC repo that predates the v3 tracking system.

### Step 1: Detect Legacy State

```python
# Detection logic
legacy_files = {
    "PRD.md": exists("PRD.md"),
    "TECH_REQ.md": exists("TECH_REQ.md"),
    "EPCC_PLAN.md": exists("EPCC_PLAN.md"),
    "EPCC_EXPLORE.md": exists("EPCC_EXPLORE.md")
}

v3_files = {
    "epcc-features.json": exists("epcc-features.json"),
    "epcc-progress.md": exists("epcc-progress.md")
}

if any(legacy_files.values()) and not any(v3_files.values()):
    trigger_migration_prompt()
```

### Step 2: Migration Prompt

Display detection results and offer migration:

```
📋 **Legacy EPCC repo detected**

Found:
  ✅ PRD.md (Core Features documented)
  ✅ TECH_REQ.md (Technical requirements)  [or ❌ if missing]
  ✅ EPCC_PLAN.md (Implementation plan)    [or ❌ if missing]
  ❌ epcc-features.json (Feature tracking)
  ❌ epcc-progress.md (Session log)

This repo was created with EPCC v2 and doesn't have v3 tracking.

Migrate to EPCC v3 tracking? [Y/n]
  - Y: Parse existing documents, generate tracking files
  - n: Continue without long-running project support
```

Use AskUserQuestion tool:
```json
{
  "questions": [{
    "question": "Legacy EPCC repo detected (PRD.md found, no feature tracking). Migrate to EPCC v3?",
    "header": "Migrate?",
    "multiSelect": false,
    "options": [
      {
        "label": "Yes, migrate",
        "description": "Parse PRD.md/TECH_REQ.md, generate epcc-features.json and epcc-progress.md"
      },
      {
        "label": "No, skip",
        "description": "Continue without v3 tracking (limited session continuity)"
      }
    ]
  }]
}
```

### Step 3: Migration Execution

If user confirms migration:

#### 3a. Parse PRD.md for Features

Look for feature sections in PRD.md:
- "Core Features" / "Features" / "Functional Requirements"
- Priority markers: P0, P1, P2 or Must Have, Should Have, Nice to Have

Extract each feature:
```json
{
  "id": "F001",
  "name": "[Feature name]",
  "description": "[Feature description]",
  "priority": "[P0/P1/P2]",
  "status": "pending",
  "passes": false,
  "source": "PRD.md#[section]"
}
```

#### 3b. Enrich with TECH_REQ.md (If Present)

If TECH_REQ.md exists, parse for:
- Technical subtasks per feature
- Infrastructure requirements
- Non-functional requirements

Add subtasks to features:
```json
{
  "subtasks": [
    {"name": "Database schema", "status": "pending"},
    {"name": "API endpoint", "status": "pending"},
    {"name": "Unit tests", "status": "pending"}
  ]
}
```

Add infrastructure features (INFRA-*):
```json
{
  "id": "INFRA-001",
  "name": "Database Setup",
  "priority": "P0",
  "status": "pending"
}
```

#### 3c. Generate epcc-features.json

Create the tracking file with all features as pending:

```json
{
  "project": "[Project name from PRD]",
  "version": "3.0.0",
  "created": "[current timestamp]",
  "lastUpdated": "[current timestamp]",
  "migratedFrom": "EPCC v2",
  "migrationDate": "[current timestamp]",
  "sourceFiles": ["PRD.md", "TECH_REQ.md"],
  "WARNING": "Feature definitions are IMMUTABLE. Only modify passes, status, and subtasks[].status fields.",
  "features": [
    // ... extracted features
  ],
  "metrics": {
    "total": X,
    "verified": 0,
    "inProgress": 0,
    "pending": X,
    "percentComplete": 0
  }
}
```

#### 3d. Initialize epcc-progress.md

Create progress log with migration entry:

```markdown
# EPCC Progress Log

**Project**: [Project Name]
**Started**: [Original PRD date if available, else today]
**Migrated to v3**: [Today's date]
**Progress**: 0/X features (0%)

---

## Session: Migration - [timestamp]

### Migration from EPCC v2

Imported features from legacy EPCC setup:
- Source: PRD.md, TECH_REQ.md
- Features imported: X
- Infrastructure tasks: Y

### Feature Summary
| ID | Name | Priority | Status |
|----|------|----------|--------|
| F001 | [Name] | P0 | pending |
| F002 | [Name] | P0 | pending |
...

### Next Session
- Review imported features for accuracy
- Mark any already-completed features
- Begin implementation with `/epcc-code [feature-id]`
```

#### 3e. Git Commit Migration

Stage and commit migration files:

```bash
git add epcc-features.json epcc-progress.md
git commit -m "chore: migrate to EPCC v3 tracking system

- Imported X features from PRD.md
- Added Y infrastructure tasks from TECH_REQ.md
- Initialized progress tracking

All features marked as pending. Run /epcc-resume --status to verify."
```

### Step 4: Feature Status Assessment

After migration, offer to mark completed features:

```
✅ Migration complete!

Imported X features from PRD.md/TECH_REQ.md.
All features marked as "pending" by default.

**Some features may already be implemented.**

Would you like to review and mark completed features? [Y/n]
  - Y: Interactive checklist to mark verified features
  - n: Start fresh (all features pending)
```

If user selects Yes, use AskUserQuestion with multiSelect:

```json
{
  "questions": [{
    "question": "Which features are already implemented and verified?",
    "header": "Complete?",
    "multiSelect": true,
    "options": [
      {
        "label": "F001: User Auth",
        "description": "JWT-based login/logout"
      },
      {
        "label": "F002: Task CRUD",
        "description": "Create, read, update, delete tasks"
      }
      // ... all imported features
    ]
  }]
}
```

For each selected feature:
- Update status to "verified"
- Set passes to true
- Add commit SHA from git log (if identifiable)

### Step 5: Report Migration Results

```
🎉 **EPCC v3 Migration Complete**

**Project**: [Project Name]
**Features Imported**: X total
  - P0 (Must Have): Y features
  - P1 (Should Have): Z features
  - P2 (Nice to Have): W features
**Infrastructure Tasks**: N tasks

**Status**:
  - ✅ Verified: [count]
  - ⬜ Pending: [count]

**Files Created**:
  - epcc-features.json (feature tracking)
  - epcc-progress.md (session log)

**Git Commit**: [short SHA] - "chore: migrate to EPCC v3 tracking system"

**Next Steps**:
1. Run `/epcc-resume` to see full status
2. Start work with `/epcc-code [feature-id]`
```

---

## Session Startup Checklist (Default Mode)

Execute this checklist to orient quickly:

### Phase 1: Environment Verification
```bash
# 1. Confirm working directory
pwd

# 2. Check git state
git branch --show-current
git status --short

# 3. Review recent commits
git log --oneline -10
```

### Phase 2: Progress State Recovery
```bash
# 4. Read progress log (last session summary)
if [ -f "epcc-progress.md" ]; then
    # Extract last session section
    head -100 epcc-progress.md
fi

# 5. Read feature status
if [ -f "epcc-features.json" ]; then
    # Parse feature list and calculate metrics
    cat epcc-features.json
fi
```

### Phase 3: Feature Analysis

Parse `epcc-features.json` to calculate:
- Total features
- Features passing (verified)
- Features in progress
- Features pending
- Percentage complete

Identify:
- Current in-progress feature (if any)
- Highest-priority pending feature
- Any features that regressed (were passing, now failing)

### Phase 4: Quick Verification (Optional)

If test command is known (from init.sh or EPCC_PLAN.md):
```bash
# Run test suite to verify current state
npm test    # or pytest, etc.
```

Report any failures, especially in previously-passing features.

## Output Format

### Full Resume (Default)

Display comprehensive session context:

```markdown
## EPCC Session Resume: [Project Name]

**Working Directory**: /path/to/project
**Branch**: [current-branch]
**Last Commit**: [sha] - [message]

---

### Progress: X/Y features (Z%)

| Status | Feature | Priority | Notes |
|--------|---------|----------|-------|
| ✅ | F001: User Authentication | P0 | verified, commit: abc123 |
| ✅ | F002: Task CRUD | P0 | verified, commit: def456 |
| 🔄 | F003: Task List View | P0 | in_progress, 2/5 subtasks |
| ⬜ | F004: Task Detail View | P1 | pending |
| ⬜ | F005: Notifications | P2 | pending |

### Last Session Summary

**Date**: [Date from epcc-progress.md]
**Work Completed**:
- [Item 1]
- [Item 2]

**Handoff Notes**:
[Notes from last session]

### Quick Checks

| Check | Status |
|-------|--------|
| Tests | 45/45 passing |
| Build | OK |
| Coverage | 87% |

### Recommended Next Action

**Continue**: F003 - Task List View (in_progress)
**Resume at**: src/views/TaskList.tsx:45 - need to implement pagination

**Start work with**: `/epcc-code F003`

---

Ready to continue? [Y/n/other feature]
```

### Status Only (--status)

Display abbreviated progress:

```markdown
## EPCC Progress: [Project Name]

**Progress**: X/Y features (Z%)
**Last Session**: [Date] - Completed [feature]
**Current**: [in_progress feature] | **Next**: [pending feature]

Feature Status:
- ✅ Verified: X
- 🔄 In Progress: Y
- ⬜ Pending: Z
```

### Feature Detail (--feature F001)

Display detailed feature status:

```markdown
## Feature: F001 - User Authentication

**Status**: verified
**Priority**: P0
**Passes E2E**: true
**Commit**: abc123

### Acceptance Criteria
1. ✅ Login form accepts email and password
2. ✅ Valid credentials redirect to dashboard
3. ✅ Invalid credentials show error message
4. ✅ JWT token stored in localStorage
5. ✅ Protected routes require valid token

### Subtasks
| Task | Status |
|------|--------|
| JWT generation | complete |
| Login endpoint | complete |
| Logout endpoint | complete |
| Auth middleware | complete |
| Tests | complete |

### Implementation
**Files Modified**:
- src/auth/jwt.ts
- src/auth/login.ts
- src/middleware/auth.ts
- tests/auth.test.ts

### Test Evidence
[Screenshot or test output reference]
```

### Validation Mode (--validate)

Run E2E checks on all verified features:

```markdown
## EPCC Validation: [Project Name]

Running E2E checks on X verified features...

| Feature | E2E Status | Notes |
|---------|------------|-------|
| F001: User Authentication | ✅ PASS | All acceptance criteria verified |
| F002: Task CRUD | ✅ PASS | All acceptance criteria verified |
| F003: Task List View | ❌ FAIL | Pagination broken after merge |

### Regression Detected!

**F003: Task List View** was marked as verified but now fails E2E.

**Action Required**: Fix regressions before continuing with new work.
- Prioritize fixing broken tests over implementing new features
- Update epcc-features.json: F003.passes = false
- Document regression in epcc-progress.md

**Recommended**: `/epcc-code F003 --fix-regression`
```

## Handling Missing State Files

### No epcc-features.json

```markdown
## EPCC Resume: No Feature Tracking

No `epcc-features.json` found. This project doesn't have structured feature tracking.

**Options**:
1. **Start fresh tracking**: Run `/prd` to create requirements and feature list
2. **Add tracking to existing plan**: Run `/epcc-plan` to generate feature list from EPCC_PLAN.md
3. **Continue without tracking**: Use standard EPCC commands without progress tracking
```

### No epcc-progress.md

```markdown
## EPCC Resume: No Progress Log

Found `epcc-features.json` but no `epcc-progress.md`.

Creating epcc-progress.md from current state...

[Generate initial progress log from epcc-features.json and git history]
```

## Integration with Other Commands

### After /epcc-resume → Next Action

Based on resume output, suggest appropriate next command:

| State | Recommended Command |
|-------|---------------------|
| Feature in progress | `/epcc-code [feature-id]` |
| All features pending | `/epcc-code [highest-priority]` |
| Regressions detected | `/epcc-code [regressed-feature] --fix` |
| All features verified | `/epcc-commit` |
| No features defined | `/epcc-plan` |

### Progress Tracking Updates

This command is **read-only** - it does NOT modify state files.

Modifications happen through:
- `/epcc-code` - Updates feature status during implementation
- `/epcc-commit` - Updates progress log after commits

## Autonomous Behavior

This command operates **autonomously** with minimal user interaction:

### Don't Ask, Just Report
- ❌ "Should I run tests?" → ✅ Run tests, report results
- ❌ "Which feature should I suggest?" → ✅ Analyze priorities, suggest highest-priority
- ❌ "The feature list is missing" → ✅ Report missing files, suggest alternatives

### When to Ask

Only use AskUserQuestion if:
- Multiple valid next actions with equal priority
- Critical decision required (e.g., major regression in verified feature)

## Example Sessions

### Example 1: Normal Resume
```
User: /epcc-resume

Claude:
## EPCC Session Resume: Task Management App

Progress: 3/8 features (37.5%)
...
Recommended: Continue F003 (Task List View)
Start work with: /epcc-code F003
```

### Example 2: Status Check
```
User: /epcc-resume --status

Claude:
## EPCC Progress: Task Management App

Progress: 3/8 (37.5%) | Last: F002 completed | Next: F003
```

### Example 3: Feature Detail
```
User: /epcc-resume --feature F002

Claude:
## Feature: F002 - Task CRUD

Status: verified | Passes E2E: true
[Full feature details]
```

### Example 4: Validation
```
User: /epcc-resume --validate

Claude:
## EPCC Validation: Task Management App

Running E2E checks on 3 verified features...
[Validation results]
```

## Remember

**Quick orientation enables confident continuation.**

🚫 **DO NOT**: Modify files, start implementation, change feature status
✅ **DO**: Read state files, run checks, report status, suggest next action

This command is the **first step** of any resumed session - use it to understand where you are before taking action.
