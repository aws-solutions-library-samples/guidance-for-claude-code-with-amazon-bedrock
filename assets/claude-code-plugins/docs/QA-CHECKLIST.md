# Documentation Quality Assurance Checklist

**Purpose**: Ensure documentation quality, consistency, and proper navigation structure across all Claude Code Plugins Marketplace documentation.

## 1. Terminology Consistency

### Official Names (Use Exactly)
- ✅ **Claude Code Plugins Marketplace** (project name)
- ✅ **Claude Code** (the tool)
- ✅ **EPCC workflow** (plugin name, lowercase "workflow")
- ✅ **Diataxis** (framework name, capital D)

### Plugin Names (Exact Match Required)
All plugin names must match these exactly:

| Plugin Name | Install Command |
|-------------|----------------|
| `epcc-workflow` | `/plugin install epcc-workflow@aws-claude-code-plugins` |
| `documentation` | `/plugin install documentation@aws-claude-code-plugins` |
| `architecture` | `/plugin install architecture@aws-claude-code-plugins` |
| `security` | `/plugin install security@aws-claude-code-plugins` |
| `testing` | `/plugin install testing@aws-claude-code-plugins` |
| `performance` | `/plugin install performance@aws-claude-code-plugins` |
| `tdd-workflow` | `/plugin install tdd-workflow@aws-claude-code-plugins` |
| `agile-tools` | `/plugin install agile-tools@aws-claude-code-plugins` |
| `ux-design` | `/plugin install ux-design@aws-claude-code-plugins` |
| `deployment` | `/plugin install deployment@aws-claude-code-plugins` |
| `code-analysis` | `/plugin install code-analysis@aws-claude-code-plugins` |

### Command Syntax Standards
- ✅ Commands always start with `/` (e.g., `/plugin`, `/epcc-explore`)
- ✅ Marketplace reference: `@aws-claude-code-plugins`
- ✅ Full install syntax: `/plugin install <name>@aws-claude-code-plugins`
- ✅ Slash commands: `/epcc-explore`, `/epcc-plan`, `/epcc-code`, `/epcc-commit`

### Common Terms (Consistent Usage)
| Use This | Not This |
|----------|----------|
| plugin | plug-in, Plugin |
| agent | Agent (unless starting sentence) |
| marketplace | Marketplace (unless starting sentence) |
| workflow | Workflow (unless starting sentence) |
| command | Command (unless starting sentence) |

## 2. Cross-Reference Verification

### Documentation Hub (docs/README.md)
- [ ] Links to tutorial: `[Getting Started Tutorial](tutorials/getting-started-epcc-workflow.md)`
- [ ] Links to how-to: `[Configuration How-To](how-to/configure-plugins.md)`
- [ ] Links to main README: `[Main Repository README](../README.md)`
- [ ] Links to CONTRIBUTING: `[Contributing Guide](../CONTRIBUTING.md)`
- [ ] Links to SECURITY: `[Security Policy](../SECURITY.md)`
- [ ] All plugin links reference main README sections

### Tutorial Document (docs/tutorials/getting-started-epcc-workflow.md)
- [ ] Links to documentation hub: `[Documentation Hub](../README.md)`
- [ ] Links to how-to for advanced topics: `[Configuration Guide](../how-to/configure-plugins.md)`
- [ ] Links to specific how-to sections with anchors (e.g., `#team-configuration`)
- [ ] Links to main README for plugin details: `[Main README](../../README.md)`

### How-To Document (docs/how-to/configure-plugins.md)
- [ ] Links to documentation hub: `[Documentation Hub](../README.md)`
- [ ] Links to tutorial for beginners: `[Getting Started](../tutorials/getting-started-epcc-workflow.md)`
- [ ] Links to main README for plugin catalog: `[Plugin Catalog](../../README.md#available-plugins)`
- [ ] Proper section anchors (e.g., `#team-configuration`, `#troubleshooting`)

### Main README (README.md)
- [ ] Links to documentation hub: `[Documentation Hub](docs/README.md)`
- [ ] Links to tutorial: `[Getting Started Tutorial](docs/tutorials/getting-started-epcc-workflow.md)`
- [ ] Links to how-to: `[Configuration How-To](docs/how-to/configure-plugins.md)`
- [ ] Repository structure shows docs directory correctly
- [ ] All plugin sections have proper anchors

## 3. Content Consistency

