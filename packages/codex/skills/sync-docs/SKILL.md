---
name: sync-docs
description: Analyze documentation drift and generate sync reports for any project. Enhanced with Serena semantic discovery for deep code analysis. Use when asked to sync docs, check documentation, audit documentation drift, or when $coderails-codex:sync-docs is invoked. Supports --semantic for deeper undocumented-code discovery.
---

# Sync Docs - Universal Documentation Synchronization

Compare a codebase with its documentation. Report differences and how to correct them.
Use Serena for semantic code discovery when the user selects that option.

## Invocation

```bash
/sync-docs                          # Write the full drift report
/sync-docs --check                  # Only show drift report (no suggestions)
/sync-docs --suggest-updates        # Include proposed markdown for updates
/sync-docs --semantic               # Use Serena for deep code discovery
/sync-docs --compare <section>      # Examine one named section
/sync-docs --verbose                # Include file paths and line numbers
/sync-docs --diagrams-only          # Audit only docs/diagrams/
```

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     SYNC-DOCS WORKFLOW                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Phase 1: Discover Project Structure                                     │
│    ├─ Identify documentation files (README, AGENTS.md, docs/)           │
│    ├─ Detect project type (microservices, monolithic, library)          │
│    └─ Extract documented components and services                         │
│                                                                          │
│  Phase 2: Traditional Audit                                              │
│    ├─ Compare documented vs actual components                           │
│    ├─ Verify configuration documentation                                │
│    ├─ Check version numbers and dates                                   │
│    └─ Validate diagrams match code                                       │
│                                                                          │
│  Phase 2.5: Semantic Discovery (--semantic)          ◀── NEW            │
│    ├─ Serena: Precise symbol extraction                                  │
│    └─ Cross-reference: Match code entities to docs                       │
│                                                                          │
│  Phase 3: Generate Drift Report                                          │
│    ├─ Prioritize findings (Critical → Low)                              │
│    ├─ Provide specific file references                                   │
│    └─ Include health score                                               │
│                                                                          │
│  Phase 4: Suggest Updates (--suggest-updates)                           │
│    └─ Generate markdown patches for each gap                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Discover Project Structure

### 1.1 Identify Documentation Sources

Find primary documentation:
- `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`
- `docs/`, `documentation/`, `wiki/`, `guides/`
- `docs/diagrams/`, `docs/internal_documentation/`
- API docs: `openapi.yaml`, `swagger.json`, `api-docs/`

### 1.2 Detect Project Type

| Project Type | Indicators |
|--------------|------------|
| Microservices | Multiple service directories, docker-compose.yml, k8s configs |
| Monolithic | One application, traditional MVC structure |
| Library | package.json/setup.py/Cargo.toml with library config |
| Frontend | React/Vue/Angular configs, public/static directories |
| Serverless | serverless.yml, SAM templates, Lambda functions |

### 1.3 Extract Documented Elements

From discovered documentation:
- Documented service and component names with descriptions
- Architecture patterns and design decisions
- Technology stack and dependencies
- Configuration options and feature flags
- Deployment procedures
- Container/service counts

---

## Phase 2: Traditional Audit

### 2.1 Component Verification

```bash
# Compare documented services to actual directories
ls -d */ | grep -v node_modules
```

- Check if all discovered services/modules are documented
- Identify orphaned documentation (describes non-existent components)
- Validate inter-component dependencies

### 2.2 Configuration Audit

If infrastructure files exist:
- Read the environment assignments from docker-compose.yml
- Compare against documented configuration
- Identify undocumented feature flags
- Check container counts (documented vs actual)

### 2.3 Version and Date Check

- Check version numbers against the latest release
- Check "Last Updated" dates are not stale
- Validate service counts in documentation

---

## Phase 2.5: Semantic Discovery (--semantic flag)

If the user supplies `--semantic`, use Serena MCP servers for deep code discovery.

### Prerequisites

- An active Serena MCP server with the project activated

### Step 1: Compare to Documentation

For each discovered file:
1. Check the documentation for the file or class.
2. If the documentation does not identify it, mark it **UNDOCUMENTED**.

### Step 3: Serena Precise Navigation

Get these facts for each undocumented entity:

```javascript
// Use mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

// First activate project
await serena.activate_project({ project: "/path/to/project" });

// Get symbol overview for each discovered file
const symbols = await serena.get_symbols_overview({
  relative_path: "path/to/undocumented/file.py"
});
// Result: { Class: ['ClassName'], Function: ['func_name'], Constant: [...] }

// For deeper analysis
const classDetails = await serena.find_symbol({
  name: "DiscoveredClassName",
  symbol_type: "class"
});
```

