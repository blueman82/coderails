import { fileURLToPath } from "node:url";

const defaultProjects = {
  coderails: { cwd: fileURLToPath(new URL("../../", import.meta.url)) },
};

export function createProjectRegistry(projects = defaultProjects) {
  const entries = new Map(Object.entries(projects));
  return {
    get(id) {
      return entries.get(id) ?? null;
    },
    list() {
      return [...entries.keys()];
    },
  };
}
