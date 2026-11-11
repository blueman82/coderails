# Learned Failure Modes

**MACHINE-MAINTAINED — do not hand-edit.** Only the `loop-retro-promotion` pipeline may write this file.
It freezes task evals and uses a branch for this file alone.
It then runs `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:post-review`, `/coderails:post-evals`, and `/coderails:merge`.
Do not edit the file directly or run `gh pr merge` directly for its updates.
Check the source of changes from a different workflow.

## Promoted lessons

### A green test suite is not evidence the gate works — only a negative control run against the code that HAD the bug is

- **`Failure mode:`** Infrastructure defects can ship with all tests green. The author can miss the same condition in the code and in the tests. A first correction can also go green at 39/39 and leave a defect for a different reviewer to find.
- **Lesson:** Show that the gate stops code with the known defect. Use a negative control against the version that had it. "Tests pass" answers "is the code self-consistent?", but cannot answer "does the gate do its job?"
  1. Check that the control put back the code with the defect. `git stash push` on a committed file with no local edits does nothing. Use `git checkout <base-ref> -- <file>` with the specified ref. Check that the file has the intended contents before you trust the result.
  2. Derive each assertion from the goal in the report. Do not use the repo's own test suite as the oracle for the eval. A different reviewer can supply test inputs that the author did not use.
- **`Evidence:`** This recurred 7 times in 7 sessions. Session IDs (`fb2bfec4`, `2e82b342`, `007e525b`, `bc0e6ad9`, `75fa2e68`, `f876b596`, `0692aeab`). In `fb2bfec4`, two defects were live with 39/39 green on `main`. The first correction shipped a worse defect and also had 39/39 green. A different reviewer found the defects. In `1cc4c7d0`, five frozen evals asked the right questions but used incorrect checks. At freeze, the smoke run saw only negative results.

  Loop `75fa2e68` showed that a check with only negative results may give the same result for all inputs. Test the formula with a **synthetic pass-shaped input** at freeze time too.
- **Promotion date:** 2026-07-20

### A frozen, blind-authored check can itself be defective — validate each scripted check's discriminating power before freezing

- **`Failure mode:`** A frozen check can give the same result for all inputs. Examples include an `awk` formula that always exits 1 and a `grep` pattern with no occurrence in the input. A different shell may not read Bash syntax such as `<(command)`. These defects can go unseen when checks only give negative results before build.
- **Lesson:** At freeze time, run each scripted `cmd` and `negative_control` one time in the shell that will run the eval. Check that the environment and formula work. If there are optional `fixtures`, require opposite exit codes for the good and bad samples. Run the formula on good and bad inputs at freeze. For a change after freeze, record its `reason`, keep the assertion, and grade again if a verdict exists.

  For an agent-run eval, test the grader's prompt structure. Give the grader the artifact refs and keep the implementation conversation out. The author can miss its own compatibility code.
- **`Evidence:`** This recurred 4 times across 5 sessions (`8b69e779`, `bc0e6ad9`, `75fa2e68`, `1cc4c7d0`, `5f525531`). Four frozen checks in `8b69e779` had errors unrelated to the artifact. In `bc0e6ad9`, three frozen evals ran for the first time and gave errors. The reporter flag was unknown, the npm workspaces differed, and the gate blocked its own check.

  In `1cc4c7d0`, five frozen checks asked the right questions but used incorrect methods. Testing good and bad inputs at freeze could have found all five. In `5f525531`, an eval expected a regression check in one file. The correction correctly put it in a different file. A smoke run with synthetic fixtures could have distinguished the two.
- **Promotion date:** 2026-07-20

### The Bash tool's working directory drifts between calls to whichever sibling worktree was most recently entered — anchor every command

- **`Failure mode:`** Between Bash calls, the cwd can change to the worktree used most recently. A worker can test a different tree. The tests can succeed with an incorrect number of assertions, and Git can report a clean tree. Look at test counts, assertion counts, list lengths, or the cwd to find the change.
- **Lesson:** Specify the worktree for each Bash call. Start with `cd <absolute worktree path> &&`, use `git -C <absolute path>`, or use absolute paths for Git and file commands. Check known counts to identify which tree the command read. A different count can show a different tree. Absolute paths keep edits at the intended path. Line numbers such as `sed -n N`, whole-file searches, and paths in a changing worktree can give stale results.
- **`Evidence:`** This recurred 6 times across 5 sessions. Session IDs (`0767967d` loop ordinal 1, `8a43eccc`, `eafadd31`, `47859e78`, `b5fe4e97`). In `0767967d`, an assertion count showed that a worker tested a different tree. The orchestrator's shell also changed to a sibling worktree in multiple turns. An explicit `cd <absolute>` corrected the cwd each time.

  In `47859e78` and `b5fe4e97`, almost all Bash calls changed to a sibling worktree. The work was in a different tree. An explicit `cd <absolute>` or `git -C <absolute path>` corrected the reported cwd changes.
