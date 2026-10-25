# Native session observations

The dashboard reads native Claude and Codex session records. Each provider keeps its own reader. The local trace cache holds IDs, hashes, counts, and source references. It does not hold prompt or result text. The source detail view reads one native record only after the user opens it.

| Evidence | Status |
|---|---|
| Source | Both readers, strict schemas, panels, and the report command exist in the candidate plugin. |
| Local | Synthetic records test privacy, labels, joins, counts, and panel output. |
| Installed | A real session from each provider still needs capture after installation. |
| Operation | A report applies only to its named, eligible sessions and bound source files. |

## Observation types

| Type | Meaning |
|---|---|
| Invocation | A native skill call was requested. This does not prove that the skill finished. |
| Read | One direct file-read request has one later result with text and no error marker. |
| Failed read | One direct file-read request has one later result with an explicit error. |
| Mention | A text field names a recognized skill or context file. This does not prove a read. |
| Uncertain | A request has no result, or the native result does not prove success or error. |

The target hash uses a normalized skill name or a recognized context file name. The trace does not store the source path. A byte count covers the complete observed UTF-8 text field. A missing field has an unavailable count. The parser refuses source files above its scan limit. It does not report a count from a partial field.

Worker events can show a validated display name as `Name (short ID)`. If two loaded workers have the same short ID,
the panel shows their full IDs. The name changes display only. Native actor IDs, task names, graph node IDs, and joins
stay the same. Collision detection covers the loaded page, not every session in a store.

Claude usage fields describe a message. Codex `total_token_usage` fields are cumulative snapshots. The trace marks that difference. Do not add cumulative snapshots. A route budget is unavailable when the native transcript has no typed route record. Injected prose does not prove that the provider delivered or used the route.

## Descriptive report

Run `python3 scripts/observation_report.py <cohorts.json>`. The cohort file names baseline and comparison sessions. Each entry gives the provider, native session ID, parser version, eligibility, any exclusion or retry link, and paths plus SHA-256 hashes for the trace manifest, event file, and each native source file.

The command rehashes every file. It checks the provider, session, parser, trace, source, event, parent, and retry links. It refuses changed files, foreign records, duplicate identities, and malformed metadata. The report counts eligible sessions and the five observation types. It shows incomplete coverage, retries, and exclusions. Its output has no source path, body, token sum, or quality score.

The report describes the enrolled sessions. It does not measure an effect of Coderails. The report trusts observation labels from the native reader and the bound sources. It does not parse the native text a second time. A real capture from each installed provider is required for installed acceptance.
