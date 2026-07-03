---
name: engineering-principles-go
description: Go-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for Go files.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__mcp-exec__*
paths: "**/*.go"
---

# Engineering Principles Go - Language-Specific Standards

**Version:** 2.0.0
**Purpose:** Enforce Go idioms and patterns on `.go` files.

---

## Go Idioms (MANDATORY)

### Interface & Struct Patterns
- **Accept interfaces, return structs** — Functions should accept interface parameters for flexibility, return concrete struct types for clarity
- **Package-level organization** — No class-level thinking; organize by package responsibility

### Error Handling
- **Errors are values** — Handle them or return them, never ignore with `_ =`
- **Wrap errors with context** — Use `fmt.Errorf("context: %w", err)` for stack traces
- **Early returns** — Check errors immediately, return early

### Testing
- **Table-driven tests** — Use `[]struct{ name string; ... }` pattern for test cases
- **Subtests** — Use `t.Run(tt.name, func(t *testing.T) { ... })`

### Naming & Style
- **Short variable names in small scopes** — `i`, `n`, `err` are fine locally
- **Exported = PascalCase, unexported = camelCase**
- **Acronyms stay uppercase** — `HTTPClient`, not `HttpClient`

---

## Reduction Patterns (APPLY)

| Pattern | Before | After |
|---------|--------|-------|
| Early return | `if err != nil { ... } else { ... }` | `if err != nil { return err }` |
| Error wrapping | `return err` | `return fmt.Errorf("context: %w", err)` |
| No empty structs | `Type{}` without purpose | Remove or use `var t Type` |
| No unused vars | `_ = validateInput(data)` | `if err := validateInput(data); err != nil { ... }` |
| Named returns | `func() (int, error)` | `func() (count int, err error)` for docs |
| No TODO comments | `// TODO: fix later` | Fix now or remove |

---

## Imperative → Idiomatic Patterns (MANDATORY)

Go is intentionally imperative — no map/filter/reduce. Instead, enforce Go-specific idioms that reduce verbosity and improve clarity.

### Loop Anti-Patterns

| Anti-Pattern | Replacement | Example |
|-------------|-------------|---------|
| Nested loops 3+ deep | Extract inner loops to functions | `for a: for b: for c:` → `for a: processB(a)` |
| Manual string building in loop | `strings.Builder` or `strings.Join` | `s += item + ","` → `b.WriteString(item)` |
| Append without pre-allocation | `make([]T, 0, len(src))` when size known | `var result []T` → `result := make([]T, 0, len(src))` |
| Manual map building without size | `make(map[K]V, len(src))` when size known | `m := map[K]V{}` → `m := make(map[K]V, len(src))` |
| Manual contains check on slice | `map[T]bool` or `map[T]struct{}` lookup | `for _, v := range items { if v == target }` → `if lookup[target]` |
| Range over index only | Use `_` or range value directly | `for i := range items { items[i].X }` → `for _, item := range items { item.X }` |
| Manual reverse iteration | `slices.Reverse` (1.21+) or reverse index | `for i := len(s)-1; i >= 0; i--` → `slices.Reverse(s)` |
| Manual min/max in loop | `min()`/`max()` builtins (1.21+) | `if x < current { current = x }` → `current = min(current, x)` |
| Manual slice contains | `slices.Contains` (1.21+) | `for _, v := range s { if v == target }` → `slices.Contains(s, target)` |
| Manual sort + unique | `slices.Sort` + `slices.Compact` (1.21+) | Manual dedup loop → `slices.Sort(s); slices.Compact(s)` |

### Conditional Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Long `switch`/`if-else` chain (5+) | `map[string]func()` dispatch table |
| Repeated type assertions | `switch v := x.(type)` type switch |
| Nested conditionals 3+ deep | Guard clauses / early return |
| Flag accumulation in loop | Early return on first match |
| `if init; cond` not used | Use short statement form: `if err := f(); err != nil` |
| Boolean function with if/else return | Return expression directly: `return x > 0` |

### Concurrency Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Manual goroutine + WaitGroup | `errgroup.Group` (handles errors + waiting) |
| Manual channel collect | `errgroup` or pipeline pattern |
| Unbounded goroutine spawn | Worker pool with semaphore channel |
| Manual mutex map | `sync.Map` (for append-heavy, read-many patterns) |
| Select without `default` or timeout | Add `context.Context` deadline or `default` |
| Channel for single value | Direct return or callback |

### Stdlib Shortcuts

