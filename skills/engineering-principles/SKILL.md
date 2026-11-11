---
name: engineering-principles
description: Enforce engineering principles (YAGNI, KISS, DRY, Fail Fast, SSOT, Law of Demeter) and language-specific coding standards (Python/Go/TypeScript/Bash) on code being written or modified. Uses Serena LSP for call site analysis and reference counting. Use PROACTIVELY when writing, modifying, or reviewing code. Triggers on code changes, "enforce standards", "check principles", "apply standards", "code quality", or explicit /engineering-principles command.
allowed-tools: Read, Write, Edit, Glob, Grep, Skill, mcp__mcp-exec__*
---

# Engineering Principles & Language Standards

**Version:** 4.0.0
**Purpose:** Apply engineering principles and language idioms to code changes.
Use Serena LSP to check code structure and find uses of symbols. Invoke the matching
language skill to check idioms.

## When to Activate

**Proactively** (without user asking):
- After writing or changing code in a file
- When you check code changes before a commit
- When implementing features or fixing bugs

**Explicitly** (user invokes `/engineering-principles`):
- Point at a file or directory to audit and fix

---

## PHASE 0: Language Detection & Dispatch (MANDATORY)

**Before you do the analysis, identify the language and invoke its skill.**

| File Extension | Invoke Skill |
|----------------|--------------|
| `.go` | Invoke `engineering-principles-go` skill |
| `.py` | Invoke `engineering-principles-python` skill |
| `.ts`, `.tsx` | Invoke `engineering-principles-ts` skill |
| `.sh` (or no extension with a `bash`/`sh` shebang, e.g. `#!/usr/bin/env bash`) | Invoke `engineering-principles-bash` skill |

The language skill supplies idioms and examples. This skill applies the
shared principles and MCP analysis.

---

## Phase 1: MCP Environment Setup

Before analysis, activate Serena for the current project.

```javascript
// Run through mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

// Test connectivity
const serenaConfig = await serena.get_current_config();
const hasSerena = !!serenaConfig;

console.log("Serena (LSP):", hasSerena ? "OK" : "UNAVAILABLE - falling back to static analysis");

// Activate Serena project if available
if (hasSerena) {
  await serena.activate_project({ project: process.cwd() });
}
```

**Graceful degradation:** If Serena is unavailable, fall back to file-level static analysis using Read/Grep/Glob. Serena is optional.

---

## Phase 2: Structural Analysis via Serena (LSP)

Use Serena to get specified structural data for principle enforcement.

### 2.1 Symbol Overview

```javascript
// Run through mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

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

For a function with a status dict, enum, or tagged union result, check each caller. Check that it accounts for all possible results.

```javascript
// Run through mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

