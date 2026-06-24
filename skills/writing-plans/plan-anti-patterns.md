# Plan Anti-Patterns

Read this when writing or reviewing a plan. These are the ways a plan can look complete while leaving a worker stranded.

## Placeholder steps

A step that defers work to the implementer is not a step — it is a gap wearing a checkbox.

**Bad:** "Add appropriate error handling", "TODO: implement retry logic", "fill in edge cases later", "implement as needed"
**Good:** Show the actual error-handling code or the exact retry signature. If you don't know it yet, the spec isn't resolved — stop and resolve the spec before writing the plan.

## "Similar to Task N" instead of content

A worker may implement tasks out of order, in a separate session, or without reading earlier tasks. "Same pattern as Task 3" fails them.

**Bad:** "Follow the same approach as Task 2 for the repository layer"
**Good:** Repeat the interface, the file path, and the step sequence. Copy-paste is correct here. Plans are not DRY in the prose sense — they are DRY in the "don't make the implementer hunt" sense.

## Steps that say what without showing how

A code step that describes what to write without showing the code is an outline, not a plan. An implementer reading "implement the parser" has learned nothing they didn't already know.

**Bad:** "Step 3: Write the parse function that splits on commas and trims whitespace"
**Good:**
```python
def parse_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.split(",")]
```

If a step changes code, show the code. If a step runs a command, show the command and the expected output.

## References to undefined types or functions

A task that calls `build_index(doc: Document) -> Index` but `Document` and `Index` are defined in Task 4 (which this worker hasn't read) leaves the worker guessing. Every type, function name, and method signature a task uses must be defined — either in the same task or explicitly imported from a named earlier task's Interfaces section.

**Bad:** "Call `validate(payload)` and pass the result to `store()`" with no definition of either function anywhere in the plan.
**Good:** Include exact signatures in the Interfaces section: `validate(payload: dict) -> ValidationResult` (defined in Task 1). `store(result: ValidationResult) -> None` (this task produces it).

## Tasks too large for one test cycle

If a task cannot be tested by a single `pytest` run or a single reviewer gate, it is too large. A task that adds a model, a service, an API endpoint, and a UI component is four tasks. Large tasks defeat the purpose of planning — the implementer has to decompose on the fly, and the reviewer cannot approve incrementally.

**Bad:** "Task 2: Build the order system — model, service, API, and admin view"
**Good:** Four tasks: Task 2 (Order model + migration), Task 3 (OrderService CRUD), Task 4 (POST /api/orders endpoint), Task 5 (admin order list view). Each ends with a runnable test and a commit.