### Installation Examples
Verify all documents use identical installation commands:

```bash
# Add marketplace
/plugin marketplace add aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock

# Install plugin
/plugin install epcc-workflow
# Browse plugins
/plugin
```

### Directory Structure Examples
All documents must show consistent directory structure:

```
claude-code-plugins/
├── .claude-plugin/
│   └── marketplace.json
├── plugins/
│   ├── epcc-workflow/
│   ├── documentation/
│   ├── architecture/
│   └── ...
├── docs/
│   ├── README.md
│   ├── tutorials/
│   └── how-to/
└── README.md
```

### Plugin Descriptions
Each plugin description must match the main README exactly:

#### EPCC Workflow
- "EPCC (Explore-Plan-Code-Commit) systematic development workflow"
- "Systematic, methodical development approach"

#### Documentation
- "Complete Diataxis documentation framework"
- "Comprehensive, user-focused documentation"

#### Architecture
- "Architecture design, review, and documentation"
- "System design and architecture reviews"

## 4. Example Consistency

### Working Code Examples
All code examples must:
- [ ] Use real, working commands
- [ ] Produce expected output
- [ ] Be tested before publication
- [ ] Include expected results or explanations
- [ ] Be identical across documents (same example = same code)

### Common Examples to Verify

**Example 1: Basic Plugin Installation**
```bash
/plugin install epcc-workflow```

**Example 2: Team Configuration**
```json
{
  "requiredMarketplaces": ["aws-solutions-library-samples/guidance-for-claude-code-with-amazon-bedrock"],
  "requiredPlugins": [
    "epcc-workflow@aws-claude-code-plugins",
    "security@aws-claude-code-plugins"
  ]
}
```

**Example 3: EPCC Workflow Commands**
```bash
/epcc-explore "authentication system"
/epcc-plan
/epcc-code
/epcc-commit
```

## 5. No Contradictions

### Check for Conflicts

- [ ] Installation steps are identical in all documents
- [ ] Command syntax is consistent everywhere
- [ ] Plugin capabilities match across all references
- [ ] Prerequisites are consistent
- [ ] Version numbers (if any) match
- [ ] File paths are consistent
- [ ] Directory structures match

### Common Contradiction Points
1. **Installation process**: Tutorial vs How-To must be identical
2. **Plugin names**: Must match exactly everywhere
3. **Command syntax**: Must be identical in all examples
4. **Directory paths**: Must use same structure
5. **Prerequisites**: Must list same requirements

## 6. Link Validation

### Internal Links (Relative Paths)

From `docs/README.md`:
- [ ] `tutorials/getting-started-epcc-workflow.md` ✓
- [ ] `how-to/configure-plugins.md` ✓
- [ ] `../README.md` ✓
- [ ] `../CONTRIBUTING.md` ✓
- [ ] `../SECURITY.md` ✓

From `docs/tutorials/getting-started-epcc-workflow.md`:
- [ ] `../README.md` ✓
- [ ] `../how-to/configure-plugins.md` ✓
- [ ] `../../README.md` ✓

From `docs/how-to/configure-plugins.md`:
- [ ] `../README.md` ✓
- [ ] `../tutorials/getting-started-epcc-workflow.md` ✓
- [ ] `../../README.md` ✓

From `README.md`:
- [ ] `docs/README.md` ✓
- [ ] `docs/tutorials/getting-started-epcc-workflow.md` ✓
- [ ] `docs/how-to/configure-plugins.md` ✓
- [ ] `CONTRIBUTING.md` ✓
- [ ] `SECURITY.md` ✓

### External Links

- [ ] `https://docs.claude.com/claude-code` ✓
- [ ] `https://docs.claude.com/claude-code/plugins-reference` ✓
- [ ] `https://docs.claude.com/claude-code/plugin-marketplaces` ✓
- [ ] `https://diataxis.fr/` ✓
- [ ] GitHub repository links (if applicable) ✓

### Anchor Links

- [ ] `#team-configuration` exists in how-to guide
- [ ] `#troubleshooting` exists in how-to guide
- [ ] `#installation` exists in how-to guide
- [ ] `#available-plugins` exists in main README
- [ ] All referenced anchors are valid

## 7. Diataxis Framework Compliance

### Tutorial Document
- [ ] Learning-oriented (focuses on learning outcomes)
- [ ] Hands-on, step-by-step instructions
- [ ] Assumes no prior knowledge
- [ ] Encourages experimentation
- [ ] Provides working examples
- [ ] Has clear completion criteria
- [ ] Estimated time provided (25 minutes)

