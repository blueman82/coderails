import { randomUUID } from "node:crypto";
import { execFileSync, spawn as spawnChild } from "node:child_process";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

const providerArgs = {
  codex: ["codex", ["exec", "--json", "--skip-git-repo-check"]],
  claude: ["claude", ["-p", "--output-format", "stream-json"]],
};

function materializePrompt(prompt) {
  return `You are running headlessly from Coderails Factory. Before any work, invoke the installed native Coderails agentic-loop skill. The native loop owns the graph, all work, progress.json, dispatch, gates, scripts, and evidence; Factory only observes it. Create or resume that native graph and carry the task through its required checks.\n\nUser task:\n${prompt}`;
}

function providerSessionId(line) {
  try {
    const event = JSON.parse(line);
    for (const key of ["session_id", "sessionId", "thread_id", "threadId"]) {
      if (typeof event[key] === "string" && event[key]) return event[key];
    }
  } catch {}
  return null;
}

function defaultGitCommonDir(cwd) {
  return execFileSync("git", ["-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" }).trim();
}

function progressPath(loopRoot, gitCommonDir, sessionId) {
  return join(loopRoot, gitCommonDir.replaceAll("/", "-"), sessionId.replaceAll("/", "_").replaceAll("..", ""), "progress.json");
}

export function createLauncher({ store, projects, createId = randomUUID, now = () => new Date().toISOString(), spawn = spawnChild, readProgress = readFile, gitCommonDir = defaultGitCommonDir, loopRoot = process.env.CODERAILS_AGENTIC_LOOP_DIR ?? join(homedir(), ".coderails", "agentic-loop"), refreshMs = 500 }) {
  function append(runId, order, type, payload) {
    store.appendEvidence({ runId, order, type, source: "provider", timestamp: now(), payload });
  }

  return {
    store,
    launch({ projectId, provider, prompt }) {
      const project = projects.get(projectId);
      if (!project) throw new Error("unknown project");
      const command = providerArgs[provider];
      if (!command) throw new Error("unknown provider");
      if (typeof prompt !== "string" || prompt.length === 0) throw new Error("invalid prompt");

      const runId = createId();
      store.create({ id: runId, projectId, provider, prompt });
      const [program, fixedArgs] = command;
      let order = 0;
      let failed = false;
      let child;
      try {
        child = spawn(program, [...fixedArgs, materializePrompt(prompt)], { cwd: project.cwd, shell: false, stdio: ["ignore", "pipe", "pipe"] });
      } catch (error) {
        store.setStatus(runId, "failed");
        append(runId, ++order, "provider_spawn_error", error instanceof Error ? error.message : String(error));
        return { runId, status: "failed" };
      }
      store.setStatus(runId, "running");
      let progressTimer;
      let observedSessionId;
      const observeProgress = async () => {
        if (!observedSessionId) return;
        try {
          const state = await readProgress(progressPath(loopRoot, gitCommonDir(project.cwd), observedSessionId), "utf8");
          store.setProgress(runId, JSON.parse(state));
        } catch (error) {
          if (error?.code !== "ENOENT") append(runId, ++order, "progress_observation_error", error instanceof Error ? error.message : String(error));
        }
      };
      const discoverSession = (line) => {
        const sessionId = providerSessionId(line);
        if (!sessionId || observedSessionId) return;
        observedSessionId = sessionId;
        void observeProgress();
        progressTimer = setInterval(() => void observeProgress(), refreshMs);
        progressTimer.unref?.();
      };
      let stdoutBuffer = "";
      child.stdout?.on("data", (chunk) => {
        const text = String(chunk);
        append(runId, ++order, "provider_stdout", text);
        stdoutBuffer += text;
        const lines = stdoutBuffer.split("\n");
        stdoutBuffer = lines.pop();
        lines.forEach(discoverSession);
      });
      child.stderr?.on("data", (chunk) => append(runId, ++order, "provider_stderr", String(chunk)));
      child.once("error", (error) => {
        failed = true;
        store.setStatus(runId, "failed");
        append(runId, ++order, "provider_error", error instanceof Error ? error.message : String(error));
      });
      child.once("close", (code) => {
        clearInterval(progressTimer);
        void observeProgress();
        store.setStatus(runId, !failed && code === 0 ? "completed" : "failed");
      });
      return { runId, status: "running" };
    },
  };
}
