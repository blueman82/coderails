import { safeEvidence } from "./evidence.mjs";
import { parseProgressGraph } from "./graph.mjs";

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
    setProgress(id, progress) {
      const run = runs.get(id);
      if (!run) throw new Error("unknown run");
      run.graph = parseProgressGraph(progress);
      publish({ type: "graph", runId: id, graph: run.graph });
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
