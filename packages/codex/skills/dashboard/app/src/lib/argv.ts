import type { ButtonDef } from "./config";

function profileFlags(profile: ButtonDef["profile"]): string[] {
  if (profile === "auto") {
    return ["--sandbox", "workspace-write", "-c", "sandbox_workspace_write.network_access=false"];
  }
  return ["--sandbox", "read-only"];
}

export const NON_INTERACTIVE_FRAMING =
  "This is an unattended, headless run with no human watching output in real time. " +
  "Do not address a human or end your final text with a question. " +
  "Write findings only to whatever report or artifact file the invoked skill specifies.";

export function withExecSubcommand(argv: readonly string[]): string[] {
  return argv[0] === "exec" ? [...argv] : ["exec", ...argv];
}

export function buildArgv(btn: ButtonDef, rawInput?: string): string[] {
  const input = rawInput !== undefined && rawInput.trim() === "" ? undefined : rawInput;
  if (input?.trim().startsWith("-")) {
    throw new Error(`buildArgv: input must not start with '-' (got: ${input})`);
  }

  const command = btn.command.trim();
  const prompt = input === undefined ? command : command ? `${command} ${input}` : input;
  if (!prompt) {
    throw new Error("buildArgv: refusing to spawn an empty prompt (no command and no input)");
  }

  const framedPrompt = `${NON_INTERACTIVE_FRAMING} ${prompt}`;
  const flags = profileFlags(btn.profile);
  return input === undefined ? [...flags, framedPrompt] : [...flags, "--", framedPrompt];
}
