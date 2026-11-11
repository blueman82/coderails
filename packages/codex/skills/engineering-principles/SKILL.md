---
name: engineering-principles
description: Enforce engineering principles (YAGNI, KISS, DRY, Fail Fast, SSOT, Law of Demeter) and language-specific coding standards (Python/Go/TypeScript/Bash) on code being written or modified. Uses Serena LSP for call site analysis and reference counting. Use PROACTIVELY when writing, modifying, or reviewing code. Triggers on code changes, "enforce standards", "check principles", "apply standards", "code quality", or explicit /engineering-principles command.
allowed-tools: Read, Write, Edit, Glob, Grep, Skill, mcp__mcp-exec__*
---

# Engineering Principles & Language Standards

**Version:** 4.0.0
**Purpose:** Apply engineering principles and language-specific idioms.
Use Serena LSP to check structure and count uses of symbols. Invoke the applicable language skill for idioms.

## When to Activate

**Proactively** (without user asking):
- After you write or change code
- When you examine code changes before commit
- When implementing features or fixing bugs

**Explicitly** (user invokes `/engineering-principles`):
- Point at a file or directory to audit and fix

---

## PHASE 0: Language Detection & Dispatch (MANDATORY)

**Identify the language before analysis. Invoke the applicable sub-skill:**

| File Extension | Invoke Skill |
|----------------|--------------|
| `.go` | Run `engineering-principles-go` skill |
| `.py` | Run `engineering-principles-python` skill |
| `.ts`, `.tsx` | Run `engineering-principles-ts` skill |
| `.sh` (or no extension with a `bash`/`sh` shebang, e.g. `#!/usr/bin/env bash`) | Run `engineering-principles-bash` skill |

**The language-specific skill provides idioms, patterns, and examples. This coordinator provides universal principles and MCP analysis.**

---

## Phase 1: MCP Environment Setup

Before analysis, activate Serena for the current project.

```javascript
// Use mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

// Test connectivity
const serenaConfig = await serena.get_current_config();
const hasSerena = !!serenaConfig;

console.log("Serena (LSP):", hasSerena ? "OK" : "UNAVAILABLE - falling back to static analysis");

// Activate Serena project if available
if (hasSerena) {
  await serena.activate_project({ project: process.cwd() });
}
```

**Fallback:** If Serena is unavailable, use Read/Grep/Glob for file-level static analysis.

---

## Phase 2: Structural Analysis via Serena (LSP)

Use Serena to get accurate structural data for the principle checks.

### 2.1 Symbol Overview

```javascript
// Use mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

const symbols = await serena.get_symbols_overview({ relative_path: "TARGET_FILE" });

// Collect all symbols for analysis
const allSymbols = [
  ...(symbols.classes || []),
  ...(symbols.functions || []),
  ...(symbols.methods || [])
];
```

### 2.2 Reference Counting (YAGNI Detection)

```javascript
async function checkYAGNI(symbolName) {
  const refs = await serena.find_referencing_symbols({ name_path: symbolName });
  return {
    symbol: symbolName,
    referenceCount: refs.length || 0,
    isDeadCode: (refs.length || 0) === 0,
  };
}
```

**YAGNI rule:** If `referenceCount === 0` and symbol is not exported/public, flag for deletion.

### 2.3 Symbol Depth Analysis (Law of Demeter)

```javascript
async function checkDemeter(symbolName) {
  const detail = await serena.find_symbol({ name: symbolName, depth: 3 });
  const body = detail.body || '';

  // Find a.b.c.d chains (3+ dots)
  const chainPattern = /\w+(?:\.\w+){3,}/g;
  const chains = body.match(chainPattern) || [];

  return { symbol: symbolName, demeterViolations: chains };
}
```

### 2.4 Class Structure Analysis (KISS)

```javascript
async function checkKISS(className) {
  const detail = await serena.find_symbol({ name: className, depth: 2 });
  const children = detail.children || [];
  const methods = children.filter(c => c.kind === 'method' || c.kind === 'function');

  return {
    className,
    methodCount: methods.length,
    isTrivialClass: methods.length === 1,
    hasDeepHierarchy: (detail.bases || []).length > 2,
  };
}
```

### 2.5 Return Value Contract Verification

If a function gives status dicts, enums, or tagged unions, check how all callers handle the possible results:

```javascript
// Use mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

async function checkReturnContracts(functionName) {
  // 1. Read the function body to find all result paths
  const detail = await serena.find_symbol({ name: functionName, depth: 2 });
  const body = detail.body || '';

  // 2. Get all different result values (status strings, enum variants, error types)
  const returnStatuses = body.match(/return\s+\{[^}]*"status":\s*"(\w+)"/g) || [];
  const statusValues = [...new Set(returnStatuses.map(r => r.match(/"(\w+)"$/)?.[1]).filter(Boolean))];

  // 3. Find all callers
  const callers = await serena.find_referencing_symbols({ name_path: functionName });

  // 4. Check the results each caller handles
  for (const caller of callers) {
    const callerBody = (await serena.find_symbol({ name: caller.name, depth: 1 })).body || '';
    const handledStatuses = statusValues.filter(s => callerBody.includes(`"${s}"`));
    const unhandled = statusValues.filter(s => !handledStatuses.includes(s));

    if (unhandled.length > 0) {
      console.log(`[CONTRACT] ${caller.name} does not handle: ${unhandled.join(', ')} from ${functionName}`);
    }
  }
}
```

