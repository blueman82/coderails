---
name: engineering-principles-python
description: Python-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for Python files.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__mcp-exec__*
paths: "**/*.py"
---

# Engineering Principles Python - Language-Specific Standards

**Version:** 2.0.0
**Purpose:** Enforce Python idioms and patterns on `.py` files.

---

## Python Idioms (MANDATORY)

### Naming & Structure (PEP 8)
- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_CASE` for constants
- Full type hints on ALL function signatures and class attributes (must pass Pyright strict)

### Imports
- Explicit imports (no star imports)
- Prefer top-level imports. Use a local import when an optional dependency
  or a measured import cycle requires it, and explain the reason.
- Use `TYPE_CHECKING` for type-only imports when it avoids a runtime cycle.
- Use `from __future__ import annotations` for forward references

### Idioms
- **EAFP for race-prone operations** — catch the operation's documented
  exception. Keep explicit checks for input validation and policy rules.
- **Context managers** for all resources (`with open(...)`, `async with ...`)
- **f-strings** over `.format()` or `%`
- **List/dict comprehensions** over explicit loops where readable
- **No mutable default arguments** — use `None` and check

### Documentation
- PEP 257 docstrings for public APIs only
- No docstrings for private methods unless complex

---

## Reduction Patterns (APPLY)

| Pattern | Before | After |
|---------|--------|-------|
| Ternary | `if x: y = a else: y = b` | `y = a if x else b` |
| Walrus | `m = re.match(...); if m:` | `if (m := re.match(...)):` |
| No redundant else | `if x: return a else: return b` | `if x: return a; return b` |
| Builtin generics | `List[int]`, `Dict[str, int]` | `list[int]`, `dict[str, int]` |
| Union syntax | `Optional[str]`, `Union[int, str]` | `str \| None`, `int \| str` |
| Comprehension | `for x in items: result.append(f(x))` | `[f(x) for x in items]` |
| Single-method class | `class X: def do(self): ...` | `def do(): ...` |

---

## Imperative → Declarative Patterns (MANDATORY)

Find these patterns and replace them with the matching Python idiom.

### Loop Anti-Patterns

| Anti-Pattern | Replacement | Example |
|-------------|-------------|---------|
| Independent nested loops 3+ deep | `itertools.product` or extract function | Use `product(x, y, z)` only when each iterable is independent of the outer loop. |
| Manual counter | `enumerate()` | If the original loop increments from 0 before use, use `for i, x in enumerate(items, start=1):`. |
| Parallel iteration by index | `zip()` | On Python 3.10 or later, use `zip(a, b, strict=True)` when unequal lengths must fail. On Python 3.9, check lengths first. Ordinary `zip` truncates. |
| Loop with early break on condition | `any()` / `all()` | `for x in items: if pred(x): found = True; break` → `found = any(pred(x) for x in items)` |
| Loop building dict | dict comprehension | `d = {}; for k, v in pairs: d[k] = f(v)` → `{k: f(v) for k, v in pairs}` |
| Loop building set | set comprehension | `s = set(); for x in items: s.add(f(x))` → `{f(x) for x in items}` |
| Loop with running total | `sum()` | `total = 0; for x in items: total += x` → `sum(items)` |
| Loop filtering then transforming | chained comprehension | `for x in items: if pred(x): result.append(f(x))` → `[f(x) for x in items if pred(x)]` |
| Nested loop with flatten | `itertools.chain.from_iterable()` | `for sub in lists: for x in sub: result.append(x)` → `list(chain.from_iterable(lists))` |
| Loop with `sorted()` inside | sort once outside | `for x in items: sorted_sub = sorted(...)` → sort before loop |

### Conditional Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Long `if/elif/else` chains (5+) | dict dispatch / lookup table |
| Repeated `isinstance` checks | `match/case` (3.10+) or visitor pattern |
| Flag variables set in conditionals | direct returns or ternary |
| Nested conditionals 3+ deep | guard clauses / early returns |
| Boolean flag accumulation in loop | `any()` / `all()` |

### Accumulation Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| String concatenation in loop | `"".join(parts)` |
| Manual `list.extend` equivalent | `list.extend()` or `[*a, *b]` |
| Manual dict merge | `{**a, **b}` or `a \| b` (3.9+) |
| Manual max/min tracking | `max()` / `min()` with `key=` |
| Manual grouping by key | `defaultdict(list)`; use `itertools.groupby()` only when matching keys are consecutive |
| Manual counting | `collections.Counter` |
| Manual deduplication | `set()` or `dict.fromkeys()` (order-preserving) |
| Repeated retry logic | A bounded shared helper when several call sites need the same policy; avoid a new dependency for one loop |
| Manual path string operations | `pathlib.Path` |
| Manual datetime arithmetic | `timedelta` |

---

## Example: Before/After

```python
# BEFORE (violations: KISS, naming, type hints, redundant else, old generics)
from typing import List, Dict, Optional

