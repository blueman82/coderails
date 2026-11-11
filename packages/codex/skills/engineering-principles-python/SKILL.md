---
name: engineering-principles-python
description: Python-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for Python files.
---

# Engineering Principles Python - Language-Specific Standards

**Version:** 2.0.0
**Purpose:** Enforce Python idioms and patterns on `.py` files.

---

## Python Idioms (MANDATORY)

### Naming & Structure (PEP 8)
- `snake_case` for function names and names for values
- `PascalCase` for classes
- `UPPER_CASE` for constants
- Full type hints on all function signatures and class attributes. Pyright strict mode must report no errors

### Imports
- Explicit imports (no star imports)
- No lazy imports
- No `TYPE_CHECKING` blocks — fix architecture if circular imports exist
- Use `from __future__ import annotations` to refer to types before their definition

### Idioms
- **Prefer EAFP to LBYL** — use `try/except` without an `if` check for a missing or invalid value
- **Context managers** for all resources (`with open(...)`, `async with ...`)
- **Prefer f-strings** to `.format()` or `%`
- **Prefer list/dict comprehensions** to explicit loops if the comprehension is readable
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

Find these anti-patterns and replace them with idiomatic Python.

### Loop Anti-Patterns

| Anti-Pattern | Replacement | Example |
|-------------|-------------|---------|
| Nested loops 3+ deep | `itertools.product`, comprehension, or extract function | `for a in x: for b in y: for c in z:` → `for a, b, c in product(x, y, z):` |
| Manual counter | `enumerate()` | `i = 0; for x in items: i += 1` → `for i, x in enumerate(items):` |
| Parallel iteration by index | `zip()` | `for i in range(len(a)): a[i], b[i]` → `for x, y in zip(a, b):` |
| Loop with `break` on a condition | `any()` / `all()` | `for x in items: if pred(x): found = True; break` → `found = any(pred(x) for x in items)` |
| Loop building dict | dict comprehension | `d = {}; for k, v in pairs: d[k] = f(v)` → `{k: f(v) for k, v in pairs}` |
| Loop building set | set comprehension | `s = set(); for x in items: s.add(f(x))` → `{f(x) for x in items}` |
| Loop that updates a total | `sum()` | `total = 0; for x in items: total += x` → `sum(items)` |
| Loop filtering then transforming | chained comprehension | `for x in items: if pred(x): result.append(f(x))` → `[f(x) for x in items if pred(x)]` |
| Nested loop with flatten | `itertools.chain.from_iterable()` | `for sub in lists: for x in sub: result.append(x)` → `list(chain.from_iterable(lists))` |
| Loop that uses `sorted()` | Sort one time before the loop | `for x in items: sorted_sub = sorted(...)` → sort before loop |

### Conditional Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Long `if/elif/else` chains (5+) | dict dispatch / lookup table |
| Multiple `isinstance` checks of the same value | `match/case` (3.10+) or visitor pattern |
| Conditionals that set flags | `return` statements or ternary |
| Nested conditionals 3+ deep | Check preconditions first and exit if they do not hold |
| Loop that updates a Boolean flag | `any()` / `all()` |

### Accumulation Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| String concatenation in loop | `"".join(parts)` |
| Manual `list.extend` equivalent | `list.extend()` or `[*a, *b]` |
| Manual dict merge | `{**a, **b}` or `a \| b` (3.9+) |
| Manual max/min tracking | `max()` / `min()` with `key=` |
| Manual grouping by key | `itertools.groupby()` or `defaultdict(list)` |
| Manual counting | `collections.Counter` |
| Manual deduplication | `set()` or `dict.fromkeys()` (order-preserving) |
| Manual retry loop | `tenacity` or backoff decorator |
| Manual path string operations | `pathlib.Path` |
| Manual datetime arithmetic | `timedelta` |

---

## Example: Before/After

```python
# BEFORE (violations: KISS, naming, type hints, redundant else, legacy generics)
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
# AFTER (declarative: chain, `any`, join, f-string)
from itertools import chain

def summarize(groups: list[list[str]]) -> str:
    flat = list(chain.from_iterable(groups))
    found_special = any(item.startswith("!") for item in flat)
    label = "Found special" if found_special else "No special"
    return f"{label} in {len(flat)} items: {', '.join(flat)}"
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

# EAFP (try the operation and handle errors) - PREFER
try:
    value = dictionary[key]
except KeyError:
    value = default

# Prefer this for dicts:
value = dictionary.get(key, default)
```

---

## Output Sanitization Patterns

When inserting untrusted text (AI output, user input, external API responses) into structured output formats, sanitize before insertion:

| Output Format | Dangerous Tokens | Sanitization |
|---------------|-----------------|--------------|
| **Slack’s `mrkdwn` format** | `<!channel>`, `<!here>`, `<!everyone>`, `<@U...>` | `re.sub(r'<[!@][^>]+>', '', text)` |
| **HTML** | `<script>`, `onclick=`, untrusted HTML entities | `html.escape(text)` |
| **SQL** | `'; DROP TABLE`, `OR 1=1` | Use parameterized queries only. Do not use f-strings. |
| **Shell** | `$(cmd)`, `` `cmd` ``, `; rm -rf` | `shlex.quote(text)` |
| **JSON in templates** | Unescaped quotes, newlines | `json.dumps(text)` |

**Rule:** Do not trust text from AI models, user input, or external APIs. Sanitize it at the point of insertion, not at the point of collection.

**Allowlist > blocklist:** Use an allowlist check (`if status not in ("success", "disabled")`) for status/result dicts that callers read.
A blocklist check such as `if status == "error"` can miss an unhandled result value. The allowlist stops on those values.

---

## Checklist

Before completing Python code changes:

- [ ] All functions have full type hints for arguments and results
- [ ] No `List`, `Dict`, `Optional` from typing — use builtins
- [ ] No star imports
- [ ] No mutable default arguments
- [ ] f-strings used (not `.format()` or `%`)
- [ ] Context managers for resources
- [ ] EAFP pattern (`try/except` without `if` checks)
- [ ] No redundant `else` after `return`
- [ ] Comprehensions where readable
- [ ] No nested loops 3+ deep — flatten or extract
- [ ] `enumerate`/`zip` replace manual indexing
- [ ] `any`/`all` replace loops that use `break` for Boolean checks
- [ ] `sum`/`max`/`min` replace loops that calculate totals or limits
- [ ] `Counter`/`defaultdict` replace manual counting/grouping
- [ ] `"".join()` replaces string concatenation in loops
- [ ] Dict dispatch replaces long `if/elif` chains (5+)
- [ ] Check preconditions first and exit before nested conditionals 3+ deep
- [ ] **Untrusted text sanitized before output** (AI responses, user input, API data)
