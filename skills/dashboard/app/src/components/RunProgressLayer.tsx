"use client";

import { useEffect, useState } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { useRunLifecycle } from "@/hooks/useRunLifecycle";
import { RunProgress } from "@/components/RunProgress";
import type { ActiveRun } from "@/hooks/useRunLifecycle";

interface TrackedRun {
  run: ActiveRun;
  resolved: { ok: boolean } | undefined;
}

// Bridges the SSE-derived `active` runs list (useRunLifecycle) into a set of RunProgress callouts
// that outlive their run's disappearance from `active` just long enough to show the resolve
// flash: a run is added when it first appears active, kept (marked resolved) once its matching
// runs.jsonl record gets an endedAt, and only removed when RunProgress itself calls onDone after
// the flash+fade finishes.
export function RunProgressLayer() {
  const { snapshot } = useDashboardContext();
  const { active } = useRunLifecycle(snapshot.runs);
  const [tracked, setTracked] = useState<Map<string, TrackedRun>>(new Map());

  useEffect(() => {
    setTracked((prev) => {
      const next = new Map(prev);

      for (const run of active) {
        const existing = next.get(run.runId);
        if (!existing) {
          next.set(run.runId, { run, resolved: undefined });
        } else if (existing.resolved) {
          // Reappeared active after being marked resolved shouldn't happen in practice, but if
          // it does, drop the stale resolved flag rather than showing a flash mid-run.
          next.set(run.runId, { run, resolved: undefined });
        }
      }

      const stillActiveIds = new Set(active.map((r) => r.runId));
      for (const [runId, entry] of next) {
        if (!stillActiveIds.has(runId) && !entry.resolved) {
          const finished = snapshot.runs.find((r) => r.runId === runId && r.endedAt !== undefined);
          if (finished) {
            next.set(runId, { run: entry.run, resolved: { ok: finished.exitCode === 0 } });
          } else {
            // Vanished without a finish record we can see (e.g. server restarted mid-run) — drop
            // it rather than showing a permanently-stuck callout.
            next.delete(runId);
          }
        }
      }

      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, snapshot.runs]);

  function handleDone(runId: string) {
    setTracked((prev) => {
      const next = new Map(prev);
      next.delete(runId);
      return next;
    });
  }

  const entries = Array.from(tracked.values());

  return (
    <>
      {entries.map((entry, i) => (
        <RunProgress
          key={entry.run.runId}
          run={entry.run}
          stackIndex={i}
          resolved={entry.resolved}
          onDone={() => handleDone(entry.run.runId)}
        />
      ))}
    </>
  );
}
