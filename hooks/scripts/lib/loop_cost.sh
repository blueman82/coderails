#!/bin/bash
# loop_cost.sh — sourced (not executed) bash lib exposing dc_mine_token_usage,
# mirroring the fail-open idiom and lib style of dc_mine_hook_blocks in
# discipline_common.sh.

# dc_mine_token_usage <session_id>
#   Mines token usage + estimated USD cost for one agentic-loop orchestrator
#   session PLUS every worker (subagent) transcript it spawned. Stdout: a
#   single JSON object (schema below). Fail-open to {} on ANY error (no glob
#   hit, unreadable dir, jq failure, missing price file) — never nonzero,
#   never block a caller, mirroring dc_mine_hook_blocks exactly.
#
#   Resolution: glob ~/.claude/projects/*/<session_id>.jsonl (override via
#   CLAUDE_PROJECTS_DIR for tests) -> its containing dir <proj> is the
#   orchestrator's project. Orchestrator transcript = that file. Worker
#   transcripts = everything under <proj>/<session_id>/subagents/ walked
#   RECURSIVELY (mirrors skills/dashboard/app/src/lib/collect/usage.ts
#   listJsonlFiles's recursive descent — a flat glob would miss an agent
#   that itself spawned a nested subagents/ dir).
#
#   Per transcript line (jq): keep only type=="assistant" with a
#   message.id (string), message.model present and != "<synthetic>", and a
#   message.usage object. DEDUPE by message.id, first occurrence wins — every
#   line for one id carries the identical cumulative usage snapshot (same
#   invariant documented in usage.ts:75-77). Sum per model: input_tokens,
#   output_tokens, cache_read_input_tokens, and cache_creation split into
#   cache_write_5m (message.usage.cache_creation.ephemeral_5m_input_tokens)
#   and cache_write_1h (message.usage.cache_creation.ephemeral_1h_input_tokens).
#   If the split object is absent but the legacy flat
#   cache_creation_input_tokens is present, the whole amount goes to
#   cache_write_5m — conservative, since 5m is the cheaper multiplier.
#
#   Pricing: hooks/scripts/lib/model_prices.json (override via
#   CLAUDE_MODEL_PRICES_FILE for tests). usd = input/1e6*in + output/1e6*out +
#   cache_read/1e6*read + cw5m/1e6*w5m + cw1h/1e6*w1h. A model present in
#   transcripts but absent from the price table: tokens still counted,
#   usd_estimate 0, id appended to unpriced_models (never dropped, never
#   crashed on).
dc_mine_token_usage() {
  local session="$1"
  local projects_dir="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"

  # Self-path resolution, cross-shell. ${BASH_SOURCE[0]} is bash-only — under
  # zsh it is empty inside a function, which would silently resolve
  # dirname's fallback to '.' (cwd) instead of this file's real directory.
  # zsh's own self-path idiom is ${(%):-%x}, but that syntax is a bash PARSE
  # error (not just a runtime one), so it can't appear directly in a script
  # bash also sources — it's routed through eval so bash's parser never sees
  # the literal token, and only the zsh branch (guarded by $ZSH_VERSION)
  # ever evaluates it.
  local self_path="${BASH_SOURCE[0]:-}"
  if [ -z "$self_path" ] && [ -n "${ZSH_VERSION:-}" ]; then
    self_path="$(eval 'echo ${(%):-%x}')"
  fi
  local prices_file="${CLAUDE_MODEL_PRICES_FILE:-$(dirname "$self_path")/model_prices.json}"

  command -v jq >/dev/null 2>&1 || { printf '{}'; return 0; }
  [ -n "$session" ] || { printf '{}'; return 0; }
  [ -f "$prices_file" ] || { echo "loop_cost: prices file not found at $prices_file" >&2; printf '{}'; return 0; }

  # session_id is harness-owned (caller-supplied), not attacker-controlled —
  # defence-in-depth against path traversal, not a security boundary (same
  # framing as als_sanitise_session_id's own comment). Reuse that helper's
  # exact strip-"/"-and-collapse-".." transform rather than duplicating it,
  # since $session is already known non-empty here (checked above), its
  # empty/"?" fresh-fallback branch never fires for this call site.
  if ! declare -f als_sanitise_session_id >/dev/null 2>&1; then
    # shellcheck source=/dev/null
    # Reuse $self_path (resolved above) rather than ${BASH_SOURCE[0]} again —
    # under zsh that expands empty inside a function, so dirname's fallback
    # would silently resolve to '.' (cwd) instead of this file's real
    # directory, degrading (not crashing, thanks to the 2>/dev/null + the
    # declare -f fallback below) to an unsanitised session id.
    . "$(dirname "$self_path")/loop_state_common.sh" 2>/dev/null
  fi
  if declare -f als_sanitise_session_id >/dev/null 2>&1; then
    session="$(als_sanitise_session_id "$session")"
  fi

  # Resolve <proj> — the directory containing <session>.jsonl.
  # Under zsh, nomatch is on by default: an unmatched glob is a HARD ERROR,
  # not a silent empty expansion like bash. A session with no transcript
  # would crash the for loop before the orch_transcript fail-open guard
  # below ever ran. null_glob makes the unmatched glob expand to nothing
  # instead, so the loop body simply never runs — scoped to this function via
  # local_options so it doesn't leak into the caller's shell. Under bash,
  # setopt is not a builtin: it exits 127 to /dev/null and behaviour is
  # unchanged (bash already expands to the literal pattern, which the
  # existing `[ -f "$f" ] || continue` below then skips). That 127 is
  # discarded here, but it WOULD abort a caller running under `set -e` —
  # no such caller exists (guard scripts deliberately don't use set -e).
  setopt local_options null_glob 2>/dev/null
  local orch_transcript="" proj=""
  for f in "$projects_dir"/*/"$session.jsonl"; do
    [ -f "$f" ] || continue
    orch_transcript="$f"
    proj="$(dirname "$f")"
    break
  done
  [ -n "$orch_transcript" ] || { printf '{}'; return 0; }

  # Collect transcripts: the orchestrator file, plus every .jsonl found by
  # recursing under <proj>/<session>/subagents/ (find handles arbitrary
  # nesting depth for free — mirrors listJsonlFiles's recursive descent).
  local -a transcripts=("$orch_transcript")
  local subagents_dir="$proj/$session/subagents"
  if [ -d "$subagents_dir" ]; then
    while IFS= read -r -d '' f; do
      transcripts+=("$f")
    done < <(find "$subagents_dir" -type f -name '*.jsonl' -print0 2>/dev/null)
  fi

  local scanned=${#transcripts[@]}

  # Per-line tolerant parse (stage 1: drop malformed lines) then aggregate
  # over the survivors (stage 2), same two-stage style as dc_extract_last_text.
  local mined
  mined=$(
    for t in "${transcripts[@]}"; do
      jq -R 'fromjson? // empty' "$t" 2>/dev/null
    done | jq -s '
      [ .[]
        | select(.type == "assistant")
        | select(.message.id != null and (.message.id | type) == "string")
        | select(.message.model != null and .message.model != "<synthetic>")
        # Type-guard, not just presence: a wrong-typed usage (e.g. a string)
        # is not just "no usage" — indexing it downstream (.usage.cache_creation)
        # throws and jq -s aborts the WHOLE aggregation, wiping every other
        # transcript real numbers to a bare {}. Drop the one bad line here
        # instead, same as any other malformed line, so the batch survives.
        | select(.message.usage != null and (.message.usage | type == "object"))
        | { id: .message.id, model: .message.model, usage: .message.usage }
      ]
      # dedupe by message.id, first occurrence wins (unique_by keeps the
      # first element of each equal-key group, verified against ordering
      # with duplicate ids interleaved — not incidental)
      | unique_by(.id)
      | reduce .[] as $e (
          {};
          ($e.model) as $m
          | (.[$m] // {input_tokens:0,output_tokens:0,cache_read_tokens:0,cache_write_5m_tokens:0,cache_write_1h_tokens:0}) as $cur
          # Wrong-typed cache_creation (e.g. a string) must fall through to
          # the legacy-field branch, not throw on ".ephemeral_5m_input_tokens"
          # — same whole-batch-wipeout risk as the usage type-guard above.
          | (if ($e.usage.cache_creation | type) == "object" then $e.usage.cache_creation else null end) as $cc
          # One leaf deeper: `// 0` alone only substitutes on null/false, NOT
          # on a wrong-typed value — ("abc" // 0) is still "abc", and adding
          # that to a number throws, same whole-batch-wipeout risk as above.
          # `| numbers` filters out anything non-numeric first so the `// 0`
          # fallback actually catches wrong-typed leaves too.
          | (if $cc != null then (($cc.ephemeral_5m_input_tokens | numbers) // 0) else (($e.usage.cache_creation_input_tokens | numbers) // 0) end) as $cw5m
          | (if $cc != null then (($cc.ephemeral_1h_input_tokens | numbers) // 0) else 0 end) as $cw1h
          | .[$m] = {
              input_tokens: ($cur.input_tokens + (($e.usage.input_tokens | numbers) // 0)),
              output_tokens: ($cur.output_tokens + (($e.usage.output_tokens | numbers) // 0)),
              cache_read_tokens: ($cur.cache_read_tokens + (($e.usage.cache_read_input_tokens | numbers) // 0)),
              cache_write_5m_tokens: ($cur.cache_write_5m_tokens + $cw5m),
              cache_write_1h_tokens: ($cur.cache_write_1h_tokens + $cw1h)
            }
        )
    ' 2>/dev/null
  )
  [ -n "$mined" ] || { printf '{}'; return 0; }
  echo "$mined" | jq -e . >/dev/null 2>&1 || { printf '{}'; return 0; }

  # Price each model. jq -s with two inputs (mined per-model, price table).
  local result
  result=$(jq -sn \
    --slurpfile per_model <(printf '%s' "$mined") \
    --slurpfile prices "$prices_file" \
    --argjson scanned "$scanned" \
    '
    ($per_model[0]) as $pm
    | ($prices[0]) as $pt
    | ($pt.per_mtok // {}) as $rates
    | (
        $pm | to_entries | map(
          .key as $model
          # Rate lookup only, never the emitted key: transcripts record the
          # resolved dated snapshot (e.g. claude-haiku-4-5-20251001) while
          # the price table is keyed by the bare alias (claude-haiku-4-5).
          # Strip a trailing -YYYYMMDD before indexing $rates so a dated
          # snapshot still finds the alias rate; per_model/models_used
          # below keep the raw $model string so they match transcript
          # reality exactly.
          | ($model | sub("-[0-9]{8}$"; "")) as $lookup_key
          | .value as $t
          | ($rates[$model] // $rates[$lookup_key]) as $r
          | if $r == null then
              { model: $model, priced: (.value + {usd_estimate: 0}), unpriced: true }
            else
              ($t.input_tokens/1000000*$r.input
                + $t.output_tokens/1000000*$r.output
                + $t.cache_read_tokens/1000000*$r.cache_read
                + $t.cache_write_5m_tokens/1000000*$r.cache_write_5m
                + $t.cache_write_1h_tokens/1000000*$r.cache_write_1h) as $usd
              | { model: $model, priced: (.value + {usd_estimate: $usd}), unpriced: false }
            end
        )
      ) as $priced_entries
    | ($priced_entries | map({(.model): .priced}) | add // {}) as $per_model_out
    | ($priced_entries | map(select(.unpriced) | .model)) as $unpriced_models
    | {
        schema_version: 1,
        prices_as_of: ($pt.prices_as_of // ""),
        price_source: ($pt.price_source // ""),
        per_model: $per_model_out,
        total_tokens: ([$per_model_out[] | .input_tokens + .output_tokens + .cache_read_tokens + .cache_write_5m_tokens + .cache_write_1h_tokens] | add // 0),
        total_usd_estimate: ([$per_model_out[] | .usd_estimate] | add // 0),
        transcripts_scanned: $scanned,
        unpriced_models: $unpriced_models,
        models_used: ($per_model_out | keys | sort),
        notes: "headless claude -p child sessions excluded (own top-level session, no parent linkage)"
      }
    ' 2>/dev/null)

  [ -n "$result" ] || { printf '{}'; return 0; }
  printf '%s' "$result"
  return 0
}
