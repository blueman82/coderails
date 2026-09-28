import { TOKEN, makeHandler, req } from "./run.fixture";
import { describe, it, expect } from "vitest";

describe("POST /api/run — token", () => {
  it("rejects a missing token with 401 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ button: "wiki-lint" }));
    expect(res.status).toBe(401);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects a wrong token with 401 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: "wrong", button: "wiki-lint" }));
    expect(res.status).toBe(401);
    expect(fake!.calls.length).toBe(0);
  });

  it("never includes the token in a response body", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: "wrong", button: "wiki-lint" }));
    const text = await res.text();
    expect(text).not.toContain(TOKEN);
  });
});