- **Promotion date:** 2026-07-20

### A worker's "all N items done" report on a multi-item fix list is a per-item claim, not one claim — verify each item against the merged artifact

- **`Failure mode:`** A worker can give one "done" report for multiple items. The first "done" included the gate correction but left the price and sanitisation unchanged. A subsequent "C fixed" included the guard but left incorrect numeric leaves. Instructions and reports crossed, so each report was two-thirds correct for earlier instructions. A worker's own green checks can agree with the worker's scope and miss an item. A different reviewer can test conditions that the worker did not check.
- **Lesson:** Apply Phase 12 to each item. Find or reproduce each item at the merged SHA. Examples include the price row, the sanitise call, the guard, and the test. A "done" report can mean "the last thing I understood you to ask," so check which instructions the worker used. If there is no result for an item, send that item to the worker and check it again. Do a short search for each "done" item. This can prevent a known type of crash from coming back.
- **`Evidence:`** This recurred two times (`47859e78` loop ordinal 1 and `f876b596` ordinal 2). In `47859e78`, three "done" reports were each two-thirds correct for a four-item miner correction. The orchestrator read from `origin` again and asked for each missing item. In `f876b596`, two reviewers found defects in PRs with honest green reports. A doc row contradicted a nearby paragraph. A test missed the sequence that led to the error.
- **Promotion date:** 2026-07-20

### Two spawned agents can receive the same unit's brief, or a worker can self-identify under the wrong name — resolve ownership by artifact, never by the name label

- **`Failure mode:`** Two agents with different names can get the same brief in one wave. This leaves a different unit without an owner. A "no branch exists yet" result can be out of date. It can cause a second dispatch for the same unit. The two workers can then try to use one branch. A worker can also report a different unit if it gets the orchestrator's cwd. An instruction can get to the worker after a report has left, which makes "already done" unclear.

  In a different session, a reviewer stayed idle for two intervals and gave no report. There was no artifact to check.
- **Lesson:** After dispatch, use artifacts to identify each owner. Before a second dispatch, check worktrees, branches, and open PRs again. A worker can start before its branch or PR appears. If the name and brief disagree, use the brief and files on disk. Give each unit a unique ID. Read the current artifacts again if an instruction and report arrive in a different sequence.

  **When no artifact exists.** Send no more than one reminder to an idle worker. If the scope is small and you read it all, do that work in the current session. If a gate or a published artifact needs the missing output, name the checks with no results. Do not claim that your own check completes the reviewer's work.

  While the agent is live, report only what you saw. A late report and a missing report look the same at that time. A durable artifact can turn an unsupported claim into an incorrect record.
- **`Evidence:`** This occurred in 10 sessions. The first four were `f87a0a2e`, `13b7e758`, `1cf76302`, and `0767967d`. The others were `8a43eccc`, `5b916f1a`, `eafadd31`, `47859e78`, `8b69e779`, and `7dfd0e8a`. The workers used the same branch in `f87a0a2e`. In `47859e78`, reports frequently arrived after new instructions ("49 awaiting-input stops in one loop, most from this crossing"). The orchestrator checked `origin` again before each step to correct this. In `5b916f1a`, an idle reviewer gave no report. The orchestrator performed a read-only check for a small part it had read.

  In `7dfd0e8a`, a published artifact from the reviewer said that two reviewers gave no output. The PR merged on that basis. One reviewer then sent a late report with three defects in the merged content. The PR needed a public correction. The artifact reported an inference as fact.
- **Promotion date:** 2026-07-27

### A concurrent actor can merge into the same files, take a reserved version number, or move the target you're mid-edit on — sweep for other in-flight work at intake, not just once

