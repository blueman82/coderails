#!/bin/bash
# Aggregate test runner — discovers all *.test.sh in this directory and runs each.
set -u
cd "$(dirname "$0")" || exit 1

fails=0
skips=0
total=0

for test_file in *.test.sh; do
	[ -f "$test_file" ] || continue
	total=$((total + 1))
	printf '\n=== %s ===\n' "$test_file"
	if env -u GIT_ALTERNATE_OBJECT_DIRECTORIES -u GIT_CONFIG \
		-u GIT_CONFIG_PARAMETERS -u GIT_CONFIG_COUNT -u GIT_CONFIG_KEY_0 \
		-u GIT_CONFIG_VALUE_0 -u GIT_DIR -u GIT_WORK_TREE \
		-u GIT_COMMON_DIR -u GIT_IMPLICIT_WORK_TREE -u GIT_GRAFT_FILE \
		-u GIT_INDEX_FILE -u GIT_NO_REPLACE_OBJECTS -u GIT_REPLACE_REF_BASE \
		-u GIT_PREFIX -u GIT_SHALLOW_FILE bash "$test_file"; then
		printf 'OK\n'
	else
		rc=$?
		if [ "$rc" -eq 3 ]; then
			skips=$((skips + 1))
			printf 'SKIPPED (prerequisite): %s\n' "$test_file"
		else
			fails=$((fails + 1))
			printf 'FAILED (exit %d)\n' "$rc"
		fi
	fi
done

if [ "$total" -eq 0 ]; then
	printf 'run_all: ERROR — no *.test.sh files found in %s\n' "$(pwd)" >&2
	exit 1
fi

# Downstream consumers (eval/proof formulas) should gate on `fails`, not `passed==total` — a legitimate skip makes passed<total without being a failure.
printf '\n--- run_all: %d/%d suites passed, %d skipped ---\n' "$((total - fails - skips))" "$total" "$skips"

if [ "$skips" -eq "$total" ]; then
	printf 'WARNING: all %d suites skipped — nothing was actually verified\n' "$total" >&2
	exit 1
fi

[ "$fails" -eq 0 ] && exit 0 || exit 1
