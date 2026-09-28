

import type { DashboardSnapshot } from "../src/hooks/useDashboardState";

import type { QueueEntry } from "../src/lib/collect/queue";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return {
    sessions: [],
    loops: [],
    gates: [],
    health: [],
    runs: [],
    queue: [],
    builds: [],
    contextTrend: null,
    ...overrides,
  };
}

function pendingEntry(overrides: Partial<QueueEntry> = {}): QueueEntry {
  return {
    hash: "abc123",
    toolName: "mcp__codex_ai_Slack__slack_send_message",
    toolInput: { channel: "#general", text: "hello team" },
    createdAt: Date.now(),
    status: "pending",
    ...overrides,
  };
}

export { emptySnapshot, pendingEntry };