class DataProcessor:
    def process(self, items):
        result = []
        for item in items:
            if item is not None:
                processed = item.strip().lower()
                result.append(processed)
        return result

    def get_first(self, items):
        if len(items) > 0:
            return items[0]
        else:
            return None
```

```python
# AFTER (all violations fixed)
class DataProcessor:
    def process(self, items: list[str | None]) -> list[str]:
        return [item.strip().lower() for item in items if item is not None]

    def get_first(self, items: list[str]) -> str | None:
        if len(items) > 0:
            return items[0]
        return None
```

---

## Imperative Example: Before/After

```python
# BEFORE (imperative: manual counter, flag, nested loop, string concat)
def summarize(groups: list[list[str]]) -> str:
    output = ""
    count = 0
    found_special = False
    for group in groups:
        for item in group:
            count += 1
            if item.startswith("!"):
                found_special = True
            output = output + item + ", "
    if found_special:
        return f"Found special in {count} items: {output}"
    else:
        return f"No special in {count} items: {output}"
```

```python
# AFTER (declarative: chain, any, join, f-string)
from itertools import chain

def summarize(groups: list[list[str]]) -> str:
    flat = list(chain.from_iterable(groups))
    found_special = any(item.startswith("!") for item in flat)
    label = "Found special" if found_special else "No special"
    output = ", ".join(flat) + (", " if flat else "")
    return f"{label} in {len(flat)} items: {output}"
```

---

## Type Hints Template

```python
from collections.abc import Callable, Iterable, Mapping, Sequence

def process_data(
    items: list[str],
    callback: Callable[[str], bool],
    config: dict[str, int] | None = None,
) -> tuple[list[str], int]:
    """Process items with callback and optional config."""
    config = config or {}
    results = [item for item in items if callback(item)]
    return results, len(results)
```

---

## Context Manager Pattern

```python
# File handling
with open("file.txt", encoding="utf-8") as f:
    content = f.read()

# Multiple resources
with (
    open("input.txt", encoding="utf-8") as infile,
    open("output.txt", "w", encoding="utf-8") as outfile,
):
    outfile.write(infile.read())

# Async resources
async with aiohttp.ClientSession() as session:
    async with session.get(url) as response:
        data = await response.json()
```

---

## EAFP Pattern

```python
# LBYL (Look Before You Leap) - AVOID
if key in dictionary:
    value = dictionary[key]
else:
    value = default

# EAFP (Easier to Ask Forgiveness) - PREFER
try:
    value = dictionary[key]
except KeyError:
    value = default

# Or even better for dicts:
value = dictionary.get(key, default)
```

---

## Output Sanitization Patterns

When inserting untrusted text (AI output, user input, external API responses) into structured output formats, sanitize before insertion:

| Output Format | Dangerous Tokens | Sanitization |
|---------------|-----------------|--------------|
| **Slack mrkdwn** | `<!channel>`, `<!here>`, `<!everyone>`, `<@U...>` | `re.sub(r'<[!@][^>]+>', '', text)` |
| **HTML** | `<script>`, `onclick=`, entity injection | `html.escape(text)` |
| **SQL** | `'; DROP TABLE`, `OR 1=1` | Parameterized queries only, never f-strings |
| **Shell** | `$(cmd)`, `` `cmd` ``, `; rm -rf` | Pass arguments as an argv list. Use `shlex.quote` only when a shell command string is unavoidable. |
| **JSON in templates** | Unescaped quotes, newlines | `json.dumps(text)` |

**Rule:** Any text from AI models, user input, or external APIs MUST be treated as untrusted. Sanitize at the point of insertion, not at the point of collection.

**Allowlist > blocklist:** Callers must handle every unexpected status. Check
`if status not in ("success", "disabled")` when you build a status or result
dict. A check for only `if status == "error"` can miss a new failure value.

---

## Checklist

Before completing Python code changes:

- [ ] All functions have full type hints (args and return)
- [ ] No `List`, `Dict`, `Optional` from typing — use builtins
- [ ] No star imports
- [ ] No mutable default arguments
- [ ] f-strings used (not `.format()` or `%`)
- [ ] Context managers for resources
- [ ] Catch documented operation errors; keep explicit input and policy checks
- [ ] No redundant else after return
- [ ] Comprehensions where readable
- [ ] No nested loops 3+ deep — flatten or extract
- [ ] `enumerate`/`zip` over manual indexing where behavior matches; check unequal-length handling
- [ ] `any`/`all` over loop-with-break boolean checks
- [ ] `sum`/`max`/`min` over manual accumulation
- [ ] `Counter`/`defaultdict` over manual counting/grouping
- [ ] `"".join()` over string concatenation in loops
- [ ] Dict dispatch over long `if/elif` chains (5+)
- [ ] Guard clauses over nested conditionals 3+ deep
- [ ] **Untrusted text sanitized before output** (AI responses, user input, API data)
