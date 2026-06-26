---
name: engineering-principles
description: Enforce engineering principles (YAGNI, KISS, DRY, Fail Fast, SSOT, Law of Demeter) and language-specific coding standards (Python/Go/TypeScript) on code being written or modified. Uses Serena LSP for call site analysis and reference counting. Use PROACTIVELY when writing, modifying, or reviewing code. Triggers on code changes, "enforce standards", "check principles", "apply standards", "code quality", or explicit /engineering-principles command.
allowed-tools: Read, Write, Edit, Glob, Grep, Skill, mcp__mcp-exec__*
---

# Engineering Principles & Language Standards

**Version:** 4.0.0
**Purpose:** Proactively enforce engineering principles and language-specific idioms. Uses LSP (Serena) for structural verification and reference counting. **Dispatches to language-specific skills for idiom enforcement.**

## When to Activate

**Proactively** (without user asking):
- After writing or modifying code in any file
- When reviewing code changes before commit
- When implementing features or fixing bugs

**Explicitly** (user invokes `/engineering-principles`):
- Point at a file or directory to audit and fix

---

## PHASE 0: Language Detection & Dispatch (MANDATORY)

**Before any analysis, detect the language and invoke the appropriate sub-skill:**

| File Extension | Invoke Skill |
|----------------|--------------|
| `.go` | Execute `engineering-principles-go` skill |
| `.py` | Execute `engineering-principles-python` skill |
| `.ts`, `.tsx` | Execute `engineering-principles-ts` skill |

**The language-specific skill provides idioms, patterns, and examples. This coordinator provides universal principles and MCP analysis.**

---

## Phase 1: MCP Environment Setup

Before analysis, activate Serena for the current project.

```javascript
// Execute via mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

// Test connectivity
const serenaConfig = await serena.get_current_config();
const hasSerena = !!serenaConfig;

console.log("Serena (LSP):", hasSerena ? "OK" : "UNAVAILABLE - falling back to static analysis");

// Activate Serena project if available
if (hasSerena) {
  await serena.activate_project({ project: process.cwd() });
}
```

**Graceful degradation:** If Serena is unavailable, fall back to file-level static analysis using Read/Grep/Glob. Serena enhances but is not required.

---

## Phase 2: Structural Analysis via Serena (LSP)

Use Serena to get precise structural data for principle enforcement.

### 2.1 Symbol Overview

```javascript
// Execute via mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

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

  // Detect a.b.c.d chains (3+ dots)
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

For functions returning status dicts/enums/tagged unions, verify all callers handle all possible return values:

```javascript
// Execute via mcp__mcp-exec__execute_code_with_wrappers with wrappers: ["serena"]

async function checkReturnContracts(functionName) {
  // 1. Read the function body to find all return paths
  const detail = await serena.find_symbol({ name: functionName, depth: 2 });
  const body = detail.body || '';

  // 2. Extract distinct return values (status strings, enum variants, error types)
  const returnStatuses = body.match(/return\s+\{[^}]*"status":\s*"(\w+)"/g) || [];
  const statusValues = [...new Set(returnStatuses.map(r => r.match(/"(\w+)"$/)?.[1]).filter(Boolean))];

  // 3. Find all callers
  const callers = await serena.find_referencing_symbols({ name_path: functionName });

  // 4. For each caller, check which return values they handle
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

**Contract rule:** If a function returns N distinct status values but a caller only checks M < N, flag as "silent failure path" (HIGH severity). Prefer allowlist checks (`status not in (good_values)`) over blocklist checks (`status == "error"`) — fail-closed by default.

---

## Core Principles (Universal)

Every code change MUST be checked against these six principles:

| # | Principle | What to Look For | Best Tool |
|---|-----------|-------------------|-----------|
| 1 | **YAGNI** | Unused code, speculative features, dead branches | Serena `find_referencing_symbols` (LSP-precise); else Grep for call sites |
| 2 | **KISS** | Over-engineered abstractions, trivial classes | Serena `find_symbol` depth → single-method classes |
| 3 | **DRY** | Duplicated logic across files | Grep/Glob for repeated signatures or body fragments across files |
| 4 | **Fail Fast** | Late validation, deep nesting before error checks | Serena `find_symbol` body → nesting depth |
| 5 | **SSOT** | Duplicated state/config | Grep for the same config key/value in 2+ files |
| 6 | **Law of Demeter** | `a.b.c.d` chains | Serena `find_symbol` body → chain regex |

**Tool selection rule:** Serena for in-file structural analysis (LSP-backed, authoritative) when available; plain Grep/Glob for cross-file checks and as the fallback when Serena is absent.

### Code Reduction Rules

- No helpers for one-time operations
- No premature abstractions (3 similar lines > a premature abstraction)
- Delete unused code completely (no `_unused` renames, no `# removed` comments)
- No backwards-compatibility shims when you can just change the code
- No feature flags for unreleased features

---

## Enforcement Process

### Step 1: Detect Language & Dispatch
Read the file extension. **Invoke the matching language skill:**
- `.go` → `engineering-principles-go`
- `.py` → `engineering-principles-python`
- `.ts`/`.tsx` → `engineering-principles-ts`

### Step 2: Analyze
- **If Serena available:** Run symbol overview, reference counting, depth analysis (Phase 2)
- **Cross-file analysis:** Grep/Glob for duplicated signatures (DRY), repeated config keys (SSOT), call sites (YAGNI)
- **If Serena unavailable:** Fall back entirely to file-level static analysis via Read/Grep/Glob

### Step 3: Fix or Flag

**Fix directly** (LSP-confirmed safe):
- Naming convention violations
- Missing type hints
- Redundant `else` after `return`
- Verbose patterns with idiomatic replacements
- Unused imports

**Flag to user** (need confirmation):
- Removing functions with 0 references
- Collapsing single-method class
- Extracting duplicated code
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

- Never change external behavior or public APIs
- Never remove or simplify error handling
- Always preserve test coverage
- When in doubt, flag instead of fix
- Apply the minimum change needed
- Don't add features, comments, or docstrings beyond what's needed
- Trust LSP data (Serena) over heuristics for in-file analysis
- Use scout skills (`scout-search`, `scout-dead-code`, `scout-explain-symbol`) for cross-file semantic analysis
- **Always invoke language-specific skill for idioms**

---

