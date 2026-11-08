function readable(value: unknown, namespaced = false): string | null {
  if (typeof value !== "string" || value.length > 40) return null;
  const parts = (namespaced ? value : value.replaceAll(" ", "-")).split(":");
  if (parts.length > 1 && (!namespaced || parts.length !== 2 ||
    !/^[A-Za-z][A-Za-z0-9_-]{0,31}$/.test(parts[0]))) return null;
  const part = parts.at(-1);
  if (!part || !/^[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+){0,3}$/.test(part)) return null;
  return part.split(/[-_]/).map((word) => word[0].toUpperCase() + word.slice(1)).join(" ");
}

export function actorDisplayName(nickname: unknown, job: unknown, role: unknown): string {
  return readable(nickname) ?? readable(job) ?? readable(role, true) ?? "Worker";
}

export function validActorDisplayName(value: unknown): value is string {
  return typeof value === "string" && value.length <= 40 &&
    /^[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+){0,3}$/.test(value);
}
