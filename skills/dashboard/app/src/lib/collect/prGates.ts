import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { DashboardConfig } from "../config";
import { readMarkerVersions } from "./markerVersions";

const execFileAsync = promisify(execFile);

export type GateState = "merge-ready" | "blocked" | "stale";

export interface PrGate {
  repo: string;
  number: number;
  title: string;
  headSha: string;
  review: "present" | "missing" | "stale";
  evals: "pass" | "fail" | "missing" | "stale";
  tier?: string;
  state: GateState;
}

export interface PrGateError {
  repo: string;
  error: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Matches a comment body against the eval-marker grammar for `pr`, at ANY
// result/tier, mirroring eval_artifact::matches_marker's literal-prefix
// approach (scripts/lib/eval-artifact.sh) — pr/headSha are compared via
// string equality inside the regex capture groups, never interpolated into
// the pattern itself, so a pr/sha containing regex metacharacters can't be
// misread as part of the pattern.
function matchEvalMarkers(
  body: string,
  version: string,
  pr: number
): { headSha: string; result: string; tier: string }[] {
  const escapedVersion = version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(
    `<!-- coderails-eval-summary ${escapedVersion} pr=(\\S+) head_sha=(\\S+) result=(GO|NO-GO) tier=(\\S+) -->`,
    "g"
  );
  const matches: { headSha: string; result: string; tier: string }[] = [];
  for (const m of body.matchAll(pattern)) {
    if (m[1] !== String(pr)) continue;
    matches.push({ headSha: m[2], result: m[3], tier: m[4] });
  }
  return matches;
}

// Mirrors review_artifact::matches_marker's exact-equality approach
// (scripts/lib/review-artifact.sh): match a whole marker string, not a
// substring grep, so junk prefix/suffix on the line fails to match.
function matchReviewMarkers(body: string, version: string, pr: number): { headSha: string }[] {
  const escapedVersion = version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pattern = new RegExp(
    `<!-- coderails-review-summary ${escapedVersion} pr=(\\S+) head_sha=(\\S+) -->`,
    "g"
  );
  const matches: { headSha: string }[] = [];
  for (const m of body.matchAll(pattern)) {
    if (m[1] !== String(pr)) continue;
    matches.push({ headSha: m[2] });
  }
  return matches;
}

// parseGates is pure: given the PR's JSON (as returned by `gh pr view --json
// number,title,headRefOid`) and its comments (as returned by `gh pr view
// --json comments`), derives the merge-gate state. Never throws — malformed
// input degrades to a missing/blocked gate.
export function parseGates(prJson: unknown, comments: unknown[]): PrGate {
  const pr = isRecord(prJson) ? prJson : {};
  const number = typeof pr.number === "number" ? pr.number : 0;
  const title = typeof pr.title === "string" ? pr.title : "";
  const headSha = typeof pr.headRefOid === "string" ? pr.headRefOid : "";

  const versions = readMarkerVersions();

  let newestEval: { headSha: string; result: string; tier: string } | undefined;
  let newestReview: { headSha: string } | undefined;

  for (const entry of comments) {
    if (!isRecord(entry)) continue;
    const body = typeof entry.body === "string" ? entry.body : "";
    if (!body) continue;

    if (versions.eval) {
      for (const match of matchEvalMarkers(body, versions.eval, number)) {
        // Later occurrence with a matching (current) SHA wins over an older
        // stale one; if none match the current head, keep the last seen so
        // staleness is still reported rather than silently dropped.
        if (!newestEval || match.headSha === headSha) newestEval = match;
      }
    }
    if (versions.review) {
      for (const match of matchReviewMarkers(body, versions.review, number)) {
        if (!newestReview || match.headSha === headSha) newestReview = match;
      }
    }
  }

  let review: PrGate["review"];
  if (!newestReview) {
    review = "missing";
  } else if (newestReview.headSha === headSha) {
    review = "present";
  } else {
    review = "stale";
  }

  let evals: PrGate["evals"];
  if (!newestEval) {
    evals = "missing";
  } else if (newestEval.headSha !== headSha) {
    evals = "stale";
  } else if (newestEval.result === "GO") {
    evals = "pass";
  } else {
    evals = "fail";
  }

  const state: GateState =
    review === "stale" || evals === "stale"
      ? "stale"
      : review === "present" && evals === "pass"
        ? "merge-ready"
        : "blocked";

  const gate: PrGate = { repo: "", number, title, headSha, review, evals, state };
  if (newestEval?.tier !== undefined) gate.tier = newestEval.tier;
  return gate;
}

async function fetchOpenPrGates(repo: string, env: NodeJS.ProcessEnv): Promise<PrGate[]> {
  const { stdout: listOut } = await execFileAsync(
    "gh",
    ["pr", "list", "--repo", repo, "--state", "open", "--json", "number"],
    { env }
  );
  const list: unknown = JSON.parse(listOut);
  const numbers = Array.isArray(list)
    ? list.filter(isRecord).map((p) => p.number).filter((n): n is number => typeof n === "number")
    : [];

  const gates: PrGate[] = [];
  for (const number of numbers) {
    const { stdout: viewOut } = await execFileAsync(
      "gh",
      [
        "pr",
        "view",
        String(number),
        "--repo",
        repo,
        "--json",
        "number,title,headRefOid,comments",
      ],
      { env }
    );
    const view: unknown = JSON.parse(viewOut);
    const comments = isRecord(view) && Array.isArray(view.comments) ? view.comments : [];
    const gate = parseGates(view, comments);
    gate.repo = repo;
    gates.push(gate);
  }
  return gates;
}

// collectPrGates shells out to `gh` via execFile (never a shell string) for
// each configured repo. A non-zero gh exit (auth failure, network error,
// unknown repo, ...) degrades that repo to a {repo, error} entry — this
// function never throws. `envOverride` is test-only: merged over
// process.env so a broken GH_TOKEN can be exercised without mutating the
// real environment.
export function collectPrGates(
  cfg: DashboardConfig,
  envOverride?: NodeJS.ProcessEnv
): Promise<(PrGate | PrGateError)[]> {
  const env = envOverride ? { ...process.env, ...envOverride } : process.env;
  return Promise.all(
    cfg.repos.map(async (repo): Promise<(PrGate | PrGateError)[]> => {
      try {
        return await fetchOpenPrGates(repo, env);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        return [{ repo, error: message }];
      }
    })
  ).then((perRepo) => perRepo.flat());
}