**Collect for documentation:**
- Class names and purposes
- Method signatures
- Constants and configuration values
- Protocol/interface definitions
- Dependencies on other services

### Step 4: Generate Semantic Discovery Report

```markdown
## Semantic Discovery Findings (Serena)

### Undocumented Code Discovered

#### 1. [Component Name]
- **Source Files**: `path/to/file.py`
- **Classes** (Serena): ClassName1, ClassName2
- **Protocols**: ProtocolName1, ProtocolName2
- **Missing From**: doc1.md, doc2.md
- **Recommended step**: Add a section in the format of [existing pattern]

### Coverage Summary
- Files discovered through Serena: X
- Undocumented entities: Y
- Documentation coverage: Z%
```

---

## Phase 3: Generate Drift Report

### Report Format

```markdown
# Documentation Drift Report - [Project Name]

## Overall Health Score
[X% of documentation is current and accurate]

## Critical Updates Needed
[Blocks understanding or deployment]
- [ ] Item with file and line

## High Priority Updates
[Has an effect on daily workflow]
- [ ] Item with file and line

## Medium Priority Updates
[Makes the text clearer]
- [ ] Item with file and line

## Low Priority Updates
[Small improvements]
- [ ] Item with file and line

## Semantic Discovery Findings (if --semantic)
[Undocumented code patterns found]

## Detailed Action Items
### 1. [File Path]
- **Current documentation**: [what's documented]
- **Actual code**: [what's in codebase]
- **Suggested update**: [markdown snippet]

## Summary
- Total differences: X
- Differences that block understanding or deployment: Y
- From semantic discovery: Z
```

---

## Phase 4: Present Results

| Flag | Behavior |
|------|----------|
| `--check` | Report only, no suggestions |
| `--suggest-updates` | Include proposed markdown patches |
| `--semantic` | Run Serena semantic discovery (Phase 2.5) |
| `--compare <section>` | Deep-dive single section |
| `--verbose` | Include line numbers and full context |
| `--diagrams-only` | Audit visual documentation only |

---

## When to Use `--semantic`

**Best for:**
- After large refactoring or new service deployment
- When documentation health score is low
- Full audits each quarter
- When you think the code has undocumented features
- Large codebases where manual discovery is impractical

**Key insight:**
- Serena answers two questions: "What code exists that docs don't mention?" and "What exactly does that code do?"
- Use those answers to find differences between the code and the documentation.

---

## Examples

### Basic Drift Check
```
User: /sync-docs --check
Codex:
Scanning project structure...
Found 4 documentation files, 7 services

Documentation Drift Report - myproject

Health Score: 68%

Critical:
- [ ] CSOPM Notifier missing from 04-background-services.md

High:
- [ ] Container count wrong (docs: 11, actual: 12)
- [ ] Version stale (docs: v2.360.347, actual: v2.360.369)
```

### With Semantic Discovery
```
User: /sync-docs --semantic
Codex:
Phase 1: Discovering project structure...
Phase 2: Traditional audit...
Phase 2.5: Semantic discovery with Serena...

Serena found 13 files related to "scheduler service background" and extracted: CSOPMScheduler, CSOPMJIRAPoller, CSOPMSlackNotifier...

Semantic Discovery Findings:
- notifier_service/ (7 files) - UNDOCUMENTED
  Classes: CSOPMScheduler, CSOPMJIRAPoller, CSOPMSlackNotifier,
           CSOPMReminderService, CSOPMTicketStatusPoller
  Protocols: 9 TypedDI protocols in csopm_protocols.py
  Missing from: All diagram docs, feature_flags.md

Health Score: 52% (dropped due to semantic findings)
```

### Generate Update Suggestions
```
User: /sync-docs --suggest-updates
Codex:
[Full report plus:]

Suggested Updates:

### For 04-background-services.md

Add after section 6:

```markdown
### 7. notifier-service (SINGLETON)

**Purpose:** Automated CSOPM ticket assignment notifications

**Schedule:** 08:00 and 16:00 UTC daily

**Services:**
- CSOPMJIRAPoller - Poll JIRA for assignments
- CSOPMSlackNotifier - Send Slack DMs
- CSOPMReminderService - RCA/closure reminders
...
```
```

---

## Notes

- The tool adapts to the project structure
- Configuration is optional. The tool finds settings automatically for most projects.
- The report puts important differences first
- `--semantic` requires Serena project activation
- The health score includes traditional and semantic results
