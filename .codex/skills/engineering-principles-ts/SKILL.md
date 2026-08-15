---
name: engineering-principles-ts
description: TypeScript-specific coding standards and idioms. Invoked by engineering-principles coordinator or directly for TypeScript files.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__mcp-exec__*
paths: "**/*.ts,**/*.tsx"
---

# Engineering Principles TypeScript - Language-Specific Standards

**Version:** 2.0.0
**Purpose:** Enforce TypeScript idioms and patterns on `.ts` and `.tsx` files.

---

## TypeScript Idioms (MANDATORY)

### Type Safety
- **Strict mode always** — `"strict": true` in tsconfig.json
- **No `any` type** — Use `unknown` and narrow, or define proper types
- **Explicit return types** on exported functions
- **Discriminated unions** over type assertions

### Null Handling
- **Optional chaining** (`?.`) instead of nested null checks
- **Nullish coalescing** (`??`) instead of `|| defaultValue`
- **Non-null assertion (!)** only when you've verified safety

### Switch Statements
- **Exhaustive checks** — Never use `default` that swallows cases
- Use `assertNever` pattern for compile-time exhaustiveness

### Patterns
- `const` assertions where applicable
- Type inference where type is obvious from assignment
- Object shorthand (`{ name }` not `{ name: name }`)
- Arrow functions for callbacks
- Template literals over string concatenation

---

## Reduction Patterns (APPLY)

| Pattern | Before | After |
|---------|--------|-------|
| Optional chaining | `user && user.profile && user.profile.name` | `user?.profile?.name` |
| Nullish coalescing | `value \|\| 'default'` | `value ?? 'default'` |
| Object shorthand | `{ name: name, age: age }` | `{ name, age }` |
| Template literal | `'Hello ' + name + '!'` | `` `Hello ${name}!` `` |
| Arrow callback | `items.map(function(x) { return x * 2; })` | `items.map(x => x * 2)` |
| Type inference | `const x: number = 5` | `const x = 5` |

---

## Imperative → Declarative Patterns (MANDATORY)

Scan for these anti-patterns and replace with idiomatic TypeScript.

### Loop Anti-Patterns

| Anti-Pattern | Replacement | Example |
|-------------|-------------|---------|
| `for` loop with `push` | `.map()` / `.filter()` / `.reduce()` | `for (const x of items) { result.push(f(x)); }` → `items.map(x => f(x))` |
| `for` loop with conditional push | `.filter()` then `.map()` | `for (x of items) { if (pred(x)) result.push(f(x)); }` → `items.filter(pred).map(f)` |
| `for` loop with `break` | `.find()` / `.some()` / `.every()` | `for (x of items) { if (pred(x)) { found = x; break; } }` → `items.find(pred)` |
| Nested `for` loops | `.flatMap()` | `for (a of lists) { for (b of a) { ... } }` → `lists.flatMap(a => a.map(...))` |
| Index-based `for (let i)` | `for...of` / `.forEach()` / `.entries()` | `for (let i = 0; i < arr.length; i++)` → `for (const [i, val] of arr.entries())` |
| Loop building object | `Object.fromEntries()` | `const obj = {}; for (...) { obj[k] = v; }` → `Object.fromEntries(pairs.map(...))` |
| Loop with running total | `.reduce()` | `let sum = 0; for (x of items) sum += x;` → `items.reduce((s, x) => s + x, 0)` |
| Loop counting matches | `.filter().length` | `let n = 0; for (x of items) { if (pred(x)) n++; }` → `items.filter(pred).length` |
| Loop with type narrowing | `.filter()` with type predicate | `for (x of items) { if (isString(x)) result.push(x); }` → `items.filter(isString)` |

### Conditional Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| `if/else if` chain (5+) | Object lookup / `Map` / `Record<K, V>` |
| Nested ternaries 3+ deep | Extract to function or `switch` |
| Repeated `typeof` checks | Type guard function (`value is T`) |
| Flag accumulation in loop | `.some()` / `.every()` |
| Nested conditionals 3+ deep | Guard clauses / early returns |
| `switch` with identical patterns per case | Object/Map dispatch |

### Accumulation Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Manual array concat | Spread `[...a, ...b]` |
| Manual object merge | Spread `{ ...a, ...b }` |
| String concat in loop | `.join()` or template literal |
| Manual grouping | `Map` + `.reduce()` or `Object.groupBy()` (ES2024) |
| Manual counting | `.reduce()` to `Map` |
| Manual unique | `[...new Set(items)]` |
| Manual key extraction | `.map(x => x.key)` or destructuring |

