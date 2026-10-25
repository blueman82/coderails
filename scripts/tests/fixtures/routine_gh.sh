#!/bin/sh
echo "$@" >> "$GH_LOG"
if [ "$1 $2" = "pr list" ]; then echo 7; fi
if [ "$1 $2" = "pr view" ]; then
  if [ -n "$GH_MERGED_FILE" ] && [ -f "${GH_MERGED_FILE}.fail" ]; then exit 1; fi
  head=$(git rev-parse HEAD)
  base=$(git rev-parse origin/main)
  branch=$(git branch --show-current)
  if [ "$3" = 8 ]; then branch=other; head=$base; fi
  if [ -n "$GH_MERGED_FILE" ] && [ -f "${GH_MERGED_FILE}.mismatch" ]; then head=$base; fi
  state=OPEN
  if [ -n "$GH_MERGED_FILE" ] && [ -f "$GH_MERGED_FILE" ] && [ "$3" = 7 ]; then state=MERGED; fi
  printf '{"number":%s,"url":"https://github.com/example/test/pull/%s","headRefName":"%s","headRefOid":"%s","baseRefOid":"%s","state":"%s"}\n' "$3" "$3" "$branch" "$head" "$base" "$state"
fi
exit 0
