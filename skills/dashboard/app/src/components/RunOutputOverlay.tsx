"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { runResultLabel, formatDuration, formatHHMM } from "@/hooks/useDashboardState";
import type { RunRecord } from "@/lib/runlog";

export interface RunOutputOverlayProps {
  run: RunRecord;
  isLive: boolean;
  // Cleaned output text (prose for a live run, server-extracted prose for a settled one) — already
  // projected by the owner (OutputViewerPanel). undefined while a settled run's fetch is in flight.
  output: string | undefined;
  // A settled-fetch failure message, if the fetch failed. Mutually exclusive with a useful output.
  error?: string;
  onRetry?: () => void;
  onClose: () => void;
}

// In-page overlay ("framed window over the HUD") that renders a run's output as sanitized
// markdown. Replaces the retired inline <pre> viewer, which squished the same text into a small
// box below the history list. Rendered via a portal to document.body so its fixed backdrop covers
// the whole HUD regardless of where the history box sits in the layout. react-markdown is the
// sanitizer: it builds a React element tree and renders any raw HTML in the source as escaped
// text (no rehype-raw, no dangerouslySetInnerHTML) — run output is untrusted, so this is required.
export function RunOutputOverlay({ run, isLive, output, error, onRetry, onClose }: RunOutputOverlayProps) {
  const bodyRef = useRef<HTMLDivElement>(null);
  // Whether the live-stream auto-scroll is "pinned" to the bottom. Starts pinned; a user scroll
  // away from the bottom unpins it (so reading back through earlier output isn't yanked away),
  // and scrolling back to the bottom re-pins.
  const pinnedRef = useRef(true);

  // ESC closes. Bound on window (not the panel) so it works regardless of focus — a fresh overlay
  // hasn't necessarily moved focus into itself.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Auto-scroll to bottom as live output grows, but only while pinned. Keyed on `output` so each
  // appended chunk re-runs it; the settled (non-live) case never grows, so this is a no-op there.
  useEffect(() => {
    if (!isLive || !pinnedRef.current) return;
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [output, isLive]);

  function onBodyScroll() {
    const el = bodyRef.current;
    if (!el) return;
    // A 24px slack so "close enough to the bottom" still counts as pinned (sub-pixel scroll
    // rounding, and the last line's line-height).
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  const hasError = error !== undefined;
  const body = output ?? "";

  return createPortal(
    <div className="hud-overlay" role="dialog" aria-modal="true" aria-label={`Run output — ${run.button}`}>
      <div className="hud-overlay-backdrop" onClick={onClose} />
      <div className="hud-overlay-panel">
        <div className="hud-overlay-head">
          <span className="hud-overlay-title">{run.button.toUpperCase()}</span>
          <span className="hud-overlay-meta">
            {runResultLabel(run)} ·{" "}
            {run.endedAt ? formatDuration(run.startedAt, run.endedAt) : "…"} · {formatHHMM(run.startedAt)}
            {isLive ? " · Live" : ""}
          </span>
          <button type="button" className="hud-overlay-close" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="hud-overlay-body" ref={bodyRef} onScroll={onBodyScroll}>
          {hasError ? (
            <div className="hud-cmd-error">
              couldn&apos;t load output — {error}{" "}
              {onRetry && (
                <button type="button" onClick={onRetry}>
                  retry
                </button>
              )}
            </div>
          ) : body !== "" ? (
            <div className="hud-markdown">
              {/* img override: run output is untrusted, and a CommonMark image
                  (`![alt](url)`) renders a LIVE <img> whose GET fires on open with no click —
                  a tracking beacon / SSRF-from-the-viewer vector. A run-output viewer has no
                  legitimate use for remote images, so images render as their alt text (or
                  nothing) instead of a live element. This is a DIFFERENT pipeline stage from
                  raw-HTML escaping (which handles literal <img> tags in the source); both are
                  needed. Links are left as-is: defaultUrlTransform already inerts javascript:,
                  and following one is a visible, deliberate click. */}
              <ReactMarkdown components={{ img: (props) => <>{props.alt ?? ""}</> }}>{body}</ReactMarkdown>
            </div>
          ) : (
            <div className="hud-empty-state">{isLive ? "waiting for output…" : "no output"}</div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
