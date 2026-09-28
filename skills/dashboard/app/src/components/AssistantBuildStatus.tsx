import { formatRelativeAge } from "@/hooks/useDashboardState";
import type { BuildEntry } from "@/lib/collect/builds";

// Heartbeat staleness threshold: run_builder.py touches builds/<hash>/heartbeat
// every 30s (BUILDER_HEARTBEAT_SECS) while claude is running — 3 minutes of
// silence means the process died without writing a terminal state.
const HEARTBEAT_STALE_MS = 3 * 60 * 1000;

// Pure, exported so it's directly unit-testable without needing the
// component's mount effect to fire (this file's tests render via
// renderToStaticMarkup/SSR, where `now` is always null). `now` is the
// panel's own live clock, not a server-computed age: the builds dir's
// fs.watch only re-collects on a filesystem event, so a build that dies
// without writing a terminal state (SIGKILL, power loss — the one path that
// skips run_builder.py's EXIT trap) stops touching the heartbeat file and
// triggers no further event at all. Comparing the heartbeat's absolute mtime
// against the client's own ticking `now` is what lets "builder dead" keep
// advancing after the last real collect, instead of freezing at whatever
// staleness happened to be true the moment collection stopped. `now === null`
// (SSR, or before the mount effect resolves) is treated as "not yet known" —
// never stale — same convention as formatRelativeAge's null-`now` handling.
export function isHeartbeatStale(build: BuildEntry, now: number | null): boolean {
  return build.heartbeatAt !== undefined && now !== null && now - build.heartbeatAt > HEARTBEAT_STALE_MS;
}

// prUrl is builder-session-controlled data (state.json, read verbatim from
// run_builder.py's own `gh pr create` output — see builds.ts), not a value
// this dashboard itself generates. Rendered into an <a href>, an unvalidated
// scheme (javascript:, data:) would be a click-triggered XSS vector, so only
// an https: URL is ever linked; anything else falls back to the plain-text
// CTA, same as when prUrl is absent.
function safePrUrl(prUrl: string | undefined): string | undefined {
  if (!prUrl) return undefined;
  try {
    return new URL(prUrl).protocol === "https:" ? prUrl : undefined;
  } catch {
    return undefined;
  }
}

// Renders the build-state CTA for an approved workflow-audit:propose-skill
// queue entry, joined to its builds/<hash>/ sidecar by hash. When there's no
// build entry yet — the claim never landed on disk (e.g. L2-WU7 DEFECT A's
// wrapper_not_found), or this approved entry predates the builder pipeline —
// this renders an explicit "no build claimed" line rather than nothing, so
// the owner's genuine Approve click isn't followed by silence (L2-WU7
// DEFECT B).
// Human-readable elapsed time from a start epoch-ms against the client's
// live `now`. Returns "" when either input is unknown (SSR before mount, or
// a build with no startedAt) so the caller renders no elapsed fragment
// rather than "NaN" — same null-`now` convention as formatRelativeAge.
export function formatElapsed(startedAt: number | undefined, now: number | null): string {
  if (startedAt === undefined || now === null) return "";
  const totalSec = Math.max(0, Math.floor((now - startedAt) / 1000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return m > 0 ? `${m}m${s}s` : `${s}s`;
}

// Parses the trailing PR number out of a builder-written prUrl
// (…/pull/<n>). Returns undefined for any URL that doesn't end in a numeric
// pull path — so a malformed prUrl simply doesn't participate in the
// open-PR-set join rather than throwing.
function prNumberFromUrl(prUrl: string | undefined): number | undefined {
  if (!prUrl) return undefined;
  const m = /\/pull\/(\d+)(?:$|[/?#])/.exec(prUrl);
  if (!m) return undefined;
  const n = Number(m[1]);
  return Number.isInteger(n) ? n : undefined;
}

// openPrNumbers is the set of currently-open PR numbers the dashboard
// already collects (prGates lists only open PRs). It lets a pr_open build
// reconcile after the fact: if its PR is no longer in the open set, it was
// merged or closed, so the panel stops claiming "awaiting your merge" — the
// after-merge staleness the owner hit when a merge left the build showing a
// stale status.
//
// NULL means "the open-PR set is not trustworthy right now" — gates haven't
// loaded yet (they arrive via a separate, slower `gh pr list` fetch than the
// synchronous builds slice), the gate poll failed, or this build's repo
// degraded to an error entry. In every such case an actually-open PR would
// be ABSENT from an empty/partial set and falsely read as "resolved" — the
// exact stale-status class inverted. When null, the reconciliation is
// skipped and the build shows the plain "awaiting your merge" until a
// trustworthy set arrives.
export function renderBuildStatus(
  build: BuildEntry | undefined,
  now: number | null,
  openPrNumbers: ReadonlySet<number> | null
) {
  if (!build) {
    return (
      <div className="hud-build-status hud-build-failed">
        approved — no build claimed (see server)
      </div>
    );
  }
  if (build.state === "pr_open") {
    const prUrl = safePrUrl(build.prUrl);
    const prNumber = prNumberFromUrl(build.prUrl);
    // Only downgrade to "resolved" when the open-PR set is trustworthy
    // (non-null). A null set (gates unloaded/failed/degraded) leaves the
    // build showing "awaiting your merge" rather than a false "resolved".
    const resolved = openPrNumbers !== null && prNumber !== undefined && !openPrNumbers.has(prNumber);
    const label = resolved ? "PR resolved — merged or closed" : "PR open — awaiting your merge";
    return (
      <div className={`hud-build-status ${resolved ? "hud-build-resolved" : "hud-build-pr-open"}`}>
        {prUrl ? (
          <a href={prUrl} target="_blank" rel="noreferrer">
            {label}
          </a>
        ) : (
          label
        )}
      </div>
    );
  }
  if (build.state === "failed") {
    return (
      <div className="hud-build-status hud-build-failed">
        failed: {build.failureReason ?? "unknown"} — delete builds/{build.hash} to retry
      </div>
    );
  }
  if (build.state === "running") {
    const stale = isHeartbeatStale(build, now);
    const elapsed = formatElapsed(build.startedAt, now);
    const heartbeatAge =
      build.heartbeatAt !== undefined && now !== null ? formatRelativeAge(build.heartbeatAt, now) : "";
    const label = stale ? "builder dead" : build.phase ? `building · ${build.phase}` : "building";
    const detail = [elapsed, heartbeatAge ? `last active ${heartbeatAge}` : ""]
      .filter(Boolean)
      .join(" · ");
    return (
      <div className={`hud-build-status ${stale ? "hud-build-dead" : "hud-build-building"}`}>
        {label}
        {detail ? <span className="hud-build-detail"> {detail}</span> : null}
      </div>
    );
  }
  // claimed | queued
  return <div className="hud-build-status hud-build-building">building</div>;
}