- **`Failure mode:`** A plan from a different session ran at the same time and merged edits to the same files. It used a reserved version number and broke the requirement to keep the versions equal. The author found the collision by accident. Other sessions had a PR merge changes to a shared file or multiple PRs land during one long task. Those merges required new fetches and edits. A dormant task with an owner may have no PR or live session. A search for the symbol or file can show that claim.
- **Lesson:** At intake, list prepared and pending plans for the same subsystem. Read plans that touch the same files, and list related open PRs. Check them again immediately before you do the work. Check a version reservation or other claim again before you use it. Fetch before each merge because the shared base can move. Look for each affected symbol or file in saved memory and task indexes. An owner can claim work without a PR or live session.
- **`Evidence:`** The check did not prevent damage or rework in four sessions. Session IDs (`13b7e758`, `1cf76302`, `b5fe4e97`, `8b69e779`). Four sessions had no rework (`f876b596`, `17c78b4e`, `0767967d`, `eafadd31`). The check found an active collision or a dormant task with an owner.

  In `b5fe4e97`, the shared base moved three times during one task. Two merges touched the same subject. In `f876b596`, a search found that a plausible target was the primary item in a different team's claim. One search prevented 33% of the proposed work from duplicating that claim.
- **Promotion date:** 2026-07-27

### Never edit the implementation to make a failed or qualified check pass by emitting the string it looks for — that changes what the system says about itself, not what it does

- **`Failure mode:`** A check needed to show that a component ran external to a specified execution path. The wrapper captured only its child's output. With no direct record in the logs, the check gave a grade with a qualification. The proposed correction would have printed the string the check searched for. The line could print if the mechanism did not run, and someone could write it by hand. The new line would also have a timestamp after the grade. In a different session, three frozen evals used a stale checkout. They gave incorrect negative results for a correction in a different worktree.
- **Lesson:** Keep a negative grade or a grade with a qualification. You can also correct a defect the check found or record the missing observation as future work. Do not add output only to satisfy a check. Use the question "does this change what the system DOES, or only what it SAYS about itself?" Use the question "Could this evidence be forged by the very component under test?" A component can supply a statement about its own operation. Get a record from a different source for proof.

  If a frozen check uses stale source, grade against the actual merge target and report the correction. Do not weaken or edit the check to get a positive grade.
- **`Evidence:`** This occurred in two sessions (`b5fe4e97` and `5f525531`). In `b5fe4e97`, the owner challenged the change before it shipped. In `5f525531`, three evals named a stale checkout. The team graded them again against the branch with the correction and kept the checks.
- **Promotion date:** 2026-07-27

### A sequencing or ordering decision you can already back with evidence you verified yourself is not a question for someone else — and an unnecessary pause lets the world move and decide it for you

- **`Failure mode:`** Two active tasks would edit the same files. The agent had checked which task it could start, which had a clear anchor, and which sequence it could undo. It sent the decision to a person two times. Work continued while it waited and resolved the question. In one instance, a concurrent merge resolved it. In a different task with broad authority, the agent also escalated multiple decisions it could check. These included correction sequence, a second check by a reviewer, and scope.
- **Lesson:** Make a decision in your scope if you have facts you checked directly. Check the basis for the decision. Record the decision and why, then continue. Shared data can change while a question is open. An answer that comes after the change can become obsolete and cost the reader time.
- **`Evidence:`** This occurred in three sessions (`007e525b`, `7e077d6c`, `0692aeab`). Loop `0692aeab` had 23 awaiting-input stops and 11 hard stops, the highest count on record. The agent could verify four or more steps in its authority in that session. They included correction sequence, a second check by a reviewer before merge, custody-fork scope, and merge repairs. The person replied "aren't you in a loop?"
- **Promotion date:** 2026-07-27

### A confident negative claim from one surface ("never happened", "nothing logs this", "not supported") can be simply wrong if you never checked where the component actually writes or documents itself

- **`Failure mode:`** A search of one log gave no results. The report said the component had "failed silently and never escalated." The component had written the escalation and its cause to a different path. A second error used a tool's help as proof that it rejected a flag. A live run showed the flag worked without a help entry.
- **Lesson:** A search with no results only tells you about that source. Before you say "never happened," "isn't supported," or "nothing logs this", find where the component writes or runs. Check the output or run directly. A redirected log or help page can have different coverage.
- **`Evidence:`** This occurred in two sessions (`7e077d6c` and `0692aeab`). In `7e077d6c`, the author reported the incorrect result to the user before the correction. In `0692aeab`, a live run found a working flag before the author removed it from a script.
- **Promotion date:** 2026-07-27

