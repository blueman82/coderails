import { randomUUID } from "node:crypto";
import { spawn as spawnChild } from "node:child_process";

const providerArgs = {
  codex: ["codex", ["exec", "--json", "--skip-git-repo-check"]],
  claude: ["claude", ["-p", "--output-format", "stream-json"]],
};

export function createLauncher({ store, projects, createId = randomUUID, now = () => new Date().toISOString(), spawn = spawnChild }) {
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
        child = spawn(program, [...fixedArgs, prompt], { cwd: project.cwd, shell: false, stdio: ["ignore", "pipe", "pipe"] });
      } catch (error) {
        store.setStatus(runId, "failed");
        append(runId, ++order, "provider_spawn_error", error instanceof Error ? error.message : String(error));
        return { runId, status: "failed" };
      }
      store.setStatus(runId, "running");
      child.stdout?.on("data", (chunk) => append(runId, ++order, "provider_stdout", String(chunk)));
      child.stderr?.on("data", (chunk) => append(runId, ++order, "provider_stderr", String(chunk)));
      child.once("error", (error) => {
        failed = true;
        store.setStatus(runId, "failed");
        append(runId, ++order, "provider_error", error instanceof Error ? error.message : String(error));
      });
      child.once("close", (code) => store.setStatus(runId, !failed && code === 0 ? "completed" : "failed"));
      return { runId, status: "running" };
    },
  };
}
