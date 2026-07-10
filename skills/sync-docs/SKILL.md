---
name: sync-docs
description: Analyze documentation drift and generate sync reports for any project. Enhanced with Serena semantic discovery for deep code analysis. Use when: "sync docs", "check documentation", "documentation drift", "doc audit", "/sync-docs". Supports --semantic flag for AI-powered undocumented code discovery.
---

# Sync Docs - Universal Documentation Synchronization

Analyze any codebase and its documentation to identify drift and generate actionable sync reports. **Enhanced with Serena for semantic code discovery.**

## Invocation

```bash
/sync-docs                          # Generate full drift report
/sync-docs --check                  # Only show drift report (no suggestions)
/sync-docs --suggest-updates        # Include proposed markdown for updates
/sync-docs --semantic               # Use Serena for deep code discovery
/sync-docs --compare <section>      # Deep-dive analysis of specific section
/sync-docs --verbose                # Include detailed file references
/sync-docs --diagrams-only          # Audit only docs/diagrams/
```

## Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     SYNC-DOCS WORKFLOW                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Phase 1: Discover Project Structure                                     │
│    ├─ Identify documentation files (README, CLAUDE.md, docs/)           │
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

Scan for primary documentation:
- `README.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`
- `docs/`, `documentation/`, `wiki/`, `guides/`
- `docs/diagrams/`, `docs/internal_documentation/`
- API docs: `openapi.yaml`, `swagger.json`, `api-docs/`

### 1.2 Detect Project Type

| Project Type | Indicators |
|--------------|------------|
| Microservices | Multiple service directories, docker-compose.yml, k8s configs |
| Monolithic | Single main application, traditional MVC structure |
| Library | package.json/setup.py/Cargo.toml with library config |
| Frontend | React/Vue/Angular configs, public/static directories |
| Serverless | serverless.yml, SAM templates, Lambda functions |

### 1.3 Extract Documented Elements

From discovered documentation:
- Services/components with descriptions
- Architecture patterns and design decisions
- Technology stack and dependencies
- Feature flags and configuration options
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
- Extract environment variables from docker-compose.yml
- Compare against documented configuration
- Identify undocumented feature flags
- Check container counts (documented vs actual)

### 2.3 Version and Date Check

- Verify version numbers match latest release
- Check "Last Updated" dates aren't stale
- Validate service counts in documentation

---

## Phase 2.5: Semantic Discovery (--semantic flag)

**When `--semantic` flag is provided**, use Serena MCP servers for deep code discovery.

### Prerequisites

- Serena MCP server running with project activated

### Step 1: Compare to Documentation

For each discovered file:
1. Check if file/class is mentioned in any documentation
2. If NOT mentioned → flag as **UNDOCUMENTED**

### Step 3: Serena Precise Navigation

For each undocumented entity, extract precise details:

```javascript
// Execute via mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

// First activate project
await serena.activate_project({ project: "/path/to/project" });

// Get symbol overview for each discovered file
const symbols = await serena.get_symbols_overview({
  relative_path: "path/to/undocumented/file.py"
});
// Returns: { Class: ['ClassName'], Function: ['func_name'], Constant: [...] }

// For deeper analysis
const classDetails = await serena.find_symbol({
  name: "DiscoveredClassName",
  symbol_type: "class"
});
```

**Extract for documentation:**
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
- **Recommended Action**: Add section following [existing pattern]

### Coverage Summary
- Files discovered via Serena: X
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
- [ ] Item with file reference

## High Priority Updates
[Impacts daily workflow]
- [ ] Item with file reference

## Medium Priority Updates
[Improves clarity]
- [ ] Item with file reference

## Low Priority Updates
[Minor improvements]
- [ ] Item with file reference

## Semantic Discovery Findings (if --semantic)
[Undocumented code patterns found]

## Detailed Action Items
### 1. [File Path]
- **Current state**: [what's documented]
- **Actual state**: [what's in codebase]
- **Suggested update**: [markdown snippet]

## Summary
- Total gaps: X
- Critical: Y
- From semantic discovery: Z
```

---

## Phase 4: Present Results

| Flag | Behavior |
|------|----------|
| `--check` | Report only, no suggestions |
| `--suggest-updates` | Include proposed markdown patches |
| `--semantic` | Run Theo+Serena discovery (Phase 2.5) |
| `--compare <section>` | Deep-dive single section |
| `--verbose` | Include line numbers and full context |
| `--diagrams-only` | Audit visual documentation only |

---

## When to Use `--semantic`

**Best for:**
- After major refactoring or new service deployment
- When documentation health score is low
- Comprehensive quarterly audits
- When you suspect undocumented features exist
- Large codebases where manual discovery is impractical

**Key insight:**
- Theo answers: "What code exists that docs don't mention?"
- Serena answers: "What exactly does that code do?"
- Combined: Complete picture of documentation gaps

---

## Examples

### Basic Drift Check
```
User: /sync-docs --check
Claude:
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
Claude:
Phase 1: Discovering project structure...
Phase 2: Traditional audit...
Phase 2.5: Semantic discovery with Theo + Serena...

Theo found 13 files related to "scheduler service background"
Serena extracted: CSOPMScheduler, CSOPMJIRAPoller, CSOPMSlackNotifier...

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
Claude:
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

- Tool adapts to any project structure
- Configuration optional (auto-discovery handles most cases)
- Prioritization focuses effort on important gaps
- `--semantic` requires Theo index and Serena project activation
- Health score accounts for both traditional and semantic findings
