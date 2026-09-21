#!/bin/bash
# loop_cost.sh — sourced (not executed) bash lib exposing dc_mine_token_usage,
# mirroring the fail-open idiom and lib style of dc_mine_hook_blocks in
# discipline_common.sh.

# dc_mine_token_usage <session_id>
#   Mines token usage + estimated USD cost for one agentic-loop orchestrator
#   session PLUS every worker (subagent) transcript it spawned. Stdout: a
#   single JSON object (schema below). Fail-open on ANY error (no glob hit,
#   unreadable dir, jq failure, missing price file) — never nonzero, never
#   block a caller, mirroring dc_mine_hook_blocks exactly. Every environmental
#   fail-open (no jq, missing/invalid price file, mining/pricing jq failure —
#   five paths, all things that can be true of a CORRECT call) returns a bare
#   {}, with a distinct diagnostic on stderr.
#   The two CALLER-error paths — no session id argument, or a session id that
#   resolves to no transcript anywhere under the projects dir — are
#   additionally self-describing on STDOUT: {"error":"...","hint":"..."}, no
#   total_tokens/total_usd_estimate/schema_version keys, so they survive
#   2>/dev/null and can't be mistaken for a successful-but-empty mine.
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
dc_loop_cost_json_safe_string() {
    local value="$1"
    value="${value//\\/}"
    value="${value//\"/}"
    printf '%s' "$value"
}

dc_loop_cost_headless_window() {
    local window="$1"
    case "$window" in '' | *[!0-9]*) window=3600 ;; esac
    printf '%s' "$window"
}

dc_loop_cost_abs_difference() {
    local difference=$(($1 - $2))
    ((difference < 0)) && difference=$((-difference))
    printf '%s' "$difference"
}

