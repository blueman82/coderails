import "@/styles/hud.css";
import { getRunToken } from "@/app/api/run/route";
import { loadConfig } from "@/lib/config";
import { DashboardApp } from "@/components/DashboardApp";
import type { DeckButton } from "@/components/DashboardApp";

// Server component: this is the ONLY place the run token and the config's button declarations
// are read. Both are handed to the client tree as props — never via any API/SSE payload — per
// runlog.ts's mintToken comment: an attacker who can only reach the HTTP API must not be able to
// recover the token. Buttons are narrowed to exactly the fields the client needs (name, label,
// profile, inputAllowed) — cwd/command never leave the server.
export default function Home() {
  const token = getRunToken();
  const config = loadConfig();
  const buttons: DeckButton[] = config.buttons.map((b) => ({
    name: b.name,
    label: b.label,
    profile: b.profile,
    inputAllowed: b.inputAllowed ?? false,
  }));

  return <DashboardApp token={token} buttons={buttons} />;
}
