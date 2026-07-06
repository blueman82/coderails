import esbuild from "esbuild";
import builtins from "builtin-modules";

// Reproducibility: no banner/footer timestamps, no sourcemap (which would
// embed absolute build-machine paths), fixed target — same input always
// produces the same dist/main.js bytes.
await esbuild.build({
  entryPoints: ["src/main.ts"],
  bundle: true,
  external: ["obsidian", "electron", ...builtins],
  format: "cjs",
  target: "es2020",
  platform: "node",
  sourcemap: false,
  treeShaking: true,
  outfile: "dist/main.js",
});
