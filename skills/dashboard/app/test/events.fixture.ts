import { afterEach, vi } from "vitest";

import { mkdtempSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import type { DashboardConfig } from "../src/lib/config";

import * as prGatesModule from "../src/lib/collect/prGates";

// Wraps the real collectPrGates so the "gates freshness" tests below can
// assert on call *count* (did stop() actually suppress a pending debounced
// refresh?) without changing what it returns — every other test in this file
// still exercises the real (empty-repos, so fast+empty) implementation.
vi.mock("../src/lib/collect/prGates", async () => {
  const actual = await vi.importActual<typeof prGatesModule>("../src/lib/collect/prGates");
  return { ...actual, collectPrGates: vi.fn(actual.collectPrGates) };
});

const tmpDirs: string[] = [];

function tmpDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function testConfig(): DashboardConfig {
  return {
    repos: [],
    wikiPaths: [],
    buttons: [],
  };
}

function req(headers: Record<string, string> = {}): Request {
  return new Request("http://127.0.0.1:3000/api/events", {
    headers: {
      origin: "http://127.0.0.1:3000",
      host: "127.0.0.1:3000",
      ...headers,
    },
  });
}

// Reads named SSE frames off a ReadableStream<Uint8Array> body, splitting on
// the blank-line frame terminator. Returns { event, data } pairs as they
// arrive; stops once `stop(frames)` returns true or the stream ends.
async function readFramesUntil(
  body: ReadableStream<Uint8Array>,
  stop: (frames: { event: string; data: unknown }[]) => boolean
): Promise<{ event: string; data: unknown }[]> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const frames: { event: string; data: unknown }[] = [];

  while (!stop(frames)) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const eventLine = raw.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = raw.split("\n").find((l) => l.startsWith("data: "));
      if (eventLine && dataLine) {
        frames.push({
          event: eventLine.slice("event: ".length),
          data: JSON.parse(dataLine.slice("data: ".length)),
        });
      }
      if (stop(frames)) break;
    }
  }
  await reader.cancel();
  return frames;
}

// Reads exactly `count` frames regardless of event name.
function readFrames(body: ReadableStream<Uint8Array>, count: number) {
  return readFramesUntil(body, (frames) => frames.length >= count);
}

// Like readFramesUntil, but keeps reading for `extraMs` past the point
// `stop(frames)` first becomes true, to catch a straggler frame that arrives
// shortly after the condition is met (e.g. an incorrectly un-debounced
// second refresh). Uses a single reader for the whole window.
async function readFramesUntilPlus(
  body: ReadableStream<Uint8Array>,
  stop: (frames: { event: string; data: unknown }[]) => boolean,
  extraMs: number
): Promise<{ event: string; data: unknown }[]> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const frames: { event: string; data: unknown }[] = [];
  let deadline: number | undefined;

  while (true) {
    if (deadline !== undefined && Date.now() >= deadline) break;
    const readPromise = reader.read();
    const remaining = deadline !== undefined ? deadline - Date.now() : undefined;
    const raced =
      remaining !== undefined
        ? await Promise.race([readPromise, new Promise<{ done: true; value: undefined }>((r) => setTimeout(() => r({ done: true, value: undefined }), remaining))])
        : await readPromise;
    if (raced.done) break;
    buffer += decoder.decode(raced.value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const eventLine = raw.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = raw.split("\n").find((l) => l.startsWith("data: "));
      if (eventLine && dataLine) {
        frames.push({
          event: eventLine.slice("event: ".length),
          data: JSON.parse(dataLine.slice("data: ".length)),
        });
      }
    }
    if (deadline === undefined && stop(frames)) {
      deadline = Date.now() + extraMs;
    }
  }
  await reader.cancel();
  return frames;
}

async function readRawText(body: ReadableStream<Uint8Array>, minBytes: number, timeoutMs: number): Promise<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  const deadline = Date.now() + timeoutMs;
  while (text.length < minBytes && Date.now() < deadline) {
    const { value, done } = await reader.read();
    if (done) break;
    text += decoder.decode(value, { stream: true });
  }
  await reader.cancel();
  return text;
}

export { tmpDir, testConfig, req, readFramesUntil, readFrames, readFramesUntilPlus, readRawText };