async function checkReturnContracts(functionName) {
  // 1. Read the function body to find all paths to `return`.
  const detail = await serena.find_symbol({ name: functionName, depth: 2 });
  const body = detail.body || '';

  // 2. Collect all possible results (status strings, enum variants, error types).
  const returnStatuses = body.match(/return\s+\{[^}]*"status":\s*"(\w+)"/g) || [];
  const statusValues = [...new Set(returnStatuses.map(r => r.match(/"(\w+)"$/)?.[1]).filter(Boolean))];

  // 3. Find all callers
  const callers = await serena.find_referencing_symbols({ name_path: functionName });

  // 4. Check which results each caller accounts for.
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

**Contract rule.** If a function gives N possible status values and a caller checks only M < N, flag a "silent failure path" (HIGH severity). Prefer an allowlist check, such as `status not in (good_values)`, to a blocklist check such as `status == "error"`. Refuse unknown values by default.

---

## Core Principles (Universal)

Each code change MUST be checked against these six principles:

| # | Principle | What to Look For | Best Tool |
|---|-----------|-------------------|-----------|
| 1 | **YAGNI** | Code with no callers, speculative features, dead branches | Serena `find_referencing_symbols` (LSP-precise). If unavailable, use Grep for call sites. |
| 2 | **KISS** | Over-engineered abstractions, trivial classes | Serena `find_symbol` depth → single-method classes |
| 3 | **DRY** | Duplicated logic across files | Grep/Glob for recurring signatures or body fragments across files |
| 4 | **`Fail Fast`** | Late validation, deep nesting before error checks | Serena `find_symbol` body → nesting depth |
| 5 | **SSOT** | Duplicated status or config data | Grep for the same config key/value in 2+ files |
| 6 | **Law of Demeter** | `a.b.c.d` chains | Serena `find_symbol` body → chain regex |

**Tool selection rule.** Use Serena for structural analysis in a file when available. It gets structure data from the LSP. Use Grep and Glob for cross-file checks. If Serena is unavailable, use Grep and Glob for structural analysis too.

### Code Reduction Rules

- No helpers for one-time operations
- Keep three lines that do almost the same work if a shared abstraction adds no value.
- Remove code that has no users (no `_unused` renames, no `# removed` comments)
- No backwards-compatibility shims when you can change the code directly
- No feature flags for unreleased features

### Comment Discipline

A comment tells the reader the constraint that the code applies. Do not cite a conversation, reviewer message, or session artifact. Give all information a reader needs without access to the history.

**The dead-link test.** Each ID or label in a comment must point to a durable record in the repo or its host platform. A PR number is correct because a reader can open it on GitHub. A session ID, work-unit label, or ID from a reviewer result is incorrect. A reader does not have the transcript or conversation.

These before-and-after examples restate comments from an earlier cleanup.

```
- # ── Change #4: extended permanent blocklist ──────────────────────────
+ # ── Permanent blocklist ───────────────────────────────────────────────
```

```
- # F1 fix: detect --force and multi-token "-d -f" patterns too.
+ # The check detects --force and multi-token "-d -f" patterns too.
```

```
- # E1: An untrusted login posts a correct, byte-identical marker. The test checks for exit 1.
- # The stub defaults to WRITE permission. The highest-value regression test in
- # the full PR checks that the login check refuses the forged marker with WRITE.
+ # If an untrusted login posts a correct, byte-identical marker, expect exit 1.
+ # The stub defaults to WRITE permission. The login check must refuse a forged
+ # marker regardless of the permission field.
```

Each rewrite keeps the rule or test condition and its purpose. It removes wording from the reviewer or session, such as a change number or a fix label. It also removes "the highest-value regression case in the full PR".

In coderails-equipped repos, the `comment_citation_gate` PreToolUse hook
applies this rule to Write/Edit/MultiEdit. Follow the rule on all platforms, with or without the hook.

---

## Enforcement Process

### Step 1: Detect Language & Dispatch
Read the file extension. **Invoke the matching language skill:**
- `.go` → `engineering-principles-go`
- `.py` → `engineering-principles-python`
- `.ts`/`.tsx` → `engineering-principles-ts`
- `.sh` (or no extension with a `bash`/`sh` shebang) → `engineering-principles-bash`

### Step 2: Analyze
- **If Serena available:** Get the symbol overview, count uses of symbols, and analyze depth (Phase 2)
- **Cross-file analysis:** Grep/Glob for duplicated signatures (DRY), recurring config keys (SSOT), call sites (YAGNI)
- **If Serena unavailable:** Fall back fully to file-level static analysis through Read/Grep/Glob

### Step 3: Fix or Flag

**Correct directly** (LSP-confirmed safe):
- Naming convention violations
- Missing type hints
- Redundant `else` after `return`
- Verbose patterns with idiomatic replacements
- Imports the code does not use

**Flag to user** (need confirmation):
- Removing functions with no uses
- Replacing a single-method class with its method
- Moving duplicated code into one function
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
- If you are unsure, flag the issue for the user
- Apply the minimum change needed
- Add features, comments, and docstrings only if necessary
- Use LSP data from Serena for in-file analysis if available
- Use Grep/Glob for cross-file checks (DRY/SSOT/YAGNI)
- **Always invoke language-specific skill for idioms**

---