### How-To Document
- [ ] Task-oriented (focuses on solving problems)
- [ ] Goal-focused instructions
- [ ] Assumes basic knowledge
- [ ] Provides practical solutions
- [ ] Multiple use cases covered
- [ ] Troubleshooting section included
- [ ] Clear task descriptions

### Reference (Main README)
- [ ] Information-oriented
- [ ] Comprehensive coverage
- [ ] Organized by function (plugins)
- [ ] Technical specifications
- [ ] Quick lookup structure

## 8. Professional Quality Standards

### Formatting
- [ ] Consistent heading levels
- [ ] Proper code block formatting with language tags
- [ ] Tables are well-formatted and aligned
- [ ] Lists use consistent bullet styles
- [ ] Links are properly formatted

### Grammar and Style
- [ ] Professional tone throughout
- [ ] Active voice preferred
- [ ] Imperative mood for instructions
- [ ] Consistent tense usage
- [ ] No spelling errors

### Structure
- [ ] Logical information flow
- [ ] Progressive disclosure (simple → complex)
- [ ] Clear section boundaries
- [ ] Table of contents where appropriate
- [ ] Summary or conclusion sections

### Accessibility
- [ ] Descriptive link text (not "click here")
- [ ] Alt text for images (if any)
- [ ] Clear heading hierarchy
- [ ] Code examples are readable
- [ ] Color is not the only information indicator

## 9. User Navigation

### "Can I Get There From Here?" Test

Starting from main README:
- [ ] Can reach documentation hub in 1 click
- [ ] Can reach tutorial in 2 clicks
- [ ] Can reach how-to in 2 clicks
- [ ] Can reach contributing guide in 1 click

Starting from documentation hub:
- [ ] Can reach tutorial in 1 click
- [ ] Can reach how-to in 1 click
- [ ] Can return to main README in 1 click
- [ ] Can reach contributing guide in 1 click

Starting from tutorial:
- [ ] Can reach documentation hub in 1 click
- [ ] Can reach how-to in 1 click
- [ ] Can reach main README in 1 click

Starting from how-to:
- [ ] Can reach documentation hub in 1 click
- [ ] Can reach tutorial in 1 click
- [ ] Can reach main README in 1 click

### User Journey Completeness

**Beginner Journey:**
1. [ ] Lands on main README
2. [ ] Finds documentation hub link
3. [ ] Identifies as beginner
4. [ ] Reaches tutorial in 2 clicks
5. [ ] Completes tutorial
6. [ ] Finds link to how-to for next steps

**Practitioner Journey:**
1. [ ] Lands on main README
2. [ ] Finds documentation hub link
3. [ ] Identifies as practitioner
4. [ ] Reaches how-to in 2 clicks
5. [ ] Solves specific problem
6. [ ] Finds link to main README for plugin details

**Team Lead Journey:**
1. [ ] Lands on main README
2. [ ] Finds documentation hub link
3. [ ] Identifies as team lead
4. [ ] Reaches team configuration in 3 clicks
5. [ ] Configures plugins for team
6. [ ] Finds link to tutorial for team training

## 10. Final Checklist

### Pre-Publication
- [ ] All agents have completed their documents
- [ ] Documentation hub is complete
- [ ] Main README updated with links
- [ ] All internal links tested
- [ ] All external links tested
- [ ] Terminology verified consistent
- [ ] Examples verified working
- [ ] No contradictions found
- [ ] Cross-references complete

### Quality Gates
- [ ] Spelling and grammar checked
- [ ] Code examples tested
- [ ] Link validity confirmed
- [ ] User journeys validated
- [ ] Diataxis principles followed
- [ ] Professional tone maintained
- [ ] Accessibility standards met
- [ ] Navigation structure verified

### Sign-Off
- [ ] Documentation Coordinator reviewed
- [ ] Tutorial Agent confirmed completion
- [ ] How-To Agent confirmed completion
- [ ] All links manually tested
- [ ] Ready for user testing

---

**Testing Notes**: After checklist completion, perform user testing with:
1. Complete beginner (never used Claude Code)
2. Experienced developer (familiar with CLI tools)
3. Team lead (responsible for team configuration)

Record any navigation issues, unclear instructions, or broken links for immediate correction.
