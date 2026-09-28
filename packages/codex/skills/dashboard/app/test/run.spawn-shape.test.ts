import { TOKEN, makeHandler, req } from "./run.fixture";
import { describe, it, expect } from "vitest";
import { NON_INTERACTIVE_FRAMING } from "../src/lib/argv";

describe("POST /api/run — spawn shape", () => {
  it("calls spawn with 'codex' and an argv ARRAY (never a string)", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(fake!.calls.length).toBe(1);
    expect(fake!.calls[0].command).toBe("codex");
    const args = fake!.calls[0].args as string[];
    expect(Array.isArray(args)).toBe(true);
    expect(args.slice(0, 2)).toEqual(["exec", "--json"]);
    expect(args.filter((arg) => arg === "exec")).toHaveLength(1);
  });

  it("passes the button's cwd to spawn's options", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(fake!.calls[0].options).toMatchObject({ cwd: "/tmp/coderails" });
  });

  it("sets CODERAILS_HEADLESS_RUN=1 in the spawned child's env, so the discipline\n     Stop hooks (check_confidence_labels.sh / check_verify_loop.sh) exempt this run", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    const options = fake!.calls[0].options as { env?: Record<string, string | undefined> };
    expect(options.env).toMatchObject({ CODERAILS_HEADLESS_RUN: "1" });
  });

  it("builds argv via buildArgv's mapping (read-only button gets the native sandbox)", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "with-input", input: "hello" }));
    const args = fake!.calls[0].args as string[];
    expect(args).toContain("--sandbox");
    expect(args).toContain("read-only");
    expect(args[args.length - 1]).toBe(`${NON_INTERACTIVE_FRAMING} $coderails-codex:assumptions hello`);
  });
});
