---
name: troubleshoot
description: Systematic troubleshooting mode - Debug problems methodically with ask-for-help mechanism to prevent spinning wheels
version: 1.0.0
argument-hint: "[error-description-or-empty-for-interactive]"
---

# Troubleshoot Command - Systematic Debugging Workflow

You are in **SYSTEMATIC TROUBLESHOOTING MODE** - a methodical 5-stage process designed to diagnose and fix problems efficiently while preventing endless debugging cycles.

⚠️ **CRITICAL PRINCIPLES**:
- **ASK FOR HELP** after 3 failed attempts or when encountering complex issues
- **ONE CHANGE AT A TIME** - never make multiple changes simultaneously
- **GATHER BEFORE GUESSING** - always collect full context before attempting fixes
- **DOCUMENT EVERYTHING** - record all attempts in TROUBLESHOOT.md
- **NO SPINNING WHEELS** - if stuck, stop and ask for user guidance

## Initial Input
$ARGUMENTS

If error description provided, use it as starting point. Otherwise, ask: "What problem are you encountering? Please describe the error or unexpected behavior."

## 🎯 Troubleshooting Objectives

1. **Understand the Problem** - Gather complete context
2. **Classify the Issue** - Determine complexity and type
3. **Form Hypotheses** - Generate specific, testable theories
4. **Test Methodically** - Validate one hypothesis at a time
5. **Document Solution** - Record the fix and lessons learned

## Troubleshooting Workflow

### Stage 1: Context Gathering (2-5 min)

**DO NOT SKIP THIS STAGE** - Rushing to fix without context leads to wasted time.

#### Information to Collect

1. **Full Error Message**
   - Never skim - read the complete error message
   - Note exact error text, error codes, line numbers
   - Capture full stack trace if available

2. **When Did This Start?**
   - What changed recently? (git diff, git log -5)
   - New code, dependencies, config changes?
   - Environment changes? (OS update, new package versions)

3. **Consistency Check**
   - Does it happen every time or intermittently?
   - Specific conditions that trigger it?
   - Works in different environment? (local vs production, different machine)

4. **What's Been Tried?**
   - Ask user: "What have you already attempted?"
   - Avoid repeating failed attempts

5. **System State**
   - Check configuration files
   - Verify environment variables
   - Review recent commits (git log -10 --oneline)
   - Check dependency versions (package.json, requirements.txt, go.mod)
   - Review logs for related errors

#### Context Gathering Checklist

Before moving to Stage 2, confirm:

```markdown
### Context Gathered
- [ ] Full error message captured (exact text)
- [ ] Stack trace analyzed (if available)
- [ ] Recent changes reviewed (git diff, git log)
- [ ] Configuration files checked
- [ ] Dependencies verified (versions, missing packages)
- [ ] Environment variables validated
- [ ] Logs reviewed for related errors
- [ ] Reproduction steps documented
```

#### Document in TROUBLESHOOT.md

```markdown
# Troubleshooting Session: [Date/Time]

## Problem Description
[User's description of the issue]

## Error Message
```
[Exact error text with full stack trace]
```

## Context
- **When Started**: [Timeline]
- **Consistency**: [Always/Sometimes - conditions]
- **Recent Changes**: [List from git log]
- **Environment**: [OS, versions, etc.]
- **Previous Attempts**: [What user tried]

## System State
- **Config Files**: [Status]
- **Dependencies**: [Versions]
- **Environment Variables**: [Status]
```

### Stage 2: Problem Classification (1-2 min)

Classify the issue to determine approach and complexity.

#### Error Categories

##### 🔤 Syntax Error
**Indicators**: Missing punctuation, typo, incorrect syntax
**Complexity**: Simple
**Fix Time**: < 5 min
**Approach**: Quick fix, no ask-for-help needed

**Examples**:
- Missing semicolon, bracket, parenthesis
- Typo in variable/function name
- Incorrect indentation (Python)
- Missing import statement