### A cleanup or teardown step is a state change that other automation may be watching as a trigger condition — check what it satisfies elsewhere before declaring a task complete

- **`Failure mode:`** A required teardown write archived or marked items as decayed. It also met the last condition for a dormant automation. A scheduled run then became active with a check that had a known defect. No one had checked it in the new context. In a different session, two writes in one teardown each met the condition of a different gate. One gate would have blocked the task from ending if the agent had not read its source.
- **Lesson:** Before teardown, find readers of each path that it will write or remove. Read each gate, hook, and scheduled task that names the path. Compare its trigger condition with the result of the proposed write. Run a check that reads a file before you remove that file. Write the terminal status before the gate that reads it runs. Do the search again before you declare the task complete. A write can satisfy the last condition of a dormant task.
- **`Evidence:`** This occurred in two sessions (`7e077d6c` and `bedcb0d4`). In `bedcb0d4`, the sequence of the writes was also necessary. A check had to read a path before its removal. The gate had to get the terminal status before it ran.
- **Promotion date:** 2026-07-27

### A destructive proof that temporarily disables a guard, even with an intended restore, must never run on a working tree another agent might also be editing concurrently

- **`Failure mode:`** A worker and orchestrator temporarily disabled a guard in the same worktree at the same time. Each planned to put it back after the proof. One of the two agents put back a stale version of a file. A check afterwards found the change. In a different session, a worker reported a "clean revert" but a subsequent checkpoint found the changed file.
- **Lesson:** Run a proof that disables a guard only on a disposable copy or a workspace for that proof alone. Do not use a worktree that a different agent might edit. If you must use a shared tree, compare the files independently with the contents before the change. The restore's "success" report is a claim. Use the diff to check it.
- **`Evidence:`** This occurred in two sessions (`0692aeab` and `a05e0075`). In `a05e0075`, a subsequent check found the change in the shared worktree after the worker reported a "confirmed clean revert".
- **Promotion date:** 2026-07-27

### Shared state written as JSON can be silently corrupted by a concurrent writer racing your own edit — a dropped comma reads downstream as a blanked field, not as a parse error

- **`Failure mode:`** A guard reported a blank ID, but the file showed the correct value. A different writer had edited the shared JSON file at about the same time. The file had no comma between two keys, and the reader gave an empty value. The guard reported a mismatch without a syntax error. This occurred on the same day in a different file with concurrent writes.
- **Lesson:** A guard can report a blank or incorrect field when the file shows the expected value. Check JSON syntax first. A reader can give the guard an empty or incorrect value if the file has a syntax error. Other tools can write to a task or session file at the same time.
  1. Check the syntax error and find the break. Look for a missing comma or brace. Do not rewrite the field without checking.
  2. Read the file again immediately before you write. Find the break in the current file. Do not rely on a line, column, or copy from before the other write.
  3. Correct a small, clear break in the current file. Replace the full file only if the damage prevents you from isolating one break. Use the current file as the source and keep the other writer's correct changes. A signal that the file changed calls for a new read and check. That signal alone does not authorize replacement of the full file.
- **`Evidence:`** This occurred in two sessions (`a05e0075` and `6ccd3c6a`). In each, a JSON syntax check gave the line and column of the missing comma. The guarded field itself was correct.
- **Promotion date:** 2026-07-27

### Write the exact field name and exact value a gate's parser reads, not a synonym that means the same thing to a human — even having just read this rule doesn't guarantee applying it at write time

- **`Failure mode:`** A gate blocked a declaration for work that had merged, deployed, and passed live checks. The record used a field and values a person could understand. The gate read a different field and accepted only a fixed set of values. It read the record as empty. The error recurred in a different session. It also recurred after the agent read this lesson in that session.
- **Lesson:** Before you write a field for a gate, read the gate's parser. Write the field name and one permitted value as written there. If a gate blocks work you believe is complete, check the record against the gate's list first. Read the list at the time of the write. Do not rely on memory of the list or this lesson.
- **`Evidence:`** This occurred in two sessions (`a4c9c07c` and `727e0f67`). In `727e0f67`, the agent read this lesson and then used synonyms in the record.
- **Promotion date:** 2026-07-27
