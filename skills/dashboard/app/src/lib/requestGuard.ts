// Shared localhost Origin/Host wall for API routes that must never be
// reachable from a hostile browser tab (cross-origin fetch, DNS rebinding).
// Extracted from the /api/run route so /api/events can apply the identical
// check without duplicating it.

// Strips IPv6 brackets if present: "[::1]" → "::1". Both `new
// URL(...).hostname` ("http://[::1]:3000" → "[::1]", brackets KEPT — this is
// not obvious and was the source of a bug: only `URL.host`/`URL.port`
// separate them, `.hostname` does not) and a raw Host header
// ("[::1]:3000") carry brackets around an IPv6 literal, so both call this
// before comparing against isLocalhost.
function stripIpv6Brackets(hostname: string): string {
  if (hostname.startsWith("[") && hostname.endsWith("]")) {
    return hostname.slice(1, -1);
  }
  return hostname;
}

function isLocalhost(hostname: string): boolean {
  const stripped = stripIpv6Brackets(hostname);
  return stripped === "localhost" || stripped === "127.0.0.1" || stripped === "::1";
}

// LAN opt-in: when DASHBOARD_HOST is set, that ONE exact host is additionally
// allowed alongside loopback — never "any non-loopback host". Read fresh on
// every call (matches this app's existing direct process.env.* read style,
// e.g. build/spawn.ts) rather than cached at module load, so tests can flip
// it per-case. Unset/empty means "no LAN host configured" — behaviour is then
// identical to isLocalhost alone, the safe default.
function isAllowedHost(hostname: string): boolean {
  if (isLocalhost(hostname)) return true;
  const lanHost = process.env.DASHBOARD_HOST;
  if (!lanHost) return false;
  return stripIpv6Brackets(hostname) === lanHost;
}

// Host: "[::1]:3000" → "[::1]" (port dropped, brackets kept — isLocalhost
// strips them). Host: "127.0.0.1:3000" → "127.0.0.1".
function hostnameFromHostHeader(host: string): string {
  if (host.startsWith("[")) {
    const end = host.indexOf("]");
    return end === -1 ? host : host.slice(0, end + 1);
  }
  return host.split(":")[0];
}

// Any doubt → reject, with ONE deliberate exception: a request with no
// Origin header at all (as opposed to one present but invalid) is treated as
// a non-browser client (curl, a CLI, a same-machine script) rather than
// rejected — browsers always send Origin on a cross-origin fetch, so the
// absence of the header is not itself a spoofable signal, and Host is still
// required and validated. An Origin header that IS present but doesn't
// resolve to localhost (including the literal string "null", which browsers
// send for opaque/sandboxed origins) is rejected — any open browser tab can
// reach 127.0.0.1, so this is the wall against cross-origin/DNS-rebinding
// requests reaching the guarded endpoint.
export function isLocalOrigin(request: Request): boolean {
  const host = request.headers.get("host");
  if (!host) return false;
  if (!isLocalhost(hostnameFromHostHeader(host))) return false;

  const origin = request.headers.get("origin");
  if (origin === null) return true;

  let originHost: string;
  try {
    originHost = new URL(origin).hostname;
  } catch {
    return false;
  }
  return isLocalhost(originHost);
}
