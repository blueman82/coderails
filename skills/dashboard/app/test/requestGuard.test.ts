import { describe, it, expect, afterEach } from "vitest";
import { isLocalOrigin } from "../src/lib/requestGuard";

function req(headers: Record<string, string>): Request {
  return new Request("http://example.invalid/api/events", { headers });
}

afterEach(() => {
  delete process.env.DASHBOARD_HOST;
});

describe("isLocalOrigin — default mode (DASHBOARD_HOST unset)", () => {
  it("accepts loopback host with matching origin", () => {
    expect(isLocalOrigin(req({ host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" }))).toBe(true);
  });

  it("rejects an arbitrary host", () => {
    expect(isLocalOrigin(req({ host: "evil.com" }))).toBe(false);
  });

  it("rejects a LAN host even though it looks plausible", () => {
    expect(isLocalOrigin(req({ host: "192.168.50.140:3000" }))).toBe(false);
  });
});

describe("isLocalOrigin — LAN mode (DASHBOARD_HOST set)", () => {
  it("accepts Host+Origin matching the configured LAN host", () => {
    process.env.DASHBOARD_HOST = "192.168.50.140";
    expect(
      isLocalOrigin(req({ host: "192.168.50.140:4199", origin: "http://192.168.50.140:4199" }))
    ).toBe(true);
  });

  it("still accepts loopback", () => {
    process.env.DASHBOARD_HOST = "192.168.50.140";
    expect(isLocalOrigin(req({ host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" }))).toBe(true);
  });

  it("rejects an arbitrary Host even when DASHBOARD_HOST is set (DNS-rebinding defence)", () => {
    process.env.DASHBOARD_HOST = "192.168.50.140";
    expect(isLocalOrigin(req({ host: "evil.com" }))).toBe(false);
  });

  it("rejects a Host that merely contains the configured host as a substring", () => {
    process.env.DASHBOARD_HOST = "192.168.50.140";
    expect(isLocalOrigin(req({ host: "192.168.50.140.evil.com" }))).toBe(false);
  });

  it("rejects a present-but-mismatched Origin even with a matching Host (cross-origin)", () => {
    process.env.DASHBOARD_HOST = "192.168.50.140";
    expect(isLocalOrigin(req({ host: "192.168.50.140:4199", origin: "http://evil.com" }))).toBe(false);
  });

  it("rejects a different LAN host than the one configured", () => {
    process.env.DASHBOARD_HOST = "192.168.50.140";
    expect(isLocalOrigin(req({ host: "192.168.50.141:4199" }))).toBe(false);
  });
});
