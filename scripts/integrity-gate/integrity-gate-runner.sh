#!/bin/bash
# Root-owned, verification_level-free integrity attestor.
# It checks SHA-bound evidence and posts an integrity-review status. It never
# invokes an LLM and never decides whether a verification_level claim is semantically right.

INTEGRITY_GATE_CONTEXT="integrity-review"
INTEGRITY_GATE_MARKER_VERSION="v1"
INTEGRITY_GATE_MAX_DIFF_BYTES="${INTEGRITY_GATE_MAX_DIFF_BYTES:-204800}"
INTEGRITY_GATE_PATH_DENYLIST='^(skills/dashboard/|launchd/|scripts/integrity-gate/|\.github/workflows/)'
INTEGRITY_GATE_PENDING_TTL="${INTEGRITY_GATE_PENDING_TTL:-720}"
INTEGRITY_GATE_CURL_BIN="${INTEGRITY_GATE_CURL_BIN:-/usr/bin/curl}"

tg_log() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }

tg_repo_slug() {
  if [[ "${INTEGRITY_GATE_REPO:-}" =~ ^[^/]+/[^/]+$ ]]; then printf '%s' "$INTEGRITY_GATE_REPO"; return; fi
  local url; url=$(git remote get-url origin 2>/dev/null) || return 1
  [[ "$url" =~ github\.com[:/]([^/]+)/(.+)$ ]] || return 1
  printf '%s/%s' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]%.git}"
}

tg_token() {
  [[ -f "${INTEGRITY_GATE_CREDS:-}" ]] || return 1
  grep -E '^GH_TOKEN=' "$INTEGRITY_GATE_CREDS" | head -1 | cut -d= -f2-
}

tg_machine_user() {
  [[ -f "${INTEGRITY_GATE_CREDS:-}" ]] || return 1
  grep -E '^MACHINE_USER=' "$INTEGRITY_GATE_CREDS" | head -1 | cut -d= -f2-
}

# curl's exit code is transport-only; the HTTP code is checked explicitly.
tg_gh_get() {
  local target="$1" accept="${2:-application/vnd.github+json}" token slug url resp code
  token=$(tg_token) || return 1
  slug=$(tg_repo_slug) || return 1
  [[ "$target" == https://* ]] && url="$target" || url="https://api.github.com/repos/$slug/$target"
  resp=$("$INTEGRITY_GATE_CURL_BIN" -sS --max-time "${INTEGRITY_GATE_WATCHDOG_TIMEOUT:-60}" -w '\n%{http_code}' "$url" \
    -H "Authorization: Bearer $token" -H "Accept: $accept") || return 1
  code="${resp##*$'\n'}"
  [[ "$code" =~ ^2[0-9][0-9]$ ]] || { tg_log "integrity fetch failed http=$code url=$url"; return 1; }
  printf '%s' "${resp%$'\n'*}"
}

tg_pr_head_sha() { tg_gh_get "pulls/$1" | jq -r '.head.sha // empty' 2>/dev/null; }

tg_pr_comments() {
  local pr="$1" token slug url hdr body next
  token=$(tg_token) || return 1; slug=$(tg_repo_slug) || return 1
  url="https://api.github.com/repos/$slug/issues/$pr/comments?per_page=100"
  while [[ -n "$url" ]]; do
    hdr=$(mktemp) || return 1
    body=$("$INTEGRITY_GATE_CURL_BIN" -sS --max-time "${INTEGRITY_GATE_WATCHDOG_TIMEOUT:-60}" -D "$hdr" "$url" \
      -H "Authorization: Bearer $token" -H 'Accept: application/vnd.github+json') || { rm -f "$hdr"; return 1; }
    [[ "$(head -1 "$hdr" | awk '{print $2}')" =~ ^2 ]] || { rm -f "$hdr"; return 1; }
    printf '%s' "$body" | jq -r '.[] | .body | @base64' || { rm -f "$hdr"; return 1; }
    next=$(grep -i '^Link:' "$hdr" | grep -oE '<[^>]+>; rel="next"' | sed -E 's/^<([^>]+)>.*/\1/' | head -1)
    rm -f "$hdr"; url="$next"
  done
}

tg_newest_eval() {
  local pr="$1" sha="$2" encoded body line newest=""
  while IFS= read -r encoded; do
    [[ -n "$encoded" ]] || continue
    body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null) || return 1
    while IFS= read -r line; do
      [[ "$line" == "<!-- coderails-eval-summary v1 pr=$pr head_sha=$sha "*" -->" ]] && newest="$body"
    done <<< "$body"
  done < <(tg_pr_comments "$pr")
  [[ -n "$newest" ]] && printf '%s' "$newest"
}

tg_has_review() {
  local pr="$1" sha="$2" encoded body line
  while IFS= read -r encoded; do
    [[ -n "$encoded" ]] || continue
    body=$(printf '%s' "$encoded" | base64 -d 2>/dev/null) || return 1
    while IFS= read -r line; do
      [[ "$line" == "<!-- coderails-review-summary v1 pr=$pr head_sha=$sha -->" ]] && return 0
    done <<< "$body"
  done < <(tg_pr_comments "$pr")
  return 1
}

tg_statuses() {
  tg_gh_get "commits/$1/statuses?per_page=100" | jq '[.[] | select(.context == "integrity-review")]' 2>/dev/null
}

tg_should_gate() {
  local statuses="$1" state created now age
  [[ -n "$statuses" ]] || return 0
  state=$(printf '%s' "$statuses" | jq -r '.[0].state // empty')
  case "$state" in
    success|failure) return 1 ;;
    pending)
      created=$(printf '%s' "$statuses" | jq -r '.[0].created_at // empty')
      now=$(date +%s)
      age=$(date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$created" +%s 2>/dev/null || date -u -d "$created" +%s 2>/dev/null || printf '%s' "$now")
      (( now - age >= INTEGRITY_GATE_PENDING_TTL ));;
    *) return 1;;
  esac
}

