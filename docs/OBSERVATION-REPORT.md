# Native session observations

The dashboard reads native Claude and Codex session records. Each provider has its own reader.
The local diagnostic log cache holds IDs, hashes, counts, and source refs. It does not hold prompt or result text.
The source information view reads one native record only after the user opens it.

| Verification | Status |
|---|---|
| Source | The two readers, strict schemas, panels, and the report command exist in the candidate plugin. |
| Local | Synthetic records test privacy, labels, joins, counts, and panel output. |
| Installed | Capture a live session from each provider after installation. |
| Operation | A report applies only to its named, eligible sessions and bound source files. |

## Observation types

| Type | Meaning |
|---|---|
| Invocation | A native session records a call to a skill. The call does not prove that the skill finished. |
| Read | One direct context-file call has one subsequent result with text and a correct success marker. |
| Read error | One direct file-read call has one subsequent result with an explicit error. |
| `mention` | A text field names a known skill or context file. This does not prove a read. |
| Uncertain | A call has no result or the result does not show success or error. It also includes skill files that the reader cannot verify as installed. |

The target hash uses a normalized skill name or a known context file name.
The readers have no trusted installation-root data. A read with a path such as `skills/<name>/SKILL.md` stays uncertain if the read succeeds.
An explicit error stays a read error. For a context read, Claude accepts an omitted boolean error flag or a flag with value `false`.
Malformed flags stay uncertain.

The reader also records a `mention` for a message with text and tool use. The diagnostic log has no source path.
A byte count covers the full measured UTF-8 text field. If the field has no value, the count is unavailable.
The parser refuses source files above its scan limit. It does not give a count for a field with missing text.

Worker records can show a checked display name as `Name (short ID)`. If two loaded workers have the same short ID, the panel shows their full IDs.
The display name changes the display only. Native actor IDs, task names, graph node IDs, and joins stay the same.
The collision check covers the loaded page. It does not check all sessions in the store.

Claude use fields apply to one message. Codex `total_token_usage` fields are cumulative snapshots. The diagnostic log marks that difference.
Do not add cumulative snapshots. The reader cannot give a routing budget if the native transcript has no typed routing record.
Prose that a hook adds does not prove that the provider sent or used the routing instruction.

## Descriptive report

Run `python3 scripts/observation_report.py <cohorts.json>`. The cohort file names the baseline sessions and the sessions to compare.
Each entry gives the provider, native session ID, parser version, and eligibility. It gives exclusion or retry information when applicable.
It also gives paths and SHA-256 hashes for the diagnostic log manifest, entry file, and each native source file.

The command hashes each file again. It checks the links between the provider, session, parser, diagnostic log, source, entry, parent, and retry.
It refuses changed files, records from a different source, duplicate identities, and malformed metadata.

The report counts eligible sessions and the five observation types. It shows where coverage falls short. It also shows retries and exclusions.
Its output has no source path, body, token sum, or quality score.

For each session and source, the report counts one Claude message use for each hashed native message ID.
Without that ID, it deduplicates only entries from the same physical record. It cannot identify one message across records.
The report stores no native ID or message body. It counts each cumulative Codex snapshot as a record and does not add their token totals.

The report covers the enrolled sessions. It does not measure an effect of Coderails.
The report trusts observation labels from the native reader and the bound sources. It does not parse the native text a second time.
Capture a live session from each installed provider to accept the installation.

## Trust and count limits

The same user can edit source files, caches, cohort metadata, and reader code, then calculate the unkeyed hashes again.
Equal hashes connect the report to the declared bytes. They do not authenticate the capture or its author.
They do not prove installation or complete historical coverage. A source hash cannot prove that a skill file came from a trusted installation.

Coverage applies to the enrolled sessions and declared sources. The report cannot count files that this set omits.
The files in the set cannot show how many historical sources it does not include.

Observation counts apply to eligible sessions and their reader entries. Usage-record counts apply to provider records.
These counts do not measure token totals or report command calls. The report has no ledger for those calls or their refusals.
Publication counters count entries from the named publication checks. They do not count reports, native observations, or report validation refusals.

Use the [runbook for native observation reports](RUNBOOK.md#native-observation-report) for command results and input errors.
The [workflow gate measurements](workflow-gates-measurement.md) and [integrity gate instructions](INTEGRITY-GATE.md)
give the publication controls and their limits.