| Manual Code | Use Instead |
|-------------|-------------|
| Manual HTTP handler chain | Middleware pattern / `http.Handler` wrapping |
| Manual JSON field naming | Struct tags `json:"field_name"` |
| Manual file tree walk | `filepath.WalkDir` |
| Manual retry with sleep | `for` with exponential backoff + jitter |
| Manual byte buffer | `bytes.Buffer` |
| Manual path join with `/` | `filepath.Join` or `path.Join` |
| Manual env with default | Helper: `envOr(key, fallback)` |
| `fmt.Sprintf` for simple concat | `strings.Join` or `+` for 2-3 strings |

---

## Example: Before/After

```go
// BEFORE (violations: error handling, nested if/else, unused var)
func ProcessData(data []byte) (Result, error) {
    _ = validateInput(data)
    result, err := parse(data)
    if err != nil {
        return Result{}, err
    } else {
        if result.Valid {
            return result, nil
        } else {
            return Result{}, fmt.Errorf("invalid result")
        }
    }
}
```

```go
// AFTER (early returns, errors handled, no unused vars)
func ProcessData(data []byte) (Result, error) {
    if err := validateInput(data); err != nil {
        return Result{}, fmt.Errorf("validation failed: %w", err)
    }

    result, err := parse(data)
    if err != nil {
        return Result{}, fmt.Errorf("parse failed: %w", err)
    }

    if !result.Valid {
        return Result{}, fmt.Errorf("invalid result")
    }

    return result, nil
}
```

---

## Imperative Example: Before/After

```go
// BEFORE (manual string build, manual contains, no pre-alloc)
func summarize(groups [][]string) string {
    output := ""
    foundSpecial := false
    for _, group := range groups {
        for _, item := range group {
            output = output + item + ", "
            for _, c := range item {
                if c == '!' {
                    foundSpecial = true
                    break
                }
            }
        }
    }
    if foundSpecial {
        return fmt.Sprintf("Found special: %s", output)
    }
    return fmt.Sprintf("No special: %s", output)
}
```

```go
// AFTER (strings.Builder, strings.Contains, early return)
func summarize(groups [][]string) string {
    var b strings.Builder
    foundSpecial := false
    for _, group := range groups {
        for _, item := range group {
            if b.Len() > 0 {
                b.WriteString(", ")
            }
            b.WriteString(item)
            if !foundSpecial && strings.Contains(item, "!") {
                foundSpecial = true
            }
        }
    }
    label := "No special"
    if foundSpecial {
        label = "Found special"
    }
    return fmt.Sprintf("%s: %s", label, b.String())
}
```

---

## Table-Driven Test Template

```go
func TestProcessData(t *testing.T) {
    tests := []struct {
        name    string
        input   []byte
        want    Result
        wantErr bool
    }{
        {"valid input", []byte("data"), Result{Valid: true}, false},
        {"empty input", []byte{}, Result{}, true},
        {"nil input", nil, Result{}, true},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got, err := ProcessData(tt.input)
            if (err != nil) != tt.wantErr {
                t.Errorf("ProcessData() error = %v, wantErr %v", err, tt.wantErr)
                return
            }
            if !reflect.DeepEqual(got, tt.want) {
                t.Errorf("ProcessData() = %v, want %v", got, tt.want)
            }
        })
    }
}
```

---

## Interface Pattern Template

```go
// Accept interface
type DataProcessor interface {
    Process(ctx context.Context, data []byte) (Result, error)
}

// Return struct
type processor struct {
    timeout time.Duration
    logger  Logger
}

func NewProcessor(timeout time.Duration, logger Logger) *processor {
    return &processor{timeout: timeout, logger: logger}
}

func (p *processor) Process(ctx context.Context, data []byte) (Result, error) {
    // implementation
}
```

---

## Checklist

Before completing Go code changes:

- [ ] All errors handled or returned (no `_ =`)
- [ ] Errors wrapped with `fmt.Errorf("context: %w", err)`
- [ ] Early returns used (no nested if/else)
- [ ] Functions accept interfaces where appropriate
- [ ] Functions return concrete structs
- [ ] Tests are table-driven with subtests
- [ ] No TODO comments
- [ ] No empty structs without purpose
- [ ] No nested loops 3+ deep — extract to functions
- [ ] `strings.Builder`/`strings.Join` over `+=` in loops
- [ ] Pre-allocate slices/maps when size is known
- [ ] `map[T]bool` or `slices.Contains` over manual contains loops
- [ ] `errgroup.Group` over manual goroutine + WaitGroup
- [ ] Type switch over repeated type assertions
- [ ] Map dispatch over long switch/if-else chains (5+)
- [ ] Guard clauses over nested conditionals 3+ deep
- [ ] `min()`/`max()` builtins over manual tracking (1.21+)
