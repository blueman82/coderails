import { safeEvidence } from "./evidence.mjs";
import { parseProgressGraph } from "./graph.mjs";

const demoProgress = {
  graph: {
    nodes: {
      plan: { name: "Plan", status: "done", outcome: "done", retry: { attempts: 1, max: 3 }, prompt: "Inspect the requested Factory change.", activity: [{ at: "2026-08-28T09:00:00Z", message: "Scope recorded" }], checks: [{ name: "Scope", outcome: "pass" }], outputs: [{ name: "Plan", value: "Factory repair plan" }], attempts: [{ number: 1, outcome: "done", summary: "Plan recorded" }] },
      build: { name: "Build", status: "running", outcome: "running", retry: { attempts: 1, max: 3 }, prompt: "Implement the approved Factory-only repair.", activity: [{ at: "2026-08-28T09:02:00Z", message: "Writing the repair" }], checks: [{ name: "Unit tests", outcome: "running" }], outputs: [{ name: "Changed files", value: "factory/" }], attempts: [{ number: 1, outcome: "running", summary: "Repair in progress" }] },
      review: { name: "Review", status: "pending", outcome: "pending", retry: { attempts: 0, max: 3 }, prompt: "Review the Factory-only diff.", activity: [], checks: [], outputs: [], attempts: [] },
    },
    edges: [{ from: "plan", to: "build" }, { from: "build", to: "review" }],
    joins: { review: { mode: "all", inputs: ["build"], released: false } },
  },
};

const demoEvidence = Array.from({ length: 16 }, (_, index) => ({
  order: index + 1, type: "activity", source: "factory", timestamp: `2026-08-28T09:${String(index).padStart(2, "0")}:00Z`, payload: `Demo activity ${index + 1}`,
}));

export function createRunStore() {
  const runs = new Map();
  const subscribers = new Set();
  let selectedRunId = null;
  const selected = () => (selectedRunId ? runs.get(selectedRunId) : null);
  const publish = (event) => subscribers.forEach((subscriber) => subscriber(event));

  return {
    create({ id, projectId, provider, prompt, progress = null }) {
      if (!id || !projectId || !provider || typeof prompt !== "string" || runs.has(id)) throw new Error("invalid run record");
      const run = { id, projectId, provider, prompt, status: "queued", graph: parseProgressGraph(progress), evidence: [], orders: new Set() };
      runs.set(id, run);
      selectedRunId ??= id;
      return run;
    },
    createDemo() {
      const id = "demo-factory-run";
      if (runs.has(id)) {
        selectedRunId = id;
        return runs.get(id);
      }
      const run = this.create({ id, projectId: "factory-demo", provider: "codex", prompt: "Demonstrate the safe local Factory graph.", progress: demoProgress });
      demoEvidence.forEach((record) => this.appendEvidence({ runId: id, ...record }));
      return run;
    },
    appendEvidence(record) {
      const run = runs.get(record.runId);
      if (!run) throw new Error("unknown run");
      if (run.orders.has(record.order)) throw new Error("duplicate evidence order");
      run.orders.add(record.order);
      const evidence = safeEvidence(record);
      run.evidence.push(evidence);
      publish({ type: "evidence", evidence });
    },
    setStatus(id, status) {
      const run = runs.get(id);
      if (!run || !["queued", "running", "completed", "failed"].includes(status)) throw new Error("invalid run status");
      run.status = status;
      publish({ type: "status", runId: id, status });
    },
    select(id) {
      if (id !== null && !runs.has(id)) throw new Error("unknown run");
      selectedRunId = id;
    },
    subscribe(subscriber) {
      subscribers.add(subscriber);
      return () => subscribers.delete(subscriber);
    },
    snapshot() {
      const run = selected();
      return {
        runs: [...runs.values()].map(({ id, projectId, provider, status }) => ({ id, projectId, provider, status })),
        selectedRunId,
        ...(run ? { selectedRun: { id: run.id, projectId: run.projectId, provider: run.provider, prompt: run.prompt, status: run.status, graph: run.graph, evidence: run.evidence } } : {}),
      };
    },
  };
}
