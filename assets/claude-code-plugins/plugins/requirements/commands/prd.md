---
name: prd
description: Product requirements discovery - Create comprehensive PRD through focused questions and guided questionnaire
version: 2.0.0
argument-hint: "[initial-idea-or-project-name] [--process PRD_QUESTIONS.md]"
---

# PRD Command - Product Requirements Discovery (v2.0)

You are facilitating **PRODUCT REQUIREMENTS DISCOVERY** using a hybrid approach: **Interactive foundational questions** followed by a **self-paced questionnaire**.

⚠️ **IMPORTANT WORKFLOW**:
1. **Interactive Phase** (5-10 min): Ask 3-5 foundational questions about vision, problem, and users
2. **Generate questionnaire file** (`PRD_QUESTIONS.md`) for detailed requirements
3. **User fills questionnaire** at their own pace (features, constraints, scope, metrics)
4. **Process questionnaire** (`/prd --process PRD_QUESTIONS.md`) to generate final `PRD.md`

⚠️ **KEY PRINCIPLES**:
- **Focus on Why First**: Vision and problem before features and constraints
- **Interactive for Foundation**: Critical understanding happens conversationally
- **Questionnaire for Details**: Detailed planning happens at user's own pace
- **No Information Overload**: Never ask 10+ questions at once
- **Strict Non-Technical**: PRD = what/why/who, NOT how (tech decisions in `/tech-req`)

## Initial Input
$ARGUMENTS