### Promise Anti-Patterns

| Anti-Pattern | Replacement |
|-------------|-------------|
| Sequential `await` in loop | `Promise.all()` for independent operations |
| `.then()` chains | `async/await` |
| Manual error collection | `Promise.allSettled()` |
| Callback nesting (callback hell) | `async/await` |
| Manual timeout wrapper | `AbortSignal.timeout()` or `Promise.race()` |

---

## Example: Before/After

```typescript
// BEFORE (violations: any, verbose null checks, no return type)
function getDisplayName(user: any) {
    if (user !== null && user !== undefined) {
        if (user.profile !== null && user.profile !== undefined) {
            if (user.profile.displayName !== null && user.profile.displayName !== undefined) {
                return user.profile.displayName;
            }
        }
    }
    return "Anonymous";
}
```

```typescript
// AFTER (typed, optional chaining, nullish coalescing, return type)
interface User {
    profile?: {
        displayName?: string;
    };
}

function getDisplayName(user: User | null | undefined): string {
    return user?.profile?.displayName ?? "Anonymous";
}
```

---

## Imperative Example: Before/After

```typescript
// BEFORE (imperative: for loop, manual push, flag, concat)
function summarize(groups: string[][]): string {
    const flat: string[] = [];
    let foundSpecial = false;
    for (const group of groups) {
        for (const item of group) {
            flat.push(item);
            if (item.startsWith("!")) {
                foundSpecial = true;
            }
        }
    }
    let output = "";
    for (const item of flat) {
        output = output + item + ", ";
    }
    return foundSpecial
        ? `Found special in ${flat.length} items: ${output}`
        : `No special in ${flat.length} items: ${output}`;
}
```

```typescript
// AFTER (declarative: flatMap, some, join, template)
function summarize(groups: string[][]): string {
    const flat = groups.flatMap(g => g);
    const foundSpecial = flat.some(item => item.startsWith("!"));
    const label = foundSpecial ? "Found special" : "No special";
    return `${label} in ${flat.length} items: ${flat.join(", ")}`;
}
```

---

## Discriminated Union Pattern

```typescript
type Result<T> =
    | { success: true; data: T }
    | { success: false; error: string };

function handleResult<T>(result: Result<T>): T | never {
    if (result.success) {
        return result.data;
    }
    throw new Error(result.error);
}

// Exhaustive switch
type Status = 'pending' | 'active' | 'completed' | 'failed';

function assertNever(x: never): never {
    throw new Error(`Unexpected value: ${x}`);
}

function getStatusLabel(status: Status): string {
    switch (status) {
        case 'pending': return 'Pending';
        case 'active': return 'Active';
        case 'completed': return 'Done';
        case 'failed': return 'Failed';
        default: return assertNever(status);
    }
}
```

---

## Const Assertion Pattern

```typescript
const colors = ['red', 'green', 'blue'] as const;
type Color = typeof colors[number]; // 'red' | 'green' | 'blue'

const config = {
    apiUrl: 'https://api.example.com',
    timeout: 5000,
} as const;
```

---

## Type Narrowing Patterns

```typescript
function isString(value: unknown): value is string {
    return typeof value === 'string';
}

function process(value: unknown): string {
    if (isString(value)) {
        return value.toUpperCase();
    }
    throw new Error('Expected string');
}

// In operator narrowing
interface Dog { bark(): void; }
interface Cat { meow(): void; }

function speak(animal: Dog | Cat): void {
    if ('bark' in animal) {
        animal.bark();
    } else {
        animal.meow();
    }
}
```

---

## Checklist

Before completing TypeScript code changes:

- [ ] No `any` type — use `unknown` or proper types
- [ ] Explicit return types on exported functions
- [ ] Optional chaining (`?.`) for null checks
- [ ] Nullish coalescing (`??`) not `||` for defaults
- [ ] Discriminated unions for variant types
- [ ] Exhaustive switch with `assertNever`
- [ ] `as const` for literal types
- [ ] Object shorthand used
- [ ] Template literals (not string concatenation)
- [ ] Arrow functions for callbacks
- [ ] `.map`/`.filter`/`.reduce` over `for` loops with `push`
- [ ] `.find`/`.some`/`.every` over `for` with `break`
- [ ] `.flatMap` over nested `for` loops
- [ ] `Object.fromEntries` over loop building objects
- [ ] `Promise.all` over sequential `await` in loops
- [ ] Object/Map dispatch over `if/else if` chains (5+)
- [ ] Guard clauses over nested conditionals 3+ deep
- [ ] `[...new Set()]` over manual dedup
