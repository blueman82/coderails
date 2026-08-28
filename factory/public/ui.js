export function selectedNodeId(graph) {
  if (graph?.state !== "ready") return null;
  return graph.nodes.find((node) => node.outcome === "running" || node.ready)?.id ?? graph.nodes[0]?.id ?? null;
}

export function moveSelectedNode(graph, id, key) {
  const nodes = graph?.state === "ready" ? graph.nodes : [];
  const index = nodes.findIndex((node) => node.id === id);
  if (index < 0 || !["ArrowLeft", "ArrowRight"].includes(key)) return id;
  return nodes[(index + (key === "ArrowRight" ? 1 : nodes.length - 1)) % nodes.length].id;
}

export function nodeSelector(id) {
  return `[data-node-id="${id}"]`;
}

export function inspectorNode(graph, id) {
  return graph?.state === "ready" ? graph.nodes.find((node) => node.id === id) ?? null : null;
}

export function shouldShowInspector(graph, id, open) {
  return open && inspectorNode(graph, id) !== null;
}

export function inspectorSections(node) {
  const activity = [...node.activity].sort((left, right) => left.at.localeCompare(right.at));
  return [
    ["Dependencies", node.dependencies.join(", ") || "None"],
    ["Join", node.join ? `${node.join.mode} · ${node.join.released ? "released" : "waiting"}` : "None"],
    ["Readiness", node.readiness],
    ["Outcome", node.outcome],
    ["Retries", `${node.retries.attempts}/${node.retries.max}`],
    ["Prompt", node.prompt ?? "Unavailable"],
    ["Activity", activity.length ? activity.map((item) => `${item.at.slice(11, 19)} ${item.message}`).join("\n") : "No activity"],
    ["Checks", node.checks.length ? node.checks.map((item) => `${item.name}: ${item.outcome}`).join("\n") : "No checks"],
    ["Outputs", node.outputs.length ? node.outputs.map((item) => `${item.name}: ${item.value}`).join("\n") : "No outputs"],
    ["Attempt history", node.attempts.length ? node.attempts.map((item) => `#${item.number} ${item.outcome}: ${item.summary}`).join("\n") : "No attempts"],
  ];
}

export function cycleTheme(theme) {
  return theme === "system" ? "light" : theme === "light" ? "dark" : "system";
}

export function activityLines(evidence) {
  return evidence.length
    ? [...evidence].sort((left, right) => left.timestamp.localeCompare(right.timestamp) || left.order - right.order).map((item) => `${item.timestamp.slice(11, 19)} ${item.source} ${item.type}: ${item.payload}`)
    : ["Waiting for Factory activity…"];
}