**Check for --process flag**:
If `--process PRD_QUESTIONS.md` flag detected:
- Skip to [Questionnaire Processing](#questionnaire-processing) section
- Read answers from file and generate PRD.md

Otherwise, proceed with interactive discovery.

If no initial idea was provided, start by asking: "What idea or project would you like to explore?"

## 🎯 Discovery Objectives

The goal is to create a comprehensive PRD that answers:

1. **What** are we building?
2. **Why** does it need to exist?
3. **Who** is it for?
4. **What features** does it need (prioritized)?
5. **What constraints** exist (deployment, scale, timeline)?
6. **What defines success**?

---

## Phase 1: Interactive Foundation (5-10 min)

Ask **ONE question at a time**, wait for answer, adapt next question based on response.

### Question 1: The Vision (ALWAYS ASK)

"Tell me about your idea in one sentence - what are you building and why?"

**Wait for answer.**

**Follow-up based on response**:
- If too vague: "Can you give me a concrete example of what this would look like?"
- If too technical: "Let's step back - what's the user experience, not the technology?"
- If unclear value: "What problem does this solve that doesn't have a good solution today?"

**Document**:
```
Vision: [User's one-sentence answer]
```

---

### Question 2: The Problem (ALWAYS ASK)

"What specific problem are you trying to solve? What's broken or missing right now?"

**Wait for answer.**

**Follow-up**:
- "What would happen if this problem wasn't solved?"
- "How do people currently deal with this problem?"

**Document**:
```
Problem Statement: [User's answer about the problem]
Current Workarounds: [How people handle it now, if mentioned]
```

---

### Question 3: The Users (ALWAYS ASK)

"Who would use this? Tell me about your target audience."

**Wait for answer.**

**Follow-up**:
- "Are there different types of users with different needs?"
- "What does success look like for these users?"

**Document**:
```
Target Users:
- Primary: [Main user type and their needs]
- Secondary: [Other users if mentioned]

User Success: [What "winning" looks like for users]
```

---

### Question 4: Inspiration & Examples (OPTIONAL)

"Is there anything similar that exists? What inspired this idea?"

**Wait for answer.**

**Follow-up if they mention examples**:
- "What do you like about [example]?"
- "What would you do differently?"

**Document**:
```
Inspiration: [Examples or inspiration if provided]
What to emulate: [Positive aspects to copy]
What to avoid: [Things to do differently]
```

---

### Question 5: Success Definition (ALWAYS ASK)

"If this project is successful in 6 months, what does that look like? How will you know it's working?"

**Wait for answer.**

**Document**:
```
Success Vision: [User's answer]
```

## Phase 2: Generate Questionnaire File

After completing Phase 1 interactive questions, generate `PRD_QUESTIONS.md` for remaining details.

**Inform User**:
"Great! I understand your vision:
- **Vision**: [Summary]
- **Problem**: [Summary]
- **Users**: [Summary]
- **Success**: [Summary]

Now I'll generate a questionnaire for the detailed requirements (features, constraints, scope). You can answer these at your own pace.

**Generating**: `PRD_QUESTIONS.md`..."

**Generate Questionnaire File**:

````markdown
# Product Requirements Questionnaire

**Project**: [Project name from user's input]
**Date**: [Current date]

**Foundation (from interactive session)**:
- **Vision**: [Vision from Question 1]
- **Problem**: [Problem from Question 2]
- **Target Users**: [Users from Question 3]
- **Inspiration**: [Inspiration from Question 4, if provided]
- **Success Vision**: [Success from Question 5]

---

## Instructions

- Replace `[YOUR ANSWER]` with your response
- Be as detailed or brief as needed
- Skip optional sections marked (Optional) if not applicable
- Feel free to add notes/context anywhere
- **Save this file and run**: `/prd --process PRD_QUESTIONS.md`

---

## Section 1: Core Features

⚠️ **STAY NON-TECHNICAL**: Focus on WHAT users need to do, NOT HOW it will be implemented.

### 1.1 The ONE Must-Have Feature

**What's the ONE thing users absolutely must be able to do?**

[YOUR ANSWER]

**Why is this essential?**

[YOUR ANSWER]

---

### 1.2 User Journey

**Walk me through a typical user's journey from start to finish:**

Example format:
1. User arrives at...
2. User does...
3. System responds with...
4. User achieves...

[YOUR ANSWER]

---

### 1.3 All Features List

**List all features/capabilities you envision (we'll prioritize in next questions):**

1. [YOUR ANSWER]
2. [YOUR ANSWER]
3. [YOUR ANSWER]
... (add as many as needed)

---

### 1.4 Feature Prioritization

**From your list above, which are MUST HAVE (P0) - can't launch without these:**

[YOUR ANSWER - List feature numbers or names]

**Which are SHOULD HAVE (P1) - important but can wait:**

[YOUR ANSWER]

**Which are NICE TO HAVE (P2) - future enhancements:**

[YOUR ANSWER]

---

### 1.5 Content & Navigation (if applicable)

**What types of content will users see?** (e.g., blog posts, pages, images, videos)

[YOUR ANSWER or "N/A"]

**How should users navigate through the content?** (e.g., categories, search, chronological, filters)

[YOUR ANSWER or "N/A"]

**What actions can users take?** (e.g., read, create, comment, share, subscribe, purchase)

[YOUR ANSWER or "N/A"]

---

## Section 2: Technical Constraints

⚠️ **NOTE**: This captures constraints, NOT specific technology choices. Technology decisions happen in `/tech-req` command.

### 2.1 Deployment

**Where should this run?**
- [ ] Cloud (AWS/Azure/GCP)
- [ ] Local/On-premises
- [ ] Hybrid
- [ ] Other: [Specify]

**Your Choice**: [YOUR ANSWER]

**If Cloud, any provider preference?**
- [ ] AWS
- [ ] Azure
- [ ] GCP
- [ ] No preference

**Your Choice**: [YOUR ANSWER or "N/A"]

**Why this deployment approach?**

[YOUR ANSWER]

---

### 2.2 Scale & Performance

**How many people would use this at once?**
- [ ] Just me
- [ ] Small team (<10)
- [ ] Department (10-100)
- [ ] Organization (100-1000)
- [ ] Public internet (1000+)

**Your Choice**: [YOUR ANSWER]

**Any performance requirements?** (e.g., page load time < 2s, response time < 500ms)

[YOUR ANSWER or "No specific requirements"]

---

### 2.3 Data & Integration

**Does this need to connect to any existing systems?** (APIs, databases, third-party services)

[YOUR ANSWER or "No"]

**If yes, what systems and why?**

[YOUR ANSWER]

**Do you need to store data?** (beyond simple static content)

[YOUR ANSWER - Yes/No]

**If yes, what kind and how much?** (e.g., user profiles - 100 users, transaction logs - 10K/month)

[YOUR ANSWER]

**Do you need user authentication?**
- [ ] No authentication needed
- [ ] Single user only (just me)
- [ ] Multiple users (team/organization)
- [ ] Public users (anyone can sign up)
- [ ] Third-party login needed (Google, GitHub, etc.)

**Your Choice**: [YOUR ANSWER]

---

### 2.4 Team & Technology

**What's your team's technical comfort level?**
- [ ] Beginner - Prefer simple, managed solutions
- [ ] Intermediate - Comfortable with most tools
- [ ] Advanced - Can handle complex setups

**Your Choice**: [YOUR ANSWER]

**Any existing technologies you MUST use?** (company standards, existing stack, licensing)

[YOUR ANSWER or "No requirements"]

**Any technologies you MUST avoid?** (licensing issues, past problems, company policy)

[YOUR ANSWER or "No constraints"]

---

## Section 3: Constraints & Scope

### 3.1 Timeline

**When would you like this working?**

[YOUR ANSWER - Target date or timeframe]

**Any key milestones or deadlines?**

[YOUR ANSWER or "No specific milestones"]

---

### 3.2 Budget

**Any budget constraints for infrastructure/hosting costs?**

[YOUR ANSWER - e.g., "Under $10/month", "No specific budget", "$100-500/month"]

**How much time can you invest in development?**

[YOUR ANSWER - e.g., "10 hours/week", "Full-time for 2 weeks", "As needed"]

---

### 3.3 Security & Compliance

**Any security or compliance requirements?** (HIPAA, SOC2, GDPR, data residency, etc.)

[YOUR ANSWER or "No specific requirements"]

**If yes, explain:**

[YOUR ANSWER]

---

### 3.4 Maintenance

**What are you comfortable maintaining long-term?**

[YOUR ANSWER - e.g., "Simple setup I can manage myself", "Don't mind complexity if it's documented", "Prefer managed services"]

---

### 3.5 Out of Scope

**What is explicitly OUT of scope for the first version?**

1. [YOUR ANSWER]
2. [YOUR ANSWER]
... (add as many as needed)

**If you had to cut features, what's the absolute minimum viable version?**

[YOUR ANSWER]

---

## Section 4: Success Metrics

### 4.1 User Success Metrics

**How will you know this is working well for users?**

[YOUR ANSWER]

**What metrics would you track?** (e.g., daily active users, time on site, task completion rate)

1. [YOUR ANSWER]
2. [YOUR ANSWER]
... (add as many as needed)

---

### 4.2 Technical Success Metrics

**What technical metrics matter?** (e.g., uptime, response time, error rate)

[YOUR ANSWER]

**Any specific targets?** (e.g., 99% uptime, page load < 2s)

[YOUR ANSWER or "No specific targets"]

---

### 4.3 Acceptance Criteria

**What specific things must work for you to consider this "done"?**

- [ ] [YOUR ANSWER - Specific testable criterion]
- [ ] [YOUR ANSWER - Specific testable criterion]
- [ ] [YOUR ANSWER - Specific testable criterion]
... (add as many as needed)

---

## Section 5: User Journeys (Optional but Recommended)

### 5.1 Primary User Journey

**Describe the main user flow in detail:**

**Journey Name**: [e.g., "First-time visitor discovers and reads content"]

1. User starts at: [Entry point]
2. User does: [Action]
3. System responds with: [Response]
4. User does next: [Next action]
5. User achieves: [Outcome/goal]

[YOUR ANSWER]

---

### 5.2 Secondary User Journey (Optional)

**If applicable, describe a secondary important flow:**

**Journey Name**: [e.g., "Content creator publishes new article"]

[YOUR ANSWER or "N/A"]

---

## Section 6: Open Questions & Risks (Optional)

### 6.1 Open Questions

**Anything you're still unsure about?**

- [ ] [YOUR QUESTION]
- [ ] [YOUR QUESTION]
... (add as many as needed)

---

### 6.2 Risks & Concerns

**What could go wrong? What are you worried about?**

[YOUR ANSWER or "No major concerns"]

---

## Next Steps

**When you're done**:
1. Save this file
2. Run: `/prd --process PRD_QUESTIONS.md`
3. I'll generate your comprehensive PRD.md!
````

**After generating file, tell user**:

"✅ **Questionnaire Generated!** I've created `PRD_QUESTIONS.md` with all the detailed questions.

**Next Steps**:
1. Open `PRD_QUESTIONS.md` and fill in your answers (replace `[YOUR ANSWER]` placeholders)
2. Take your time - there's no rush. Think through features, prioritization, and constraints
3. When done, save the file and run: `/prd --process PRD_QUESTIONS.md`
4. I'll generate your comprehensive `PRD.md`!

The questionnaire has 6 sections:
- Section 1: Core Features (what users can do)
- Section 2: Technical Constraints (deployment, scale, data needs)
- Section 3: Constraints & Scope (timeline, budget, out-of-scope items)
- Section 4: Success Metrics (how to measure success)
- Section 5: User Journeys (optional but helpful)
- Section 6: Open Questions & Risks (optional)

Feel free to skip optional sections or add notes anywhere!"

---

## Questionnaire Processing

This section is used when user runs `/prd --process PRD_QUESTIONS.md` after filling out the questionnaire.

### Step 1: Read and Validate Questionnaire

Read `PRD_QUESTIONS.md` file and extract all answers.

**Validate completeness**:
- Check that required sections have answers (Section 1-4)
- Note any skipped optional sections
- Identify incomplete answers marked as `[YOUR ANSWER]`

If critical sections are incomplete:
"⚠️ I noticed some required sections are incomplete:
- [List incomplete sections]

Would you like to:
1. Fill in these sections now (I'll wait)
2. Proceed with what you have (I'll note gaps in PRD)
3. Cancel and complete later"

**Wait for user response if incomplete.**

---

### Step 2: Generate Comprehensive PRD.md

Using answers from questionnaire and foundation from Phase 1, generate complete PRD.

**Inform user**:
"Processing your questionnaire answers and generating comprehensive PRD.md...

**Creating PRD.md**"

**Generate PRD.md file**:

```markdown
# Product Requirement Document: [Project Name]

**Created**: [Date]
**Version**: 1.0
**Status**: Ready for Review → Technical Requirements or Implementation

---

## Executive Summary

[2-3 sentence overview synthesized from vision, problem, and key features]

Example: "[Project name] is a [type of product] that [solves problem] for [target users]. It enables users to [key capability] through [approach]. Success will be measured by [top 2 metrics]."

---

## Vision Statement

[Vision from Phase 1 Question 1, expanded if needed]

---

## Problem Statement

### The Problem

[Problem from Phase 1 Question 2]

### Current Situation

[Current workarounds from Phase 1, or "Currently, [describe current state]"]

### Impact

[Why this problem matters - synthesized from user answers]

---

## Target Users

### Primary Users

- **Who**: [From Phase 1 Question 3]
- **Needs**: [Synthesized from features and user journey]
- **Current Pain**: [From problem statement]

### Secondary Users

[From Phase 1 Question 3 if mentioned, otherwise "None identified"]

### User Success

[From Phase 1 Question 3 follow-up]

---

## Inspiration & Context

[From Phase 1 Question 4 if provided, otherwise skip this section]

**Examples/Inspiration**: [Examples mentioned]

**What to Emulate**: [Positive aspects to copy]

**What to Avoid**: [Things to do differently]

---

## Goals & Success Criteria

### Product Goals

[Synthesize 2-3 SMART goals from success vision and features]

1. [Goal 1]: [Specific, measurable goal]
2. [Goal 2]: [Specific, measurable goal]
3. [Goal 3]: [Specific, measurable goal]

### Success Metrics

**User Metrics**:
[From Section 4.1 of questionnaire]

**Technical Metrics**:
[From Section 4.2 of questionnaire]

### Acceptance Criteria

[From Section 4.3 of questionnaire - the specific testable criteria]

---

## Core Features

### Must Have (P0) - Launch Blockers

[From Section 1.1 and 1.4 of questionnaire - the essential features]

For each P0 feature:
1. **[Feature Name]**
   - **Description**: [What it does]
   - **User Value**: [Why users need this]
   - **Priority**: P0
   - **Success Criteria**: [How we know it works]

### Should Have (P1) - Important But Can Wait

[From Section 1.4 of questionnaire - P1 features]

### Nice to Have (P2) - Future Enhancements

[From Section 1.4 of questionnaire - P2 features]

---

## User Journeys

### Primary User Journey: [Journey name from Section 5.1]

[User journey from Section 5.1 of questionnaire, formatted as numbered steps]

### Secondary User Journey (if provided)

[From Section 5.2 if answered, otherwise skip]

---

## Technical Constraints

⚠️ **Note**: These are constraints only. Specific technology choices will be evaluated in Technical Requirements phase using `/tech-req` command.

### Deployment

- **Environment**: [From Section 2.1 - Cloud/Local/Hybrid]
- **Provider Preference**: [From Section 2.1 - AWS/Azure/GCP if specified]
- **Rationale**: [Why this deployment approach from Section 2.1]

### Scale & Performance

- **Expected Concurrency**: [From Section 2.2 - user count]
- **Performance Requirements**: [From Section 2.2 - specific targets if provided]

### Data & Integration

- **External Systems**: [From Section 2.3 - systems to integrate]
- **Data Storage Needs**: [From Section 2.3 - type and volume]
- **Authentication Requirements**: [From Section 2.3 - auth needs]

### Team & Technology

- **Technical Comfort Level**: [From Section 2.4]
- **Must Use**: [From Section 2.4 - required technologies]
- **Must Avoid**: [From Section 2.4 - technologies to avoid]

---

## Constraints & Assumptions

### Timeline

- **Target Launch**: [From Section 3.1]
- **Key Milestones**: [From Section 3.1 if provided]

### Budget

- **Infrastructure Budget**: [From Section 3.2 - hosting costs]
- **Development Time Available**: [From Section 3.2]

### Security & Compliance

[From Section 3.3 - requirements if any, otherwise "No specific security or compliance requirements identified"]

### Maintenance Expectations

[From Section 3.4 - what user is comfortable maintaining]

### Assumptions

- [List any assumptions made based on answers]
- [E.g., "Assuming single-user initially based on scale requirements"]

---

## Explicitly Out of Scope

The following are **NOT** included in the first version:

[From Section 3.5 - list of out-of-scope items]

### Minimum Viable Product (MVP)

If all features were cut except the absolute essentials:

[From Section 3.5 - minimum viable version]

---

## Open Questions & Risks

### Open Questions

[From Section 6.1 if provided, otherwise "No open questions identified"]

### Risks & Concerns

[From Section 6.2 if provided, otherwise "No major risks identified at this stage"]

### Mitigation Strategies

[For each risk identified, suggest mitigation approach]

---

## Dependencies

### External Dependencies

[Derived from Section 2.3 - external systems and integrations]

### Internal Dependencies

[Derived from feature dependencies and constraints]

---

## Next Steps

### Immediate Actions

1. **Review & Approve PRD** - Ensure this captures your vision accurately
2. **Gather Technical Requirements** - Run `/tech-req` to evaluate technology choices and architecture
3. **Begin Implementation** - Use EPCC workflow (`/epcc-explore`, `/epcc-plan`, `/epcc-code`) or start directly

### Recommended Path

**For well-defined projects**: `/tech-req` → `/epcc-plan` → `/epcc-code`
**For greenfield exploration**: `/epcc-explore` → `/tech-req` → `/epcc-plan` → `/epcc-code`
**For simple projects**: Start implementing directly from this PRD

---

## Appendix

### Reference Materials

[List any URLs, documents, or examples mentioned during discovery]

### Version History

- v1.0 ([Date]): Initial PRD generated from discovery questionnaire
```

**After generating PRD.md, tell user**:

"✅ **PRD Complete!** I've generated `PRD.md` with your comprehensive product requirements.

**What's in the PRD**:
- Executive summary and vision statement
- Problem statement and target users
- Prioritized features (P0/P1/P2)
- User journeys
- Technical constraints
- Timeline and budget constraints
- Success metrics and acceptance criteria
- Out-of-scope items and risks

**Next Steps - Choose Your Path**:

1. **Technical Requirements** (Recommended): Run `/tech-req` to evaluate technologies and architecture
2. **EPCC Workflow**: Run `/epcc-explore` to understand existing patterns, then `/epcc-plan` for implementation strategy
3. **Direct Implementation**: Start building based on this PRD if requirements are clear

**Review Your PRD**:
- Read through `PRD.md` and verify it captures your vision
- Add any missing details or clarifications
- Share with stakeholders for feedback if needed

The PRD is your north star for all subsequent work. Keep it updated as requirements evolve!"

---

## Conversation Guidelines for Phase 1

### Stay Product-Focused, Not Technical
⚠️ **CRITICAL**: PRD focuses on WHAT users need, NOT HOW it will be built.

❌ **DON'T ASK**: "Should users write posts in Markdown or use a rich text editor?"
✅ **DO ASK**: "Who will be creating the blog posts - you, a team, or end users?"

❌ **DON'T ASK**: "Do you want a web-based admin interface or file-based editing?"
✅ **DO ASK**: "How often will content be updated, and by whom?"

❌ **DON'T ASK**: "Should we use React or Vue for the frontend?"
✅ **DO ASK**: "What devices will users access this from? (desktop, mobile, tablets)"

❌ **DON'T ASK**: "Do you want to use a database or static files?"
✅ **DO ASK**: "How much content do you expect to have? (10 posts, 1000 posts, 10000 posts)"

### Let Technical Questions Wait for /tech-req
When you catch yourself about to ask a technical question:
✅ **SAY**: "That's a great technical question - we'll evaluate implementation options in the `/tech-req` command. For now, let's focus on what users need to do."

### Be Socratic About Product Requirements
❌ **DON'T SAY**: "You should add a search feature"
✅ **DO SAY**: "If someone visits your blog looking for a specific topic, how would you want them to find it? Browse categories? Search? Something else?"

### Acknowledge Uncertainty
❌ **DON'T SAY**: "This will definitely work"
✅ **DO SAY**: "Based on similar projects, this approach typically works well for [use case]"

### Ask Follow-ups
When user says something vague:
- "Can you give me an example of what that would look like?"
- "Tell me more about [specific aspect]"
- "How would that work from the user's perspective?"

### Reflect Back After Phase 1
After completing Phase 1 questions, summarize:
✅ "So if I understand correctly:
- **Vision**: [Summary]
- **Problem**: [Summary]
- **Users**: [Summary]
- **Success**: [Summary]

Does this capture your vision? Anything to add or correct?"

**Wait for confirmation before generating questionnaire.**
