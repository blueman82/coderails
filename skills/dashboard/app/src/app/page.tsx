import "@/styles/hud.css";
import { getRunToken } from "@/lib/runlog";
import { loadConfig, visibleButtons } from "@/lib/config";
import { DashboardApp } from "@/components/DashboardApp";
import type { DeckButton } from "@/components/DashboardApp";

// Force per-request rendering. Without this, Next.js statically prerenders
// this page at build time (it has no params/searchParams/cookies access to
// opt out of static generation on its own) — baking the config's button
// declarations and run token into the production build. That means a
// production server would serve whatever buttons existed in
// ~/.claude/coderails-dashboard.json at `next build` time, forever, until
// the next rebuild — silently going stale (or empty) on every config edit.
export const dynamic = "force-dynamic";

// Server component: this is the ONLY place the run token and the config's button declarations
// are read. Both are handed to the client tree as props — never via any API/SSE payload — per
// runlog.ts's mintToken comment: an attacker who can only reach the HTTP API must not be able to
// recover the token. Buttons are narrowed to exactly the fields the client needs (name, label,
// profile, inputAllowed) — cwd/command never leave the server.
//
// getRunToken is imported from lib/runlog.ts, NOT from the api/run route module — importing a
// route.ts export into a Server Component risks landing in a second, independently-initialized
// module graph with its own copy of any module-scope cache (confirmed empirically on this
// machine: doing it that way made this page's embedded token never match what POST /api/run
// compared against, so every run 401'd). runlog.ts is a plain lib module both layers can safely
// share one instance of.
export default function Home() {
  const token = getRunToken();
  const config = loadConfig();
  const buttons: DeckButton[] = visibleButtons(config).map((b) => ({
    name: b.name,
    label: b.label,
    profile: b.profile,
    inputAllowed: b.inputAllowed ?? false,
  }));

  return <DashboardApp token={token} buttons={buttons} />;
}
