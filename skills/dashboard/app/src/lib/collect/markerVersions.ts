import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";

// The eval/review artifact marker grammar's version token ("v1" today) is
// upstream SSOT in scripts/lib/{eval,review}-artifact.sh — read it from there
// rather than retyping the literal here, so this module can never drift from
// the shell writer/reader. See scripts/lib/eval-artifact.sh's
// EVAL_ARTIFACT_MARKER_VERSION and review-artifact.sh's
// REVIEW_ARTIFACT_MARKER_VERSION.

const MAX_ANCESTORS = 10;

// Walks upward from `from` looking for a directory containing scripts/lib/,
// i.e. the coderails repo root. Returns undefined if not found within
// MAX_ANCESTORS levels (fail-open — callers degrade rather than throw).
function findRepoRoot(from: string): string | undefined {
  let dir = from;
  for (let i = 0; i < MAX_ANCESTORS; i++) {
    try {
      readFileSync(join(dir, "scripts", "lib", "eval-artifact.sh"), "utf-8");
      return dir;
    } catch {
      // keep walking up
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return undefined;
}

function extractVersion(fileText: string, constName: string): string | undefined {
  const pattern = new RegExp(`^${constName}="([^"]+)"`, "m");
  const match = fileText.match(pattern);
  return match?.[1];
}

export interface MarkerVersions {
  eval: string | undefined;
  review: string | undefined;
}

// Reads both marker-version tokens from the shell libs. Returns undefined
// fields (never throws) when the repo root or a lib file can't be found —
// callers treat undefined as "no version can match" rather than crashing.
export function readMarkerVersions(startDir: string = __dirname): MarkerVersions {
  const root = findRepoRoot(startDir);
  if (!root) return { eval: undefined, review: undefined };

  let evalText: string | undefined;
  let reviewText: string | undefined;
  try {
    evalText = readFileSync(join(root, "scripts", "lib", "eval-artifact.sh"), "utf-8");
  } catch {
    evalText = undefined;
  }
  try {
    reviewText = readFileSync(join(root, "scripts", "lib", "review-artifact.sh"), "utf-8");
  } catch {
    reviewText = undefined;
  }

  return {
    eval: evalText ? extractVersion(evalText, "EVAL_ARTIFACT_MARKER_VERSION") : undefined,
    review: reviewText ? extractVersion(reviewText, "REVIEW_ARTIFACT_MARKER_VERSION") : undefined,
  };
}
