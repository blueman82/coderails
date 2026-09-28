import { TOKEN, makeHandler, req } from "./run.fixture";
import { describe, it, expect } from "vitest";

describe("POST /api/run — button validation", () => {
  it("rejects an undeclared button name with 404 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "does-not-exist" }));
    expect(res.status).toBe(404);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects input on a button without inputAllowed with 400 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "wiki-lint", input: "hello" }));
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });

  it("accepts input on a button with inputAllowed", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "with-input", input: "hello" }));
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });

  it("rejects input starting with '-' (flag smuggling) with 400 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "with-input", input: "--dangerously-skip-permissions" })
    );
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects an empty-command button pressed with no input (empty prompt) with a clean 400, not a 500, and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "ask" }));
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects an empty-command button pressed with empty-string input (empty prompt) with a clean 400, not a 500, and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "ask", input: "" }));
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });
});