dc_loop_cost_orchestrator_transcript() {
    local projects_dir="$1" session="$2" transcript
    setopt local_options null_glob 2>/dev/null
    for transcript in "$projects_dir"/*/"$session.jsonl"; do
        [ -f "$transcript" ] || continue
        printf '%s' "$transcript"
        return 0
    done
}

dc_loop_cost_price_models() {
    local mined="$1" prices_file="$2" scanned="$3" headless_count="$4"
    jq -sn --slurpfile per_model <(printf '%s' "$mined") --slurpfile prices "$prices_file" --argjson scanned "$scanned" --argjson headless_excluded "$headless_count" '($per_model[0]) as $pm | ($prices[0]) as $pt | ($pt.per_mtok // {}) as $rates | ($pm | to_entries | map(.key as $model | ($model | sub("-[0-9]{8}$"; "")) as $lookup_key | .value as $t | ($rates[$model] // $rates[$lookup_key]) as $r | if $r == null then { model: $model, priced: (.value + {usd_estimate: 0}), unpriced: true } else ($t.input_tokens/1000000*$r.input + $t.output_tokens/1000000*$r.output + $t.cache_read_tokens/1000000*$r.cache_read + $t.cache_write_5m_tokens/1000000*$r.cache_write_5m + $t.cache_write_1h_tokens/1000000*$r.cache_write_1h) as $usd | { model: $model, priced: (.value + {usd_estimate: $usd}), unpriced: false } end)) as $priced_entries | ($priced_entries | map({(.model): .priced}) | add // {}) as $per_model_out | ($priced_entries | map(select(.unpriced) | .model)) as $unpriced_models | {schema_version: 1, prices_as_of: ($pt.prices_as_of // ""), price_source: ($pt.price_source // ""), per_model: $per_model_out, total_tokens: ([$per_model_out[] | .input_tokens + .output_tokens + .cache_read_tokens + .cache_write_5m_tokens + .cache_write_1h_tokens] | add // 0), total_usd_estimate: ([$per_model_out[] | .usd_estimate] | add // 0), transcripts_scanned: $scanned, unpriced_models: $unpriced_models, models_used: ($per_model_out | keys | sort), headless_children_excluded_count: $headless_excluded, notes: "headless claude -p child sessions excluded from per_model/total_tokens (own top-level session, no parent linkage to attribute their tokens) — see headless_children_excluded_count for how many candidates were detected in the same project dir within the activity window"}' 2>/dev/null
}

dc_loop_cost_self_path() {
    local self_path="${BASH_SOURCE[0]:-}"
    [ -n "$self_path" ] || [ -z "${ZSH_VERSION:-}" ] || self_path="$(eval 'echo ${(%):-%x}')"
    printf '%s' "$self_path"
}

dc_loop_cost_session_or_error() {
    [ -n "$1" ] && return 0
    echo "loop_cost: empty session id" >&2
    printf '{"error":"loop_cost: empty session id","hint":"dc_mine_token_usage requires a session id as its first argument"}'
    return 1
}

dc_loop_cost_sanitise_session() {
    local session="$1" self_path="$2"
    # shellcheck disable=SC1091 # Runtime-relative library path is intentionally dynamic.
    declare -f als_sanitise_session_id >/dev/null 2>&1 || . "$(dirname "$self_path")/loop_state_common.sh" 2>/dev/null
    declare -f als_sanitise_session_id >/dev/null 2>&1 && als_sanitise_session_id "$session" || printf '%s' "$session"
}

dc_loop_cost_transcripts() {
    local orch_transcript="$1" proj="$2" session="$3" f
    printf '%s\0' "$orch_transcript"
    [ -d "$proj/$session/subagents" ] || return
    find "$proj/$session/subagents" -type f -name '*.jsonl' -print0 2>/dev/null
}

dc_loop_cost_headless_count() {
    local orch_transcript="$1" proj="$2" f orch_mtime f_mtime diff count=0
    local window
    window="$(dc_loop_cost_headless_window "${CLAUDE_HEADLESS_WINDOW_SECS:-3600}")"
    orch_mtime=$(stat -c %Y "$orch_transcript" 2>/dev/null || stat -f %m "$orch_transcript" 2>/dev/null)
    [ -n "$orch_mtime" ] || {
        printf '0'
        return
    }
    while IFS= read -r -d '' f; do
        [ "$f" = "$orch_transcript" ] && continue
        f_mtime=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
        [ -n "$f_mtime" ] || continue
        diff="$(dc_loop_cost_abs_difference "$f_mtime" "$orch_mtime")"
        [ "$diff" -le "$window" ] && count=$((count + 1))
    done < <(find "$proj" -maxdepth 1 -type f -name '*.jsonl' -print0 2>/dev/null)
    printf '%s' "$count"
}

dc_loop_cost_mine_transcripts() {
    local transcript
    for transcript in "$@"; do
        jq -R 'fromjson? // empty' "$transcript" 2>/dev/null
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
}

dc_mine_token_usage() {
    local session="${1:-}" projects_dir="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
    dc_loop_cost_session_or_error "$session" || return 0
    local self_path
    self_path="$(dc_loop_cost_self_path)"
    local prices_file="${CLAUDE_MODEL_PRICES_FILE:-$(dirname "$self_path")/model_prices.json}"
    command -v jq >/dev/null 2>&1 || {
        echo "loop_cost: jq not found on PATH" >&2
        printf '{}'
        return 0
    }
    [ -f "$prices_file" ] || {
        echo "loop_cost: prices file not found at $prices_file" >&2
        printf '{}'
        return 0
    }
    session="$(dc_loop_cost_sanitise_session "$session" "$self_path")"
    local orch_transcript
    orch_transcript="$(dc_loop_cost_orchestrator_transcript "$projects_dir" "$session")"
    [ -n "$orch_transcript" ] || {
        echo "loop_cost: no transcript found for session $session under $projects_dir" >&2
        printf '{"error":"loop_cost: no transcript found for session %s","hint":"check the session id is the live orchestrator session and CLAUDE_PROJECTS_DIR points at the right projects dir"}' "$(dc_loop_cost_json_safe_string "$session")"
        return 0
    }
    local proj
    proj="$(dirname "$orch_transcript")"
    local transcript
    local -a transcripts=()
    while IFS= read -r -d '' transcript; do transcripts+=("$transcript"); done < <(dc_loop_cost_transcripts "$orch_transcript" "$proj" "$session")
    local mined
    mined="$(dc_loop_cost_mine_transcripts "${transcripts[@]}")"
    [ -n "$mined" ] || {
        echo "loop_cost: mining produced no output" >&2
        printf '{}'
        return 0
    }
    printf '%s' "$mined" | jq -e . >/dev/null 2>&1 || {
        echo "loop_cost: mining produced invalid JSON" >&2
        printf '{}'
        return 0
    }
    local result
    result="$(dc_loop_cost_price_models "$mined" "$prices_file" "${#transcripts[@]}" "$(dc_loop_cost_headless_count "$orch_transcript" "$proj")")"
    [ -n "$result" ] || {
        echo "loop_cost: pricing produced no output" >&2
        printf '{}'
        return 0
    }
    printf '%s' "$result"
}
