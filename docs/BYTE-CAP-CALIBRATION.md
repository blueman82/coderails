# Measure loop cost before setting a limit

Coderails does not configure a token cap for agentic loops in this repo.
Choose any provider limit from measured runs. Check the provider's current
settings before you set it. Do not use the example ranges from an older
version of this guide as measured Coderails data.

## Collect a completed loop

1. Run a representative task through `/coderails:agentic-loop`.
2. Resolve its state directory with
   `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.py"`.
3. After Phase 13 teardown, read `retro.json` beside `progress.json`.
   Its `cost` field holds the dated token and USD breakdown by model.
4. Record the task type, work-unit count, provider, model, completion state,
   and any context compaction. Keep the `cost.prices_as_of` date with USD
   amounts. An old price date needs a rate check; it does not change the
   recorded token count.
5. Repeat with tasks of the size you want the limit to cover. Include
   failed and retried loops so the sample covers their cost.

The live dashboard can show cost during a run. Use the completed retro for
a final comparison. `/coderails:post-evals` posts SHA-bound grading, not the
loop's final token or USD total.

## Choose and check a limit

Compare the measured token totals for similar tasks. Choose headroom for
retries and context compaction. Record the sample and the reason for the
headroom. Check the current provider documentation for the supported limit
and its setting name. This repo does not verify a Claude Code or Agent SDK
setting called `max_tokens_per_session` or an environment variable called
`RACHEL_MAX_TURNS`.

After setting a limit, run another representative loop. Check whether the
limit ends useful work before the loop finishes. Change the limit based on
that result. Recheck after a model, workflow, or task-size change.

## Sources

- [Agentic-loop teardown](../skills/agentic-loop/teardown.md) defines the
  completed retro and cost report.
- [Reference](REFERENCE.md#artifact-and-state-locations) lists loop state
  locations.
