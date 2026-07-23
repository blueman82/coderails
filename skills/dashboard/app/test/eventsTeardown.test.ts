import { describe, it, expect } from "vitest";
import { createEventsHandler } from "../src/app/api/events/route";
import type { Aggregator, AggregatorDeps } from "../src/lib/collect";
import type { DashboardConfig } from "../src/lib/config";

// Teardown guard for the SSE route.
//
// The route previously tore down ONLY from ReadableStream.cancel(). That fires
// when the response *consumer* cancels, which a client that simply goes away
// does not reliably trigger — so an abandoned connection left its aggregator
// running: recursive fs.watch handles on projectsDir/loopsDir/runsDir/queueDir/
// buildsDir plus the gates setInterval, one full set per connection, never
// released.
//
// That is a file-descriptor leak, and it is fatal under launchd: the agent runs
// with `launchctl limit maxfiles` = 256 (NOT the shell's soft limit), so a
// handful of page loads exhausts the table. Once exhausted the server still
// accepts TCP but can no longer open files or watches, and it wedges: HTTP 000
// on every route, no SSE frames, panels stuck on "loading…" forever.
//
// So teardown must ALSO run when the request is aborted, and must be idempotent
// because both paths can fire for the same connection.

function testConfig(): DashboardConfig {
  return { repos: [], wikiPath: null } as unknown as DashboardConfig;
}

function req(signal?: AbortSignal): Request {
  return new Request("http://localhost:4173/api/events", {
    headers: { Origin: "http://localhost:4173", Host: "localhost:4173" },
    ...(signal ? { signal } : {}),
  });
}

/** Records start/stop calls so a test can assert the aggregator was released. */
function countingAggregator() {
  const calls = { start: 0, stop: 0, unsubscribed: 0 };
  const impl = (_deps: AggregatorDeps): Aggregator => ({
    getSnapshot: () => ({
      sessions: [], loops: [], gates: [], health: [], runs: [], queue: [], builds: [],
      contextTrend: undefined,
    }),
    subscribe: () => {
      return () => { calls.unsubscribed += 1; };
    },
    start: () => { calls.start += 1; },
    stop: () => { calls.stop += 1; },
  });
  return { calls, impl };
}

describe("GET /api/events — connection teardown", () => {
  it("stops the aggregator when the request is aborted, without any stream cancel()", async () => {
    const { calls, impl } = countingAggregator();
    const controller = new AbortController();
    const handler = createEventsHandler({ config: testConfig(), createAggregatorImpl: impl });

    const res = handler(req(controller.signal));
    expect(res.body).toBeTruthy();
    expect(calls.start).toBe(1);
    expect(calls.stop).toBe(0);

    // The client goes away. Nothing cancels the ReadableStream — this is the
    // exact path that leaked before.
    controller.abort();
    await new Promise((r) => setTimeout(r, 0));

    expect(calls.stop).toBe(1);
    expect(calls.unsubscribed).toBe(1);
  });

  it("is idempotent when abort and cancel both fire for one connection", async () => {
    const { calls, impl } = countingAggregator();
    const controller = new AbortController();
    const handler = createEventsHandler({ config: testConfig(), createAggregatorImpl: impl });

    const res = handler(req(controller.signal));
    controller.abort();
    await new Promise((r) => setTimeout(r, 0));
    await res.body!.cancel();

    // Exactly one teardown, no matter how many paths fire.
    expect(calls.stop).toBe(1);
    expect(calls.unsubscribed).toBe(1);
  });

  it("still tears down via cancel() when the request carries no abort signal", async () => {
    const { calls, impl } = countingAggregator();
    const handler = createEventsHandler({ config: testConfig(), createAggregatorImpl: impl });

    const res = handler(req());
    await res.body!.cancel();

    expect(calls.stop).toBe(1);
  });
});
