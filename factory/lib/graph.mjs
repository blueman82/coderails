const waiting = { state: "waiting", message: "Waiting for the native Coderails graph…" };

function namedList(node, id, name) {
  const value = node[name] ?? [];
  if (!Array.isArray(value)) throw new Error(`graph node ${id} ${name} must be an array`);
  return value;
}

export function parseProgressGraph(progress) {
  if (!progress) return waiting;
  const graph = progress.graph;
  if (!graph || typeof graph !== "object" || Array.isArray(graph)) return { state: "malformed", message: "graph must be an object" };
  if (!graph.nodes || typeof graph.nodes !== "object" || Array.isArray(graph.nodes)) return { state: "malformed", message: "graph.nodes must be an object" };
  if (!Array.isArray(graph.edges) || !graph.joins || typeof graph.joins !== "object" || Array.isArray(graph.joins)) return { state: "malformed", message: "graph edges and joins are required" };

  const dependencies = Object.fromEntries(Object.keys(graph.nodes).map((id) => [id, []]));
  for (const edge of graph.edges) {
    if (!edge || !dependencies[edge.to] || !dependencies[edge.from]) return { state: "malformed", message: "graph edge references an unknown node" };
    dependencies[edge.to].push(edge.from);
  }
  for (const [id, join] of Object.entries(graph.joins)) {
    if (!dependencies[id] || !join || !Array.isArray(join.inputs)) return { state: "malformed", message: "graph join is invalid" };
    if (join.inputs.some((input) => !dependencies[input])) return { state: "malformed", message: "graph join references an unknown node" };
    dependencies[id].push(...join.inputs);
  }
  try {
    return {
      state: "ready",
      nodes: Object.entries(graph.nodes).map(([id, node]) => {
      if (!node || typeof node !== "object") throw new Error(`graph node ${id} is invalid`);
      const join = graph.joins[id];
      const required = [...new Set(dependencies[id])];
      return {
        id,
        name: node.name || id,
        dependencies: required,
        join: join ? { mode: join.mode, released: join.released } : null,
        readiness: node.status === "running" ? "active" : node.status === "pending" && required.every((dependency) => ["done", "skipped"].includes(graph.nodes[dependency].outcome)) ? "ready" : "waiting",
        outcome: node.outcome || node.status || "unknown",
        retries: { attempts: node.retry?.attempts ?? 0, max: node.retry?.max ?? 0 },
        prompt: node.prompt == null ? null : maskValue(node.prompt),
        activity: maskValue(namedList(node, id, "activity")),
        checks: maskValue(namedList(node, id, "checks")),
        outputs: maskValue(namedList(node, id, "outputs")),
        attempts: maskValue(namedList(node, id, "attempts")),
      };
      }),
    };
  } catch (error) {
    return { state: "malformed", message: error.message };
  }
}
import { maskValue } from "./evidence.mjs";
