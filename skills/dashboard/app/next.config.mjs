/** @type {import('next').NextConfig} */
const nextConfig = {
  // The dashboard is always served on loopback; the spec binds 127.0.0.1 while Next's dev
  // server treats that host as cross-origin for its own dev resources (chunk/HMR loads were
  // blocked, silently stalling client-component hydration — no canvas, no error).
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // NOTE: do NOT pin turbopack.root here — pinning it to the app dir breaks Next's builtin
  // client-manifest resolution (global-error.js 500s). The workspace-root inference warning
  // is caused by a stray lockfile at ~/Github/package-lock.json, outside this repo.
};

export default nextConfig;
