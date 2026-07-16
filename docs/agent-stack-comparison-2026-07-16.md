# coderails + Rachel vs OpenClaw vs Hermes Agent — 2026-07-16

Local working document. Gitignored — not repo documentation. Web-sourced claims
are as-reported by the cited articles (fetched 2026-07-16); neither external
codebase was audited. No prior hermes/openclaw review exists in any local
memory, wiki, or history (verified by grep) — this is a fresh comparison, not
a delta.

## What they are

- **OpenClaw** — ~346k-star open-source personal assistant, breadth-first
  (15+ chat channels, multi-model, ClawHub skill marketplace, commercial SaaS).
- **Hermes Agent** — Nous Research's ~61k-star framework (first release
  2026-02-25), built around a self-improving learning loop and a proactive
  7-layer security model. MIT, strictly self-hosted.

## Comparison table

| Dimension | coderails + Rachel | OpenClaw | Hermes Agent | Match/Differ | Winner and why |
|---|---|---|---|---|---|
| **Core thesis** | Discipline enforcement: assume the agent rationalises, gate mechanically. Ex: `merge.sh` refuses a merge until SHA-bound review + eval artifacts exist | Reach: be everywhere the user is. Ex: one agent answering on WhatsApp, Telegram, iMessage | Improvement: get better at *your* workflows. Ex: agent writes a reusable procedure after a complex task, refines it on reuse | All differ — three different bets | **Depends on user.** For unattended coding agents, coderails' bet is the right one |
| **Verification gates** | SHA-bound PR artifacts, frozen anti-gaming evals, DNV/confidence Stop hooks. Ex: PR #189 needed review artifact + tier-0 eval GO computed by script, not by the agent | None comparable — skills ship and run, no acceptance gating | Dangerous-command approval (manual/smart/off) — action gating, not output verification | Differ | **coderails**, not close. Neither competitor asks "did the work actually meet the goal?" |
| **Security architecture** | In-trust-domain hooks (redirect-and-audit, per AGENTS.md's own ceiling) + Rachel's draft-first send gate. Ex: PreToolUse hook blocks every Slack/Calendar send until exact content is approved | Reactive. 5 CVEs incl. 9.1 path-traversal; ClawHavoc: 1,184 malicious ClawHub packages, ~15-25k installs hit | Proactive 7-layer: DM-pairing auth, container isolation (7 backends), Tirith pre-exec scan, prompt-injection scanning | Differ sharply | **Hermes.** Containers put enforcement *outside* the agent's trust domain — the exact ceiling AGENTS.md admits (and the 2026-07-16 session demonstrated: three `rm` reformulations, the third passed) |
| **Learning loop** | workflow-audit: mines transcripts → n-gram clusters → judge verdict → TDD-built skill via full PR gate. Ex: verify-merged-pr was built end-to-end from an Approve click | None — ClawHub is a marketplace of *other people's* skills, workspace-isolated, not self-improving | Records skill outcomes, promotes patterns to portable skills (agentskills.io), "Curator" prunes/consolidates the library autonomously | coderails and Hermes match in intent, differ in gating; OpenClaw absent | **Hermes on automation, coderails on trust.** Hermes learns continuously; coderails makes every learned skill survive a judge + PR gate before it exists |
| **Memory** | Curated file memories + two Obsidian wikis with lint (2026-07-16 lint caught 3 pages a prior sweep missed) | Two-level markdown/JSONL — simple, editable, no curation mechanism reported | FTS5-searchable history + Honcho user modelling + background curation | Rachel≈Hermes on curation; OpenClaw simplest | **Hermes narrowly** — automated curation + user modelling; the wikis match the outcome but need owner-driven lint passes |
| **Channels** | Telegram (Rachel's bridge) + dashboard + Claude Code CLI | 15-25+ platforms incl. WhatsApp, iMessage, Signal, Teams | Fewer; DM-pairing gated | Differ | **OpenClaw** — it's the entire product thesis |
| **Scheduling** | launchd routines + Rachel's self-created cloud routines (RemoteTrigger). Ex: morning inbox brief to Telegram | Cron + webhooks + heartbeat. Ex: 7am briefing scanning calendar/Slack/weather | Hardened cron-job storage (isolation-focused) | Rough match, all three | **Tie coderails/OpenClaw** — same capability; Rachel's is bespoke-but-yours, OpenClaw's is turnkey |
| **Cost observability** | Per-loop token/USD mining frozen into retro.json + dashboard rollups. Ex: the loop that built the feature recorded itself costing $132.73 | Not reported in any source read | Cost-efficiency claimed, no per-task artifact reported | Differ | **coderails** — a per-loop dated cost artifact is unique among the three |
| **Ecosystem** | Audience of one (private repo, by choice) | 346k stars, marketplace, commercial SaaS | 61k stars in weeks, 6 releases in 50 days, MIT, self-hosted only | Differ | **OpenClaw** on size — but its marketplace is also its attack surface (ClawHavoc) |

## Overall verdict

No single winner — three different games. **OpenClaw wins reach, Hermes wins
architecture, coderails+Rachel wins trustworthiness of output** — nothing else
here can prove a change met its goal before it merged. The symmetric truth:
coderails' one structural weakness is that its gates live inside the agent's
trust domain (AGENTS.md admits this itself), which is precisely where Hermes is
strongest; Hermes/OpenClaw's weakness — no verification that work is *correct*,
only that it *ran* — is precisely where coderails is strongest. Worth stealing:
Hermes' container isolation for coderails' worker agents. Worth keeping: the
SHA-bound artifact gate, which neither competitor has.

## Five improvement picks (priority order)

1. **Move worker enforcement outside the agent's trust domain** — sandbox
   agentic-loop workers (macOS `sandbox-exec` or Docker worktree) with
   deny-by-default filesystem writes outside their worktree. An out-of-domain
   gate returns EPERM instead of being pattern-matched around. NOT branch
   protection — that is a standing ruled-out decision.
2. **Close the learning loop** — workflow-audit, loop-retro-promotion, and
   wiki-lint all exist and all fire only manually. A scheduled routine (weekly
   workflow-audit, post-ingest wiki-lint) writing to the existing dashboard
   approval queue = Hermes' Curator built from owned parts, with the judge+PR
   gate kept in the path.
3. **Gate on intent signals, not string patterns** — widen `crack_on_gate` to
   the no-questions idiom family ("no questions", "just do it"); add
   retry-escalation to `destructive_bash_gate` (N blocks on one intent in one
   turn → deny the turn's remaining Bash).
4. **Rachel's availability, not breadth** — shift time-critical routines
   (morning brief) to the existing cloud-routine path (RemoteTrigger) so they
   survive the Mac sleeping. Don't chase OpenClaw's channel count.
5. **Sharpen the verification moat** — a fresh subagent that only answers "is
   this tier justification honest?" closes the tier-0 self-exemption seam the
   task-evals rules already worry about.

If only one: #1. The 2026-07-16 session proved cooperation is the weakest
layer, and it's the only one a container fixes by construction.

## Sources

- https://innfactory.ai/en/blog/openclaw-vs-hermes-agent-comparison/
- https://wanjohichristopher.com/blog/ai/hermes-vs-openclaw/
- https://github.com/openclaw/openclaw
- https://openclaw.ai/
- https://hackernoon.com/hermes-agent-vs-openclaw-which-ai-agent-framework-wins-in-2026 (403'd — not read, listed for completeness)
