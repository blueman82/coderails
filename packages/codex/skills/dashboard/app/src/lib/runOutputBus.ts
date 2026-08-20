// In-process pub/sub connecting POST /api/run (producer of live child-process
// output) to GET /api/events' aggregator (consumer, forwarded to the browser
// over the single SSE stream — see collect/index.ts's AggregatorEventName).
// Deliberately NOT a second SSE endpoint: the repo rule is one SSE provider,
// so run output rides the existing /api/events connection as a "run-output"
// event instead of opening a new stream.
//
// A shared module-level singleton is safe here because both producer and
// consumer are Route Handlers within the same Next.js route module graph —
// unlike the Route-Handler-vs-Server-Component split documented in
// runlog.ts's getRunToken comment (which forced that value onto disk instead
// of memory), route.ts-to-route.ts within app/api is one bundler layer, so a
// plain module-level Set survives across the two files' imports of this
// module in production. Confirmed empirically alongside this change: see
// test/runOutputBus.test.ts and the cross-route integration case in
// test/events.test.ts (run-output forwarding).
export interface RunOutputEvent {
  runId: string;
  chunk: string;
}

export type RunOutputListener = (event: RunOutputEvent) => void;

export interface RunOutputBus {
  publish(runId: string, chunk: string): void;
  subscribe(listener: RunOutputListener): () => void;
}

export function createRunOutputBus(): RunOutputBus {
  const listeners = new Set<RunOutputListener>();

  return {
    publish(runId: string, chunk: string): void {
      for (const listener of listeners) {
        try {
          listener({ runId, chunk });
        } catch {
          // A subscriber's own handling error must not stop delivery to the
          // remaining subscribers, nor propagate out of publish() and crash
          // the run that's producing this output.
        }
      }
    },
    subscribe(listener: RunOutputListener): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

// Process-wide singleton — the real production seam shared by
// api/run/route.ts (publisher) and lib/collect/index.ts's aggregator
// (subscriber, wired in via api/events/route.ts).
export const runOutputBus: RunOutputBus = createRunOutputBus();
