# E4: bootstrap manifest and Codex model routing

> **Bootstrap section superseded 2026-10-05** by `docs/decisions/2026-10-05-dynamic-context-manifest.md`.

Docs only. No behaviour change and no diagnostic log entry (nothing executes).

## Bootstrap manifest: threshold not crossed, no change

Rule (b) in `docs/graph-alignment-measurement.md`: compact the manifest only if a provider's injected SessionStart
context exceeds 8192 bytes.

Reproduce: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['bootstrap_bytes'])"`

| Provider | Bytes added at startup | Threshold | Headroom |
| --- | ---: | ---: | ---: |
| Claude (`hooks/scripts/inject_bootstrap.py`) | 6288 (skill file 6057) | 8192 | 1904 |
| Codex (`packages/codex/hooks/scripts/inject_bootstrap.py`) | 225 (5089 more loaded on demand, 5314 combined) | 8192 | 7967 at startup |

The values were below the limit, so the manifest stayed the same. The 2026-10-04 measurement gave the same figures as the pre-committed run.
The logs give no counts for startup, clear, or compact. The total byte count is unknown (see result (b) in `docs/graph-alignment-measurement.md`).

## Codex model routing: PROPOSAL only

**Each model id below is UNVERIFIED.** The repository cannot check these IDs (guess). This change writes none of them to TOML or config.

| Task class | Proposed model / compute level |
| --- | --- |
| mechanical | `gpt-6-luna` / low (UNVERIFIED id) |
| default | `gpt-6.1-sol` / high (UNVERIFIED id) |
| work on design and grading | `gpt-6.1-sol` / ultra (UNVERIFIED id) |

- The Codex provider layer owns model selection. The three copies of `graph_semantics.py` keep the same bytes.
- `hooks/scripts/agent_model_routing_nudge.py` advises Claude on the `Agent` model override.
  Mechanical words suggest `haiku`. Complex words suggest `opus`.
  Codex routing should extend or mirror that nudge. The local log has 141 checks and 0 decisions. There are no measured decisions to tune the routing.
- Before adoption a human must check the IDs and compute levels against the provider's current model list.
