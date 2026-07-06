import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    // Mirrors tsconfig.json's "@/*" path alias — needed once a test imports
    // a module (like DashboardProvider.tsx) that itself uses "@/..." imports,
    // since ts-node/vitest doesn't read tsconfig paths on its own.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
  },
});
