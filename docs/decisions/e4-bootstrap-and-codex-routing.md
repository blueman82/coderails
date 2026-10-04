# E4: bootstrap manifest and Codex model routing

Docs only. No behaviour change and no trace row (nothing executes).

## Bootstrap manifest: threshold not crossed, no change

Rule (b) in `docs/graph-alignment-measurement.md`: compact the manifest only if a provider's injected SessionStart
context exceeds 8192 bytes.

Reproduce: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['bootstrap_bytes'])"`

| Provider | Injected bytes | Threshold | Headroom |
| --- | ---: | ---: | ---: |
| Claude (`hooks/scripts/inject_bootstrap.py`) | 6288 (skill file 6057) | 8192 | 1904 |
| Codex (`packages/codex/hooks/scripts/inject_bootstrap.py`) | 225 (5089 more loaded on demand, 5314 combined) | 8192 | 7967 injected |

Decision: threshold not crossed, no change (re-measured 2026-10-04, same figures as the pre-committed run).
Caveat: how many startup, clear and compact events fire is in no log, so total injected volume is unmeasured
(`docs/graph-alignment-measurement.md`, finding (b)).

## Codex model routing: PROPOSAL only

**Every model id below is UNVERIFIED.** They cannot be confirmed from this repository (guess), and none is written
into any toml or config by this change.

| Task class | Proposed model / effort |
| --- | --- |
| mechanical | `gpt-6-luna` / low (UNVERIFIED id) |
| default | `gpt-6.1-sol` / high (UNVERIFIED id) |
| design and grading | `gpt-6.1-sol` / ultra (UNVERIFIED id) |

- Provider-owned: Codex model selection belongs to the Codex provider layer. It stays outside
  `graph_semantics.py`; the three byte-identical copies are not touched.
- Reuse, do not duplicate: `hooks/scripts/agent_model_routing_nudge.py` is the existing advisory mechanism for the
  Claude `Agent` model override (mechanical words suggest `haiku`, complex words suggest `opus`). Any Codex
  routing should extend or mirror that nudge. It has 141 evaluations and 0 decisions in the local log, so there is
  no measured behaviour to tune against yet.
- Before adoption a human must confirm the ids and the effort levels against the provider's current model list.
