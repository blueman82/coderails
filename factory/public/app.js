import { activityLines, cycleTheme, inspectorNode, inspectorSections, moveSelectedNode, nodeSelector, selectedNodeId, shouldShowInspector } from "/ui.js";

const form = document.querySelector(".launch-bar");
const queue = document.querySelector(".run-list");
const map = document.querySelector(".workflow-map");
const activity = document.querySelector(".activity");
const inspector = document.querySelector(".inspector");
const themeButton = document.querySelector(".theme-toggle");
let snapshot = { runs: [] };
let nodeId = null;
let lastNodeId = null;
let inspectorOpen = false;
let theme = localStorage.getItem("factory-theme") ?? "system";

function text(element, value) { element.textContent = value; return element; }
function code(value) { const pre = document.createElement("pre"); text(pre, value); return pre; }
function applyTheme() {
  document.documentElement.dataset.theme = theme;
  themeButton.textContent = `${theme[0].toUpperCase()}${theme.slice(1)} theme`;
}
function renderInspector(run) {
  inspector.replaceChildren();
  const node = shouldShowInspector(run?.graph, nodeId, inspectorOpen) ? inspectorNode(run?.graph, nodeId) : null;
  const eyebrow = document.createElement("p"); eyebrow.className = "eyebrow"; text(eyebrow, "INSPECTOR"); inspector.append(eyebrow);
  if (!run || !node) { inspector.append(text(document.createElement("h2"), "No node selected")); return; }
  const close = document.createElement("button"); close.className = "close"; close.type = "button"; text(close, "Close inspector");
  close.addEventListener("click", () => { inspectorOpen = false; render(snapshot); map.querySelector(nodeSelector(lastNodeId))?.focus(); });
  inspector.append(close, text(document.createElement("h2"), `${node.name} · ${node.outcome}`));
  inspectorSections(node).forEach(([name, value]) => {
    const section = document.createElement("section");
    section.append(text(document.createElement("h3"), name), code(value));
    inspector.append(section);
  });
}
function render(next) {
  snapshot = next;
  const run = snapshot.selectedRun;
  queue.replaceChildren(...(snapshot.runs.length ? snapshot.runs.map((item) => {
    const button = document.createElement("button"); button.className = `run ${item.id === snapshot.selectedRunId ? "selected" : ""}`; text(button, `${item.projectId}\n${item.provider} · ${item.status}`);
    button.addEventListener("click", () => refresh(item.id)); return button;
  }) : [text(document.createElement("p"), "Nothing queued")]));
  text(document.querySelector("#project-label"), `Project: ${run?.projectId ?? "coderails"}`);
  text(document.querySelector("#provider-label"), `Provider: ${run?.provider ?? "Codex"}`);
  map.replaceChildren();
  if (run?.graph.state === "ready") {
    nodeId ??= selectedNodeId(run.graph);
    run.graph.nodes.forEach((node, index) => {
      if (index) map.append(text(document.createElement("span"), "→"));
      const button = document.createElement("button"); button.className = `node ${node.outcome === "done" ? "done" : ""} ${node.outcome === "running" ? "live" : ""}`; button.type = "button"; button.dataset.nodeId = node.id; button.setAttribute("aria-pressed", String(nodeId === node.id)); text(button, `${node.name} ${node.outcome === "done" ? "✓" : node.outcome === "running" ? "●" : ""}`);
      const select = () => { nodeId = node.id; inspectorOpen = true; lastNodeId = node.id; render(snapshot); map.querySelector(nodeSelector(node.id))?.focus(); };
      button.addEventListener("click", select);
      button.addEventListener("keydown", (event) => {
        if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
          event.preventDefault();
          nodeId = moveSelectedNode(run.graph, node.id, event.key); inspectorOpen = true;
          lastNodeId = nodeId;
          render(snapshot);
          map.querySelector(nodeSelector(nodeId))?.focus();
        }
      });
      button.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
      map.append(button);
    });
  } else text(map, run?.graph.message ?? "No workflow loaded");
  text(activity, activityLines(run?.evidence ?? []).join("\n"));
  renderInspector(run);
}
async function refresh(runId) {
  const response = await fetch(`/api/snapshot${runId ? `?run=${encodeURIComponent(runId)}` : ""}`);
  if (!response.ok) throw new Error("Factory is unavailable");
  render(await response.json());
}
form.addEventListener("submit", async (event) => {
  event.preventDefault(); const values = Object.fromEntries(new FormData(form));
  const response = await fetch("/api/runs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(values) });
  if (!response.ok) { text(activity, "Run was not started."); return; }
  form.reset(); await refresh((await response.json()).runId);
});
themeButton.addEventListener("click", () => { theme = cycleTheme(theme); localStorage.setItem("factory-theme", theme); applyTheme(); });
applyTheme(); refresh().catch(() => text(queue, "Factory is loading"));
const events = new EventSource("/api/events");
["evidence", "status", "graph"].forEach((type) => events.addEventListener(type, () => refresh(snapshot.selectedRunId).catch(() => {})));
