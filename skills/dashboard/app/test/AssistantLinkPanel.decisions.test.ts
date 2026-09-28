import { describe, it, expect, afterEach, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { postDecision, renderDecisionFeedback } from "../src/components/AssistantLinkPanel";

describe("AssistantLinkPanel", () => {

  // L2-WU7 DEFECT B: the POST /api/queue response's `build` field
  // ({claimed:true}|{alreadyClaimed:true}|{error:"invalid_name"|"wrapper_not_found"})
  // was previously discarded entirely by postDecision, which collapsed the
  // whole response down to {ok:true}|{ok:false,error}. These tests exercise
  // postDecision directly against a mocked global.fetch (vitest's "node"
  // environment has native fetch, no jsdom needed) to prove the richer
  // response shape is now threaded through rather than dropped.
  describe("postDecision (L2-WU7 DEFECT B: build field must be threaded through, not discarded)", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    function mockFetchOnce(body: unknown, status = 200) {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: status >= 200 && status < 300,
          status,
          json: async () => body,
        })
      );
    }

    it("returns build:{claimed:true} verbatim when the server reports a successful claim", async () => {
      mockFetchOnce({ hash: "h1", status: "approved", build: { claimed: true, runId: "abcd1234" } });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({
        ok: true,
        status: "approved",
        build: { claimed: true, runId: "abcd1234" },
      });
    });

    it("returns build:{error:'wrapper_not_found'} verbatim (the exact L2-WU7 DEFECT A server-side symptom) rather than silently succeeding", async () => {
      mockFetchOnce({ hash: "h1", status: "approved", build: { claimed: false, error: "wrapper_not_found" } });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({
        ok: true,
        status: "approved",
        build: { claimed: false, error: "wrapper_not_found" },
      });
    });

    it("returns build:{alreadyClaimed:true} verbatim", async () => {
      mockFetchOnce({ hash: "h1", status: "approved", build: { claimed: false, alreadyClaimed: true } });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({
        ok: true,
        status: "approved",
        build: { claimed: false, alreadyClaimed: true },
      });
    });

    it("returns ok:true with no build field for a denied decision (no build field in the response at all)", async () => {
      mockFetchOnce({ hash: "h1", status: "denied" });
      const result = await postDecision("t", "h1", "denied");
      expect(result).toEqual({ ok: true, status: "denied", build: undefined });
    });

    it("still returns ok:false with the server error on a non-2xx response (unchanged behavior)", async () => {
      mockFetchOnce({ error: "unknown queue entry" }, 404);
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "unknown queue entry" });
    });

    it("still returns ok:false with 'network error' when fetch itself rejects (unchanged behavior)", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "network error" });
    });

    it("returns a distinct 'malformed server response' (not 'network error') when a 2xx body fails to parse", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: true,
          status: 200,
          json: async () => {
            throw new SyntaxError("Unexpected token < in JSON");
          },
        })
      );
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "malformed server response" });
    });

    it("returns 'malformed server response' for a 2xx body whose status is off-contract, rather than fabricating an 'approved' the server never asserted", async () => {
      mockFetchOnce({ hash: "h1", status: "pending" });
      const result = await postDecision("t", "h1", "approved");
      expect(result).toEqual({ ok: false, error: "malformed server response" });
    });
  });

  // L2-WU7 DEFECT B: AssistantLinkPanel previously gave zero visible
  // feedback after an Approve/Deny click — success, failure, and reason
  // were all indistinguishable from "nothing happened yet". These exercise
  // renderDecisionFeedback (the pure function the panel now calls with the
  // per-hash outcome of postDecision) directly via SSR.
  describe("renderDecisionFeedback (L2-WU7 DEFECT B: panel must show the outcome, not stay silent)", () => {
    function renderFeedback(feedback: Parameters<typeof renderDecisionFeedback>[0]) {
      return renderToStaticMarkup(createElement("div", null, renderDecisionFeedback(feedback)));
    }

    it("renders nothing when there is no feedback yet (fresh row, never clicked)", () => {
      const html = renderFeedback(undefined);
      expect(html).toBe("<div></div>");
    });

    it("shows 'build claimed — starting…' when the response reports build.claimed=true", () => {
      const html = renderFeedback({ ok: true, status: "approved", build: { claimed: true, runId: "abcd1234" } });
      expect(html).toContain("build claimed");
      expect(html).toContain("starting");
    });

    it("shows the build error verbatim, visibly, when build.error is present (the exact L2-WU7 DEFECT A symptom: wrapper_not_found)", () => {
      const html = renderFeedback({
        ok: true,
        status: "approved",
        build: { claimed: false, error: "wrapper_not_found" },
      });
      expect(html).toContain("build failed to start");
      expect(html).toContain("wrapper_not_found");
    });

    it("shows the invalid_name build error verbatim too (not just wrapper_not_found)", () => {
      const html = renderFeedback({
        ok: true,
        status: "approved",
        build: { claimed: false, error: "invalid_name" },
      });
      expect(html).toContain("build failed to start");
      expect(html).toContain("invalid_name");
    });

    it("shows an 'already claimed' message when build.alreadyClaimed=true", () => {
      const html = renderFeedback({
        ok: true,
        status: "approved",
        build: { claimed: false, alreadyClaimed: true },
      });
      expect(html).toContain("already claimed");
    });

    it("shows a plain 'approved' confirmation when approved with no build field at all (non-workflow-audit entries never get a build field)", () => {
      const html = renderFeedback({ ok: true, status: "approved", build: undefined });
      expect(html).toContain(">approved<");
      expect(html).not.toContain("claimed");
    });

    it("shows a 'denied' confirmation for a denied decision, with no build-outcome language at all (negative control)", () => {
      const html = renderFeedback({ ok: true, status: "denied", build: undefined });
      expect(html).toContain(">denied<");
      expect(html).not.toContain("claimed");
      expect(html).not.toContain(">approved<");
    });

    it("shows the raw error message when the request itself failed (network/HTTP error, unchanged from prior error-surfacing behavior)", () => {
      const html = renderFeedback({ ok: false, error: "unknown queue entry" });
      expect(html).toContain("unknown queue entry");
    });
  });
});