**Contract rule:** If a function gives N different status values and a caller checks only M < N, flag "silent failure path" (HIGH severity).
Prefer allowlist checks (`status not in (good_values)`) to blocklist checks (`status == "error"`) so an unknown status blocks work.

---

## Core Principles (Universal)

Each code change MUST be checked against these six principles:

| # | Principle | What to Look For | Best Tool |
|---|-----------|-------------------|-----------|
| 1 | **YAGNI** | Unneeded code, speculative features, dead branches | Serena `find_referencing_symbols` for LSP data. If unavailable, use Grep for call sites. |
| 2 | **KISS** | Over-engineered abstractions, trivial classes | Serena `find_symbol` depth → single-method classes |
| 3 | **DRY** | Duplicated logic across files | Grep/Glob for matching signatures or body fragments across files |
| 4 | **`Fail Fast`** | Late validation, deep nesting before error checks | Serena `find_symbol` body → nesting depth |
| 5 | **SSOT** | Duplicated runtime data or config | Grep for the same config key/value in 2+ files |
| 6 | **Law of Demeter** | `a.b.c.d` chains | Serena `find_symbol` body → chain regex |

**Tool selection rule:** If Serena is available, use its authoritative LSP data for analysis in a file.
Use plain Grep/Glob for checks across files and if Serena is unavailable.

### Code Reduction Rules

- No helpers for one-time operations
- Keep three lines that do almost the same work if there is no need for an abstraction
- Remove unneeded code fully (no `_unused` renames, no `# removed` comments)
- If you can change the code directly, do not add a backwards-compatibility shim
- No feature flags for unreleased features

### Comment Discipline

A comment gives the constraint that the code checks. Do not cite the conversation, inspection, or session artifact that led to it.
The comment must make sense to a reader with no session history.

**The dead-link test:** Each ID or label in a comment must resolve to a durable object in the repository or its host platform.
Use a PR number if it identifies a GitHub artifact that readers can check.
A session ID, work-unit label, or reviewer result ID points to a transcript or conversation that the reader does not have.
Do not use those IDs in comments.

Before and after examples from a cleanup sweep:

```diff
- # ── Change #4: extended permanent blocklist ──────────────────────────
+ # ── Permanent blocklist ───────────────────────────────────────────────
```

```diff
- # F1 fix: also match --force and multi-token "-d -f" patterns.
+ # Also matches --force and multi-token "-d -f" patterns.
```

```diff
- # E1: untrusted login posts a byte-identical valid marker → exit 1 (spoofing
- # rejected). Permission defaults to WRITE in the stub — the highest-value
- # regression case in the whole PR: login-match alone must still reject a
- # forged marker regardless of the (now write-capable) permission field.
+ # Spoof rejection: untrusted login posts a byte-identical valid marker → exit 1.
+ # Permission defaults to WRITE in the stub: login-match alone must still reject
+ # a forged marker regardless of the (write-capable) permission field.
```

Each rewrite keeps the property the code tests or checks, the "what" and the "why".
It removes information that only made sense in the inspection or session, such as a change number or correction label.
The phrase "the highest-value regression case in the whole PR" also makes sense only with the session context.

In Coderails repositories, the `comment_citation_gate` PreToolUse hook checks Write/Edit/MultiEdit for this rule.
The rule applies with or without that hook installed.

---

## Enforcement Process

### Step 1: Detect Language & Dispatch
Read the file extension. **Invoke the matching language skill:**
- `.go` → `engineering-principles-go`
- `.py` → `engineering-principles-python`
- `.ts`/`.tsx` → `engineering-principles-ts`
- `.sh` (or no extension with a `bash`/`sh` shebang) → `engineering-principles-bash`

### Step 2: Analyze
- **If Serena is available:** Get a symbol overview, count uses, and check depth (Phase 2)
- **Cross-file analysis:** Use Grep/Glob for duplicate signatures (DRY), the same config keys (SSOT), and call sites (YAGNI)
- **If Serena is unavailable:** Use only file-level static analysis through Read/Grep/Glob

### Step 3: Fix or Flag

**Correct directly** if LSP data shows the change is safe:
- Naming convention violations
- Missing type hints
- Redundant `else` after `return`
- Verbose patterns with idiomatic replacements
- Unneeded imports

**Flag to user** (need confirmation):
- Removing functions with no uses
- Replacing a single-method class
- Moving duplicated code into one shared function or module
- Breaking `a.b.c.d` chains

### Step 4: Report

```
Engineering Principles: <filename>
  Language: Go → invoked engineering-principles-go
  Fixed: 3 violations
    - Removed redundant else after return (L45)
    - Wrapped error with context (L23)
    - Used early return pattern (L12, L18)
  Flagged: 2 issues (LSP-verified)
    - _format_helper() has 0 references [YAGNI] - delete? (L67)
    - Similar to utils.go:78 [DRY] - consolidate? (grep match)
  Memory: Stored enforcement pattern
```

---

## Rules

- Do not change external behavior or public APIs
- Do not remove or simplify error handling
- Always keep test coverage
- If the change is uncertain, report the issue. Do not make the change
- Apply the minimum change needed
- Add features, comments, or docstrings only if necessary
- If Serena is available, use its LSP data for in-file analysis. Use heuristics only if that data is unavailable
- Use Grep/Glob for cross-file checks (DRY/SSOT/YAGNI)
- **Always invoke language-specific skill for idioms**

---