tg_post_status() {
  local sha="$1" state="$2" description="$3" token user actual slug body code
  token=$(tg_token) || return 1; user=$(tg_machine_user) || return 1; slug=$(tg_repo_slug) || return 1
  actual=$("$INTEGRITY_GATE_CURL_BIN" -sS --max-time "${INTEGRITY_GATE_WATCHDOG_TIMEOUT:-60}" \
    https://api.github.com/user -H "Authorization: Bearer $token" | jq -r '.login // empty') || return 1
  [[ "$actual" == "$user" ]] || { tg_log "integrity identity mismatch expected=$user actual=$actual"; return 1; }
  body=$(jq -n --arg state "$state" --arg context "$INTEGRITY_GATE_CONTEXT" --arg description "$description" \
    '{state:$state,context:$context,description:$description}')
  code=$("$INTEGRITY_GATE_CURL_BIN" -sS --max-time "${INTEGRITY_GATE_WATCHDOG_TIMEOUT:-60}" -o /dev/null -w '%{http_code}' \
    "https://api.github.com/repos/$slug/statuses/$sha" -X POST \
    -H "Authorization: Bearer $token" -H 'Accept: application/vnd.github+json' \
    -H 'content-type: application/json' -d "$body") || return 1
  [[ "$code" =~ ^2[0-9][0-9]$ ]]
}

tg_gate_pr() {
  local pr="$1" sha body marker evals files filelist diff bytes statuses bad
  sha=$(tg_pr_head_sha "$pr")
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { printf 'skip: pr=%s reason=head_sha_fetch_failed\n' "$pr"; return 1; }
  body=$(tg_newest_eval "$pr" "$sha")
  [[ -n "$body" ]] || { printf 'skip: pr=%s sha=%s reason=no_eval_artifact\n' "$pr" "$sha"; return 0; }
  statuses=$(tg_statuses "$sha") || { printf 'skip: pr=%s sha=%s reason=status_fetch_failed\n' "$pr" "$sha"; return 1; }
  tg_should_gate "$statuses" || { printf 'skip: pr=%s sha=%s reason=already_terminal_or_fresh_pending\n' "$pr" "$sha"; return 0; }
  marker=$(printf '%s' "$body" | head -1)
  [[ "$marker" == *'result=GO'* ]] || { tg_post_status "$sha" failure "integrity=fail sha=$sha reason=eval_result_not_go"; return 0; }
  tg_has_review "$pr" "$sha" || { tg_post_status "$sha" error "integrity=fail sha=$sha reason=review_evidence_missing"; return 1; }
  evals=$(printf '%s\n' "$body" | awk '/^```json[[:space:]]*$/{on=1;next}/^```[[:space:]]*$/{if(on)exit}on{print}')
  printf '%s' "$evals" | jq -e --arg sha "$sha" 'type=="object" and .schema_version>=1 and (.task_ref|type)=="string" and (.frozen_sha|type)=="string" and .head_sha==$sha and (.evals|type)=="array"' >/dev/null 2>&1 || { tg_post_status "$sha" error "integrity=fail sha=$sha reason=eval_evidence_invalid"; return 1; }
  files=$(tg_gh_get "pulls/$pr/files?per_page=100") || { tg_post_status "$sha" error "integrity=fail sha=$sha reason=files_fetch_failed"; return 1; }
  filelist=$(printf '%s' "$files" | jq -r '.[].filename // empty')
  [[ -n "$filelist" ]] || { tg_post_status "$sha" error "integrity=fail sha=$sha reason=file_list_invalid"; return 1; }
  bad=$(printf '%s\n' "$filelist" | grep -E "$INTEGRITY_GATE_PATH_DENYLIST" | head -1)
  [[ -z "$bad" ]] || { tg_post_status "$sha" failure "integrity=fail sha=$sha reason=policy_path_$bad"; return 0; }
  diff=$(tg_gh_get "pulls/$pr" 'application/vnd.github.v3.diff') || { tg_post_status "$sha" error "integrity=fail sha=$sha reason=diff_fetch_failed"; return 1; }
  bytes=$(printf '%s' "$diff" | wc -c | tr -d ' ')
  [[ -n "$diff" && "$bytes" -le "$INTEGRITY_GATE_MAX_DIFF_BYTES" ]] || { tg_post_status "$sha" failure "integrity=fail sha=$sha reason=diff_invalid_or_oversize"; return 0; }
  tg_post_status "$sha" pending "integrity=pending sha=$sha" || return 1
  if tg_post_status "$sha" success "integrity=pass sha=$sha evidence=review,eval,commands policy=checked provenance=sha-bound independent=machine"; then
    printf 'gated: pr=%s sha=%s state=success integrity=pass\n' "$pr" "$sha"
  else
    printf 'gated: pr=%s sha=%s state=status_post_failed integrity=pass\n' "$pr" "$sha"; return 1
  fi
}

tg_poll_once() {
  local prs pr summary
  prs=$(tg_gh_get 'pulls?state=open&per_page=100') || { tg_log 'tick: pr_fetch=FAILED'; return 0; }
  tg_log "tick: prs=$(printf '%s' "$prs" | jq 'length')"
  while IFS= read -r pr; do
    [[ -n "$pr" ]] || continue
    summary=$(tg_gate_pr "$pr"); [[ -n "$summary" ]] && tg_log "$summary"
  done < <(printf '%s' "$prs" | jq -r '.[].number // empty')
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then tg_poll_once; fi
