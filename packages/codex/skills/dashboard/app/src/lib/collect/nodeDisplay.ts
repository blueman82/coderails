export type NodeDisplay = { jobName: string; laneCode: string | null; display: string };

const FIXED_NAMES: Record<string, string> = {
  "S-2": "Initializer", "S-1": "Editor", S0: "Authorizer", "S0.4": "Accountant", "S0.5": "Steward",
  S1: "Planner", S2: "Scout", "S2.5": "Designer", "S2.6": "Decider", J2: "Joiner",
  "S2.7a": "Specifier", "S2.7b": "Planner", "S2.7c": "Grader", "S2.7e": "Prover", "S2.8": "Router",
  "J2.8": "Gatekeeper", "J12-all-units": "Joiner", G10: "Guardian", G11: "Linter", G12: "Verifier",
  "S9-wiki": "Archivist", "S9-docs": "Editor", "S13-proof": "Prover", "S13-retro": "Reporter", "S13-complete": "Closer",
};

const ACTION_NAMES: Record<string, string> = {
  "3": "Builder", "4": "Verifier", "4b-review": "Reviewer", "5": "Investigator",
  "5-repair": "Repairer", "6": "Resolver", "7/8": "Publisher", "4b-merge-gate": "Gatekeeper",
  "10-respawn": "Respawner",
};

function fixedName(nodeId: string): string | undefined { return FIXED_NAMES[nodeId]; }

function laneCode(unit: number): string | null {
  if (unit >= 1 && unit <= 6) return `A-${unit}`;
  if (unit >= 7 && unit <= 12) return `B-${unit - 6}`;
  if (unit >= 13 && unit <= 18) return `C-${unit - 12}`;
  if (unit >= 19 && unit <= 24) return `D-${unit - 18}`;
  return ({ 25: "I-1", 26: "F-1", 27: "F-2", 28: "L-1", 29: "G-1", 30: "R-1", 31: "O-1", 32: "V-1", 33: "H-1" } as Record<number, string>)[unit] ?? null;
}

export function describeNode(nodeId: string): NodeDisplay | null {
  const unit = /^(?:U3|S2\.7d)\[([1-9][0-9]*)\]$/.exec(nodeId);
  const role = /^U(3|4|4b-review|5|5-repair|6|7\/8|4b-merge-gate|10-respawn)\[[1-9][0-9]*\]$/.exec(nodeId);
  const freezer = /^S2\.7d\[[1-9][0-9]*\]$/.test(nodeId);
  const jobName = fixedName(nodeId) ?? (freezer ? "Freezer" : role ? ACTION_NAMES[role[1]] : undefined);
  if (!jobName) return null;
  const code = unit ? laneCode(Number(unit[1])) : null;
  return { jobName, laneCode: code, display: `${jobName}${code ? ` · ${code}` : ""} [${nodeId}]` };
}

export function nodeAttributes(nodeId: string): Record<string, string> {
  const node = describeNode(nodeId);
  return {
    "coderails.node.id": nodeId,
    ...(node ? { "coderails.node.name": node.jobName } : {}),
    ...(node?.laneCode ? { "coderails.node.lane_code": node.laneCode } : {}),
  };
}
