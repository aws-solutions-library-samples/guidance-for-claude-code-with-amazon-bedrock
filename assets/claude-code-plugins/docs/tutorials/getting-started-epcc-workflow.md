> 📚 [Back to Documentation Hub](../README.md)

# Getting Started with Claude Code: Build Your First Feature Using EPCC Workflow

**What you'll learn**: By the end of this tutorial, you'll have installed the Claude Code Plugins Marketplace, set up the EPCC workflow plugin, and completed a full development cycle from exploration to commit. You'll be ready to apply systematic development practices to your own projects.

**Time required**: 25 minutes
**Prerequisites**:
- Claude Code installed (if not, visit [https://claude.ai/code](https://claude.ai/code))
- Basic terminal/command-line familiarity
- A code project to work with (or we'll help you create one)

## What You'll Build

You'll use the EPCC (Explore-Plan-Code-Commit) workflow to add a simple user greeting feature to a project. This represents a real-world development cycle where you:
- Explore the codebase to understand existing patterns
- Plan your implementation systematically
- Code with specialized AI agents helping you
- Commit with professional documentation

### Why This Tutorial Matters

EPCC is a methodical approach that prevents common development mistakes: starting to code before understanding the context, missing edge cases, or creating inconsistent implementations. By learning this workflow, you'll develop a habit of thinking before acting - a practice used by professional development teams worldwide.

## Before We Start

### Verify Your Setup

First, let's confirm Claude Code is working correctly:

```bash
# Test that Claude Code is installed
claude --version
```

**Expected output**: You should see a version number like `claude-code v1.x.x`

**Checkpoint**: If you see the version number, you're ready to continue. If not, install Claude Code from [https://claude.ai/code](https://claude.ai/code) first.

## Step 1: Add the Plugin Marketplace

Let's connect Claude Code to the plugins marketplace. This is like adding an app store to your development environment.

```bash
# Add the AWS Samples marketplace
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
```

**What just happened**: Claude Code connected to a curated collection of 11 production-ready plugins. Think of it as unlocking a toolbox of specialized development assistants.

**Expected result**: You should see a confirmation message like:
```
✓ Marketplace added: aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
  11 plugins available
```

**Checkpoint**: You should see confirmation that the marketplace was added. This means you now have access to all available plugins.

### Verify Marketplace Access

Let's confirm the marketplace is working:

```bash
# Browse available plugins
/plugin
```

**Expected result**: You'll see an interactive list showing all 11 plugins, including:
- epcc-workflow (Explore-Plan-Code-Commit)
- documentation (Diataxis framework)
- security (Security scanning)
- testing (QA and quality gates)
- And 7 more...

**What this means**: The marketplace is connected and you can now install any plugin from this collection.

## Step 2: Install the EPCC Workflow Plugin

Now let's install your first plugin - the EPCC workflow system:

```bash
# Install the EPCC workflow plugin
/plugin install epcc-workflow```

**What just happened**: You installed a complete systematic development workflow that includes:
- 12 specialized AI agents for exploration, planning, coding, and commit phases
- 4 workflow commands (/epcc-explore, /epcc-plan, /epcc-code, /epcc-commit)
- Auto-recovery hooks for error handling

**Expected result**: You should see:
```
✓ Plugin installed: epcc-workflow  12 agents added
  4 commands added
  Ready to use!
```

**Checkpoint**: Type `/epcc` and press Tab to see command completion. You should see all four EPCC commands listed.

### Verify Installation

Let's make sure everything is ready:

```bash
# List your slash commands (you should see /epcc-* commands)
/

# The tab completion should show:
# /epcc-explore
# /epcc-plan
# /epcc-code
# /epcc-commit
```

**What you're seeing**: These four commands represent the complete EPCC development cycle. You're now equipped with a professional workflow system.

## Step 3: Your First EPCC Workflow

Now comes the exciting part - using EPCC to build something real. We'll add a simple user greeting feature that demonstrates the full workflow.

### Phase 1: Explore (Understanding First)

Before writing any code, we need to understand our project. This is like surveying the land before building a house.

```bash
# Start the exploration phase
/epcc-explore "user interface and existing greeting patterns"
```

**What just happened**: Claude Code deployed multiple AI agents in parallel:
- @code-archaeologist analyzed your code structure
- @system-designer identified architectural patterns
- @business-analyst mapped process flows
- @test-generator assessed test coverage
- @documentation-agent reviewed existing docs

**Try it now**: Run the command above in your project directory.

**Expected result**: Claude will spend 30-60 seconds analyzing your project and then create a file called `EPCC_EXPLORE.md` in your project root.

**Checkpoint**: Open `EPCC_EXPLORE.md` and you should see sections like:
- Executive Summary
- Project Structure
- Key Components
- Patterns & Conventions
- Dependencies
- Constraints & Limitations

**What this means**: You now have a complete map of your codebase. This exploration document prevents you from making changes that conflict with existing patterns or break hidden dependencies.

### Phase 2: Plan (Strategic Design)

Now that we understand the project, let's create a detailed implementation plan:

```bash
# Start the planning phase
/epcc-plan "Add a simple user greeting feature that displays personalized welcome message"
```

**What just happened**: Claude Code:
- Read your exploration findings from EPCC_EXPLORE.md
- Created a detailed implementation plan
- Broke down the work into specific tasks
- Assessed risks and edge cases
- Defined success criteria

**Expected result**: A new file called `EPCC_PLAN.md` appears in your project root.

**Checkpoint**: Open `EPCC_PLAN.md` and you should see:
- Feature objectives clearly stated
- Technical approach defined
- Task breakdown with time estimates
- Risk assessment matrix
- Testing strategy
- Success metrics

**What you're seeing**: This is your roadmap. Professional teams spend 20-30% of development time in planning - it prevents costly mistakes and rework later.

### Phase 3: Code (Implementation with Confidence)

Time to build! But notice - we're not coding blindly. We have our exploration findings and detailed plan to guide us:

```bash
# Start the coding phase
/epcc-code "Implement user greeting feature from plan"
```

**What just happened**: Claude Code:
- Reviewed EPCC_EXPLORE.md for patterns to follow
- Consulted EPCC_PLAN.md for the implementation strategy
- Deployed specialized coding agents:
  - @test-generator wrote tests FIRST (TDD approach)
  - @security-reviewer validated security practices
  - @documentation-agent generated inline docs
  - @optimization-engineer ensured performance
- Created working, tested code

**Expected result**:
1. New code files created/modified according to your plan
2. Test files created with passing tests
3. A new file called `EPCC_CODE.md` documenting what was built

**Checkpoint**: Check these things:
- [ ] Your greeting feature code exists and works
- [ ] Tests are present and passing
- [ ] EPCC_CODE.md shows implementation details
- [ ] Code follows patterns identified in exploration phase

**Try it**: Test your new greeting feature:
```bash
# Run your tests
npm test
# or
pytest
```

**What you're seeing**: Tests should be green (passing). This is because Claude followed your project's testing conventions discovered during exploration.

### Phase 4: Commit (Professional Finalization)

The final step is creating a professional commit with complete documentation:

```bash
# Start the commit phase
/epcc-commit "Add personalized user greeting feature"
```

**What just happened**: Claude Code:
- Ran final quality checks (tests, linting, security scan)
- Generated a professional commit message
- Created comprehensive PR documentation
- Documented the complete change in EPCC_COMMIT.md
- Prepared everything for code review

**Expected result**: You'll see:
1. A suggested commit message following conventional commits format
2. Complete PR description ready to copy
3. EPCC_COMMIT.md with full documentation
4. All quality checks passed

**Checkpoint**: Open `EPCC_COMMIT.md` and you should see:
- Changes overview (what, why, how)
- Files changed list
- Testing summary with coverage
- Security considerations
- Performance impact
- Complete PR description template

**What this means**: Your change is professionally documented and ready for team review. Every decision and implementation detail is recorded.

### Make the Actual Commit

Now let's commit your work:

```bash
# Review your changes
git status
git diff

# Stage your changes
git add .

# Commit using the message from EPCC_COMMIT.md
git commit -m "feat: Add personalized user greeting feature

- Implement greeting display component
- Add user name personalization
- Include comprehensive test coverage
- Follow existing UI patterns

Based on:
- Exploration: EPCC_EXPLORE.md
- Plan: EPCC_PLAN.md
- Implementation: EPCC_CODE.md
- Finalization: EPCC_COMMIT.md"
```

**Expected result**: Git confirms your commit was created.

**What you've done**: Created a professional commit that tells the complete story of your change. Any developer (including future you) can understand exactly what was done and why.

## What You've Accomplished

Congratulations! You've just completed a full EPCC workflow cycle. Here's what you achieved:

✓ Installed the Claude Code Plugins Marketplace
✓ Set up the EPCC workflow plugin
✓ Explored a codebase systematically using AI agents
✓ Created a detailed implementation plan
✓ Built a feature with automated testing and documentation
✓ Committed professionally with complete documentation
✓ Learned a workflow used by professional development teams

**More importantly**: You now understand WHY each phase matters:
- **Explore** prevents you from breaking things or creating inconsistent code
- **Plan** saves time by thinking through problems before coding
- **Code** ensures quality through systematic implementation
- **Commit** creates maintainable history that teams can understand

## Next Steps

Now that you understand the EPCC workflow basics:

### Apply It to Your Work
Try EPCC on a real task in your project:
```bash
# Start with exploration
/epcc-explore "the authentication system"

# Or explore a specific feature you want to add
/epcc-explore "API endpoints for user management"
```

### Explore Other Plugins
The marketplace has 10 more plugins to discover:
```bash
# Browse all plugins
/plugin

# Popular combinations:
/plugin install documentation@aws-claude-code-plugins  # Great docs
/plugin install security@aws-claude-code-plugins       # Security checks
/plugin install testing@aws-claude-code-plugins        # QA automation
```

### Configure for Your Team
Set up required plugins for your entire team:
- **[Team Configuration Guide](../how-to/configure-plugins.md#step-4-install-plugin-bundles)** - Enforce plugins across your team with `.claude/settings.json`
- **[Bundle Examples](../how-to/configure-plugins.md#starter-bundle-recommended-for-teams-getting-started)** - Pre-configured setups for different team sizes
- **[Best Practices](../how-to/configure-plugins.md#team-configuration)** - DOs and DON'Ts for team plugin management

**Why this matters**: Team-level configuration ensures everyone has the same tooling, making collaboration seamless and onboarding instant.

### Advanced EPCC Techniques
- **Deep exploration**: `/epcc-explore --deep "complex legacy code"`
- **Quick iteration**: `/epcc-explore --quick "small bug fix"`
- **TDD approach**: `/epcc-code --tdd "feature with tests first"`

### Learn More
- **Configuration Guide**: See [Plugin Configuration](../how-to/configure-plugins.md) for advanced setup and team configuration
- **Plugin Catalog**: Browse the [Main README](../../README.md#available-plugins) for complete plugin details
- **Documentation Hub**: Visit the [Documentation Home](../README.md) for all resources

## Troubleshooting

### Problem: Marketplace won't add
```
Error: Cannot connect to marketplace
```

**Solution**: Check your internet connection and try again:
```bash
# Verify Claude Code is up to date
claude --version

# Try adding marketplace again
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
```

### Problem: Plugin installation fails
```
Error: Plugin not found
```

**Solution**: Make sure the marketplace is added first:
```bash
# List marketplaces
/plugin marketplace list

# Should show: aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
# If not, add it again
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock
```

### Problem: EPCC commands not found
```
Command not recognized: /epcc-explore
```

**Solution**: Verify plugin installation:
```bash
# Check installed plugins
/plugin list

# Should show: epcc-workflow# If not, reinstall
/plugin install epcc-workflow```

### Problem: Exploration phase takes too long

**Solution**: Use quick mode for smaller explorations:
```bash
# Quick exploration for small areas
/epcc-explore --quick "specific component"
```

### Problem: Too many EPCC_*.md files accumulating

**Solution**: Archive completed workflows:
```bash
# Create archive directory
mkdir -p .epcc-archive/feature-name

# Move completed EPCC files
mv EPCC_*.md .epcc-archive/feature-name/

# Or commit them with your feature
git add EPCC_*.md
git commit -m "docs: Add EPCC workflow documentation"
```

### Problem: Generated code doesn't match project style

**Solution**: Create a CLAUDE.md file in your project root with your conventions:
```markdown
# CLAUDE.md

## Code Style
- Use spaces, not tabs
- Functions should be under 50 lines
- Always use TypeScript strict mode

## Testing
- Write tests first (TDD)
- Use Jest for testing
- Minimum 80% coverage
```

EPCC will automatically read this file during exploration and follow your rules.

## Tips for Success

1. **Always start with exploration** - even if you think you know the code. You'll discover patterns and constraints you forgot about.

2. **Don't skip planning** - 15 minutes of planning saves hours of refactoring later.

3. **Review the EPCC files** - they contain valuable insights. Open EPCC_EXPLORE.md and EPCC_PLAN.md before coding.

4. **Keep EPCC files** - they're great documentation for code reviews and future maintenance.

5. **Use flags for different situations**:
   - Quick fixes: `/epcc-explore --quick`
   - Complex work: `/epcc-explore --deep`
   - Test-driven: `/epcc-code --tdd`

6. **Combine with other plugins** - EPCC works great with security, testing, and documentation plugins.

## Your EPCC Journey

You've taken your first step into systematic development with AI assistance. The EPCC workflow will become second nature with practice:

**Week 1**: Use EPCC for small features to build the habit
**Week 2**: Try it on bug fixes and refactoring tasks
**Week 3**: Apply it to complex features with multiple dependencies
**Week 4**: You'll naturally think "explore, plan, code, commit" before starting any work

Remember: **Think systematically, code confidently, commit professionally.**

Welcome to the EPCC community!

---

**Need Help?**
- [Report issues](https://github.com/aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock/issues)
- [Read the complete documentation](../../README.md)
- [Back to Documentation Hub](../README.md)