##### 🧮 Logic Error
**Indicators**: Code runs but produces wrong results
**Complexity**: Medium
**Fix Time**: 15-30 min
**Approach**: Systematic debugging, ask-for-help if > 3 attempts

**Examples**:
- Off-by-one errors in loops
- Wrong comparison operator (< vs <=)
- Incorrect algorithm implementation
- Wrong business logic

##### ⚡ Runtime Error
**Indicators**: Code crashes during execution
**Complexity**: Medium
**Fix Time**: 10-20 min
**Approach**: Check inputs, boundaries, async operations

**Examples**:
- Null/undefined reference
- Type mismatch (string vs number)
- Array out of bounds
- Promise rejection
- File not found

##### 🐌 Performance Issue
**Indicators**: Slow execution, high resource usage
**Complexity**: High
**Fix Time**: 30-60 min
**Approach**: Profiling required, ask-for-help early

**Examples**:
- N+1 database queries
- Memory leak
- Inefficient algorithm (O(n²) instead of O(n))
- Missing database indexes
- Unoptimized images/assets

##### ⚙️ Configuration Issue
**Indicators**: Missing settings, wrong environment
**Complexity**: Simple to Medium
**Fix Time**: 5-15 min
**Approach**: Check configs, env vars, permissions

**Examples**:
- Wrong environment variable
- Missing dependency
- Incorrect file permissions
- Port already in use
- Wrong API endpoint

##### 🔐 Security Issue
**Indicators**: Vulnerable dependencies, exposed secrets
**Complexity**: High
**Fix Time**: 30+ min
**Approach**: Ask-for-help immediately (critical)

**Examples**:
- Exposed API keys
- SQL injection vulnerability
- XSS vulnerability
- Insecure authentication
- Outdated vulnerable package

##### 🌐 Network/Integration Issue
**Indicators**: API failures, timeout errors, connectivity
**Complexity**: Medium to High
**Fix Time**: 20-40 min
**Approach**: Check endpoints, auth, network

**Examples**:
- API endpoint changed
- Authentication token expired
- CORS errors
- Network timeout
- Rate limiting

##### 🏗️ Architectural Issue
**Indicators**: Race conditions, concurrency issues, design flaws
**Complexity**: Very High
**Fix Time**: Hours to days
**Approach**: **ASK-FOR-HELP IMMEDIATELY** - don't attempt aggressive changes

**Examples**:
- Race condition in concurrent code
- Circular dependency
- Improper state management
- Architectural refactor needed
- Fundamental design flaw

#### Classification Output

```markdown
## Problem Classification

**Category**: [Syntax/Logic/Runtime/Performance/Config/Security/Network/Architecture]
**Complexity**: [Simple/Medium/High/Very High]
**Estimated Fix Time**: [X min]
**Approach**: [Quick fix / Systematic debugging / Ask-for-help / Prototype required]

**Reasoning**: [Why classified this way]
```

### Stage 3: Hypothesis Generation (2-3 min)

Form **specific, testable hypotheses** - not vague guesses.

#### Hypothesis Framework

For each hypothesis, define:
1. **What**: Specific theory about root cause
2. **Why**: Evidence supporting this theory
3. **How to test**: Exact test to validate/invalidate
4. **Expected outcome**: What should happen if correct

#### Example: Good vs Bad Hypotheses

❌ **BAD** (Vague):
- "Maybe it's a database issue"
- "Could be the API"
- "Something's wrong with the config"

✅ **GOOD** (Specific):
- "The database connection is timing out because the connection pool size (10) is too small for concurrent requests (50)"
- "The API returns 401 because the JWT token expired (issued 2 hours ago, expires in 1 hour)"
- "The config file is using development database URL instead of production URL (DATABASE_URL env var not set)"

#### Prioritize Hypotheses

Order by likelihood based on context:
1. **Most Likely**: Direct evidence from error message/logs
2. **Alternative**: Indirect evidence or similar past issues
3. **Less Likely**: Edge cases or rare scenarios

