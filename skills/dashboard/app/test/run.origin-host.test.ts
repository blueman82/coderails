import { TOKEN, makeHandler, req, reqNoOrigin } from "./run.fixture";
import { describe, it, expect } from "vitest";

describe("POST /api/run — origin/host", () => {
  it("rejects a non-localhost Origin with 403 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { origin: "https://evil.example" })
    );
    expect(res.status).toBe(403);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects a non-localhost Host with 403 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { host: "evil.example", origin: "http://evil.example" })
    );
    expect(res.status).toBe(403);
    expect(fake!.calls.length).toBe(0);
  });

  it("accepts an http://localhost origin", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { origin: "http://localhost:3000", host: "localhost:3000" })
    );
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });

  it("accepts a request with NO Origin header at all (non-browser client), provided Host is localhost", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(reqNoOrigin({ token: TOKEN, button: "wiki-lint" }, "127.0.0.1:3000"));
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });

  it("rejects an Origin header literally 'null' even though Host is localhost", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }, { origin: "null" }));
    expect(res.status).toBe(403);
    expect(fake!.calls.length).toBe(0);
  });

  it("accepts a bracketed IPv6 Host [::1] consistently with an IPv6 Origin", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { origin: "http://[::1]:3000", host: "[::1]:3000" })
    );
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });
});
