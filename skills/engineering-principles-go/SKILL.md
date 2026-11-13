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
- **Interface parameters and concrete struct results.** Use interface parameters for flexibility and concrete structs as function results for clarity.
- **Package-level organization.** Group code by the work each package does. Do not organize it by classes.

### Error Handling
- **Errors are values.** Add error-handling code or use `return` to give the error to the caller. Do not ignore it with `_ =`.
- **Add context to errors.** Use `fmt.Errorf("context: %w", err)` to keep the error chain.
- **Exit on error.** Check errors immediately and use `return` when an error occurs.

### Testing
- **Table-driven tests** — Use `[]struct{ name string; ... }` pattern for test inputs
- **Subtests** — Use `t.Run(tt.name, func(t *testing.T) { ... })`

### Naming & Style
- **Short names in small scopes.** Use names such as `i`, `n`, or `err` locally.
- **Exported = PascalCase, unexported = camelCase**
- **Acronyms stay uppercase** — `HTTPClient`, not `HttpClient`

---

## Reduction Patterns (APPLY)

| Pattern | Before | After |
|---------|--------|-------|
| Exit on error | `if err != nil { ... } else { ... }` | `if err != nil { return err }` |
| Error wrapping | `return err` | `return fmt.Errorf("context: %w", err)` |
| No empty structs | `Type{}` without purpose | Remove or use `var t Type` |
| Use the result of a check | `_ = validateInput(data)` | `if err := validateInput(data); err != nil { ... }` |
| Named function results | `func() (int, error)` | `func() (count int, err error)` for docs |
| No TODO comments | `// TODO: fix later` | Correct the issue or remove the comment |

---

## Imperative → Idiomatic Patterns (MANDATORY)

Go uses loops for mapping, filtering, and reducing. Apply Go idioms that make
the code shorter and clearer.

### Loop Anti-Patterns

| Anti-Pattern | Replacement | Example |
|-------------|-------------|---------|
| Nested loops 3+ deep | Move inner loops to functions | `for a: for b: for c:` → `for a: processB(a)` |
| Manual string building in loop | `strings.Builder` or `strings.Join` | `s += item + ","` → `b.WriteString(item)` |
| Append without pre-allocation | `make([]T, 0, len(src))` when you know the capacity | `var result []T` → `result := make([]T, 0, len(src))` |
| Manual map without an initial capacity | `make(map[K]V, len(src))` when you know the capacity | `m := map[K]V{}` → `m := make(map[K]V, len(src))` |
| Manual contains check on slice | `map[T]bool` or `map[T]struct{}` lookup | `for _, v := range items { if v == target }` → `if lookup[target]` |
| Range with index only | Use `_` or range value directly | `for i := range items { items[i].X }` → `for _, item := range items { item.X }` |
| Manual iteration from last to first | `slices.Reverse` (1.21+) or index from last to first | `for i := len(s)-1; i >= 0; i--` → `slices.Reverse(s)` |
| Manual min/max in loop | `min()`/`max()` builtins (1.21+) | `if x < current { current = x }` → `current = min(current, x)` |
| Manual slice contains | `slices.Contains` (1.21+) | `for _, v := range s { if v == target }` → `slices.Contains(s, target)` |
| Manual sort + unique | `slices.Sort` + `slices.Compact` (1.21+) | Manual dedup loop → `slices.Sort(s); slices.Compact(s)` |

### Conditional Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Long `switch`/`if-else` chain (5+) | `map[string]func()` dispatch table |
| Recurring type assertions | `switch v := x.(type)` type switch |
| Nested conditionals 3+ deep | Check the condition and exit the function immediately if applicable |
| Loop that updates a Boolean flag | Use `return` on the first match |
| `if init; cond` not used | Use a short statement: `if err := f(); err != nil` |
| Boolean function with a conditional result | Use the expression as the result: `return x > 0` |

### Concurrency Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Manual goroutine + WaitGroup | `errgroup.Group` (handles errors + waiting) |
| Manual channel collect | `errgroup` or pipeline pattern |
| Unbounded goroutine spawn | Worker pool with semaphore channel |
| Manual mutex map | `sync.Map` (for append-heavy, read-many patterns) |
| Select without `default` or timeout | Add `context.Context` deadline or `default` |
| Go `chan` for one value | Use `return` or a callback |

### Stdlib Shortcuts

| Manual Code | Stdlib or Idiom |
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
// BEFORE (violations: error handling, nested if/else, unneeded name)
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
// AFTER (exits on error, uses all local names)
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
// AFTER (strings.Builder, strings.Contains, exit when the result is known)
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

// Concrete struct for the function result
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

- [ ] All errors handled or sent to the caller (no `_ =`)
- [ ] Errors wrapped with `fmt.Errorf("context: %w", err)`
- [ ] Use `return` to exit without nested if/else
- [ ] Functions accept interfaces where applicable
- [ ] Functions give concrete structs as results
- [ ] Tests are table-driven with subtests
- [ ] No TODO comments
- [ ] No empty structs without purpose
- [ ] No nested loops 3+ deep — extract to functions
- [ ] Prefer `strings.Builder`/`strings.Join` to `+=` in loops
- [ ] Pre-allocate slices/maps when you know the capacity
- [ ] Prefer `map[T]bool` or `slices.Contains` to manual contains loops
- [ ] Prefer `errgroup.Group` to manual goroutine + WaitGroup
- [ ] Prefer a type switch to recurring type assertions
- [ ] Prefer map dispatch to long switch/if-else chains (5+)
- [ ] Check conditions and exit the function to prevent nesting 3 or more levels deep
- [ ] Prefer `min()`/`max()` builtins to manual tracking (1.21+)
