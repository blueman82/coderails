#!/bin/sh
echo "$@" >> "$GH_LOG"
if [ "$1 $2" = "pr list" ]; then echo 7; fi
if [ "$1 $2" = "pr view" ]; then
  head=$(git rev-parse HEAD)
  base=$(git rev-parse origin/main)
  branch=$(git branch --show-current)
  if [ "$3" = 8 ]; then branch=other; head=$base; fi
  printf '{"number":%s,"headRefName":"%s","headRefOid":"%s","baseRefOid":"%s"}\n' "$3" "$branch" "$head" "$base"
fi
exit 0