#### Document Hypotheses

```markdown
## Hypotheses

### Hypothesis 1 (Most Likely): [Specific theory]
- **Evidence**: [What from context supports this]
- **Test**: [Exact change or check to validate]
- **Expected**: [What should happen if correct]
- **Impact**: [What would this fix]

### Hypothesis 2 (Alternative): [Specific theory]
- **Evidence**: [What from context supports this]
- **Test**: [Exact change or check to validate]
- **Expected**: [What should happen if correct]
- **Impact**: [What would this fix]

### Hypothesis 3 (Less Likely): [Specific theory]
- **Evidence**: [What from context supports this]
- **Test**: [Exact change or check to validate]
- **Expected**: [What should happen if correct]
- **Impact**: [What would this fix]

**Testing Order**: 1 → 2 → 3 (most to least likely)
```

### Stage 4: Methodical Testing (Variable time)

**CRITICAL RULE**: Test ONE hypothesis at a time, never multiple simultaneously.

#### Testing Protocol

For each hypothesis:

1. **Announce** what you're testing
2. **Make ONE specific change**
3. **Test the change** (run code, check behavior)
4. **Record result** (success, failure, unexpected)
5. **Revert if failed** (don't stack changes)

#### Attempt Tracking

```markdown
## Testing Results

### Attempt 1: Testing Hypothesis 1
**Date/Time**: [Timestamp]
**Hypothesis**: [What we're testing]
**Change Made**: [Exact modification]
**Expected Outcome**: [What should happen]
**Actual Outcome**: [What actually happened]
**Result**: ✅ Success / ❌ Failed / ⚠️ Partial
**Next Action**: [If failed, revert and move to next hypothesis]

---

### Attempt 2: Testing Hypothesis 2
[Same structure...]

---

### Attempt 3: Testing Hypothesis 3
[Same structure...]
```

### ⚠️ ASK FOR HELP MECHANISM

#### Trigger Conditions

**IMMEDIATELY Ask for Help When**:
- 🏗️ **Architectural Issue** detected (race condition, fundamental design flaw)
- 🔐 **Security-Critical Issue** (exposed secrets, vulnerabilities)
- 🔥 **Production System at Risk** (affecting users)
- ❓ **Unfamiliar Territory** (technology or domain you don't understand)
- 🤔 **No Clear Hypothesis** (after context gathering, still unclear what to test)

**After 3 Failed Attempts**:
- Tested 3 distinct hypotheses
- No progress toward solution
- Error persists or gets worse

**NEVER Ask for Simple Issues**:
- Syntax errors (typos, missing semicolons)
- Import errors (missing dependencies)
- Simple configuration issues (wrong env var value)
- Obvious logic errors (wrong operator)

#### How to Ask for Help

When trigger condition met, **STOP IMMEDIATELY** and present:

```markdown
---

## ⚠️ ASKING FOR HELP

I've reached a point where I need your guidance to proceed effectively.

### What I've Tried
1. **Attempt 1**: [Summary of hypothesis and result]
2. **Attempt 2**: [Summary of hypothesis and result]
3. **Attempt 3**: [Summary of hypothesis and result]

### Current Understanding
[What I know about the problem so far]

### Why I'm Stuck
[Specific reason: too complex, unfamiliar, architectural, etc.]

### Questions for You
1. [Specific question about domain knowledge or expected behavior]
2. [Specific question about system constraints or requirements]
3. [Specific question about approach or direction]

### Possible Paths Forward

**Option A**: [Approach 1 - explain what it involves]
- Pros: [What this would achieve]
- Cons: [Risks or unknowns]

**Option B**: [Approach 2 - explain what it involves]
- Pros: [What this would achieve]
- Cons: [Risks or unknowns]

**Option C**: Escalate to [team member/external expert]
- When: [If domain expertise needed]

### What Would Help Most
[Be explicit about what information or decision would unblock progress]

**Which path should we take?** Or do you have a different approach in mind?

---
```

### Stage 5: Solution Documentation (2-3 min)

Once problem is solved, document thoroughly for future reference.

#### Solution Documentation Template

```markdown
---

## ✅ SOLUTION FOUND

### Problem Summary
- **Error**: [Brief description]
- **Root Cause**: [What actually caused it]
- **Severity**: [Minor/Moderate/Critical]
- **Impact**: [What was affected - users, systems, data]

### Solution Applied
- **Fix**: [What was changed to resolve it]
- **Files Modified**:
  - [file1.js:42](file://file1.js#42) - [What changed]
  - [file2.py:108](file://file2.py#108) - [What changed]
- **Testing**: [How the fix was verified]
- **Verification**:
  - [ ] Error no longer appears
  - [ ] System behaves as expected
  - [ ] No new errors introduced
  - [ ] All tests passing

### Why This Worked
[Explain the mechanism - why did this fix solve the problem]

### Prevention
**How to avoid this in the future**:
- [Prevention measure 1 - e.g., add validation, update documentation]
- [Prevention measure 2 - e.g., add test coverage, improve error handling]
- [Prevention measure 3 - e.g., monitoring/alerting]

**Watch Out For**:
- [Related issue that might occur]
- [Similar problem in other areas]

### Lessons Learned
1. [Key insight 1 - e.g., "Always check environment variables first for config issues"]
2. [Key insight 2 - e.g., "This error message is misleading - real cause was X"]
3. [Key insight 3 - e.g., "Tool Y helped diagnose this faster"]

### Related Issues
- [Similar problem that might help debug related issues]
- [Documentation that would have prevented this]

### Time Spent
- **Total Time**: [X minutes/hours]
- **Context Gathering**: [Y min]
- **Testing**: [Z min]
- **Attempts**: [N attempts before solution]

---

## Next Steps

1. **Commit the Fix**: Use `/epcc-commit` or regular commit with message:
   ```
   Fix: [Brief description of what was fixed]

   [More details about root cause and solution]

   Closes #[issue-number] (if applicable)
   ```

2. **Update Tests** (if needed):
   - [ ] Add test case that would have caught this bug
   - [ ] Update integration tests if behavior changed
   - [ ] Add regression test to prevent recurrence

3. **Update Documentation** (if needed):
   - [ ] Update README if setup/config changed
   - [ ] Add troubleshooting entry to docs
   - [ ] Document in team knowledge base

4. **Monitor** (for next 24-48 hours):
   - [ ] Watch for similar errors
   - [ ] Verify fix in production (if applicable)
   - [ ] Confirm no side effects

**Problem Resolved! ✅**
```

## Troubleshooting Best Practices

### ✅ DO:

1. **Gather Complete Context First**
   - Read full error messages (don't skim)
   - Check recent changes (git diff, git log)
   - Review configuration and environment
   - Check logs for related errors

2. **Form Specific Hypotheses**
   - "I think X is causing Y because Z"
   - Not vague guesses like "maybe it's the database"

3. **Test One Thing at a Time**
   - Make ONE change
   - Test immediately
   - Revert if doesn't work
   - Never stack multiple changes

4. **Document Everything**
   - Record all attempts in TROUBLESHOOT.md
   - Note what worked and what didn't
   - Explain why solution worked

5. **Ask for Help Early**
   - After 3 failed attempts
   - For complex/architectural issues
   - When unfamiliar with technology
   - For security-critical problems

### ❌ DON'T:

1. **Don't Skip Context Gathering**
   - Rushing to fix wastes more time

2. **Don't Make Multiple Changes at Once**
   - You won't know which change fixed it (or broke it)

3. **Don't Guess Randomly**
   - Form testable hypotheses based on evidence

4. **Don't Spin Wheels Silently**
   - If stuck after 3 attempts, ask for help
   - Don't keep trying random things

5. **Don't Make Aggressive Changes**
   - For architectural issues, ask first
   - Don't refactor during debugging

6. **Don't Ignore Simple Checks**
   - Typos, imports, config - check basics first
   - "It worked yesterday" means something changed

## Common Debugging Patterns

### Pattern 1: "Works on My Machine"

**Likely Causes**:
- Environment variable differences
- Different dependency versions
- Different OS/system configuration
- Cached data or state

**Investigation**:
1. Compare environment variables
2. Check dependency lock files (package-lock.json, Pipfile.lock)
3. Check for hardcoded paths
4. Clear caches and rebuild

### Pattern 2: "Intermittent Failures"

**Likely Causes**:
- Race condition / timing issue
- Non-deterministic code (random, timestamps)
- External service flakiness
- Resource contention

**Investigation**:
1. Run multiple times to establish pattern
2. Check for concurrent operations
3. Look for timing-dependent code
4. Monitor external service status

### Pattern 3: "It Stopped Working After Update"

**Likely Causes**:
- Breaking change in dependency
- API change in library
- Configuration format changed
- Deprecated feature removed

**Investigation**:
1. Check dependency changelog/release notes
2. git diff to see exactly what changed
3. Roll back update temporarily to confirm
4. Check migration guides

### Pattern 4: "Error Message is Misleading"

**Common Misleading Errors**:
- "Module not found" → Often wrong path or typo, not actually missing
- "Cannot read property X of undefined" → Object is undefined, not property
- "EADDRINUSE" → Port already used, not address issue
- "Permission denied" → Could be file permissions, user permissions, or SELinux

**Investigation**:
1. Read error stack trace fully
2. Don't trust just the error message
3. Check underlying cause (2-3 levels deep)
4. Search for error + technology combination

## Quick Win Checks (Before Deep Debugging)

Before spending hours debugging, check these common issues:

### 1. Basic Checks (2 min)
- [ ] Is the server/process actually running?
- [ ] Are you in the right directory/branch?
- [ ] Did you restart after config changes?
- [ ] Is the file saved? (Unsaved changes in editor)

### 2. Dependency Checks (2 min)
- [ ] Run `npm install` / `pip install -r requirements.txt` / equivalent
- [ ] Check for version mismatches in lock files
- [ ] Clear and reinstall dependencies if suspicious

### 3. Environment Checks (2 min)
- [ ] Environment variables set correctly? (echo $VAR_NAME)
- [ ] Using the right environment? (development vs production)
- [ ] Secrets/API keys valid and not expired?

### 4. Cache/Build Checks (2 min)
- [ ] Clear application cache
- [ ] Delete build artifacts and rebuild
- [ ] Clear browser cache (for frontend issues)
- [ ] Restart development server

### 5. Recent Changes (2 min)
- [ ] What's the last commit that worked? (git bisect if needed)
- [ ] Any dependency updates in package.json?
- [ ] Any config changes in .env or config files?

## Output File: TROUBLESHOOT.md

All troubleshooting sessions are documented in `TROUBLESHOOT.md` with:
- Complete problem description
- Context gathered
- Classification and complexity
- All hypotheses tested
- Solution applied (or help requested)
- Lessons learned

This creates a knowledge base for future similar issues.

## After Troubleshooting

### If Problem Solved:
1. Review TROUBLESHOOT.md document
2. Commit the fix with clear message
3. Add tests if appropriate
4. Update documentation if needed
5. Monitor for recurrence

### If Help Requested:
1. Wait for user guidance
2. Resume troubleshooting based on user input
3. Document the collaborative solution
4. Update TROUBLESHOOT.md with final resolution

---

## Remember

> **The goal is not to fix every problem yourself, but to solve problems efficiently through systematic process and knowing when to collaborate.**

✅ **Systematic approach beats random attempts**
✅ **Asking for help early saves time**
✅ **Documentation helps the entire team**
✅ **Prevention is better than debugging**
