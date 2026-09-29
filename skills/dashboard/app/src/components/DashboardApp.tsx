"use client";

import { useState } from "react";

import type { PermissionProfile } from "@/lib/config";
import { DashboardProvider } from "@/components/DashboardProvider";
import { Header } from "@/components/Header";
import { RailLeft } from "@/components/RailLeft";
import { RailRight } from "@/components/RailRight";
import { BottomHero } from "@/components/BottomHero";
import { Scene } from "@/components/sphere/Scene";
import { RunProgressLayer } from "@/components/RunProgressLayer";
import { HudCallout } from "@/components/HudCallout";
import { SessionTracePanel } from "@/components/SessionTracePanel";

export interface DeckButton {
  name: string;
  label: string;
  profile: PermissionProfile;
  inputAllowed: boolean;
}

export interface DashboardAppProps {
  token: string;
  buttons: DeckButton[];
}

// Scene lives INSIDE DashboardProvider (moved here from page.tsx in Task 9d) so the sphere can
// read the same single run-lifecycle/hue state as the rest of the HUD — one SSE connection, one
// accent-hue driver, no second signal path duplicating useDashboardState.
export function DashboardApp({ token, buttons }: DashboardAppProps) {
  const [traceOpen, setTraceOpen] = useState(false);
  return (
    <DashboardProvider>
      <div className="hud-root">
        <Scene />
        <div className="hud-floor-fade" />

        <div className="hud-stage">
          <Header />
          <RailLeft />
          <RailRight token={token} buttons={buttons} />
          <BottomHero />
        </div>

        <RunProgressLayer />
        <HudCallout />
        <button type="button" onClick={() => setTraceOpen((open) => !open)}
          aria-expanded={traceOpen} aria-controls="native-session-trace"
          style={{ position: "fixed", top: "0.75rem", right: "0.75rem", zIndex: 100,
            padding: "0.5rem", background: "#17212b", color: "#e9eef4", border: "1px solid #718096" }}>
          {traceOpen ? "Close session trace" : "Open session trace"}
        </button>
        {traceOpen && <div id="native-session-trace" style={{ position: "fixed", top: "3.5rem", right: "0.75rem",
          width: "min(44rem, calc(100vw - 1.5rem))", zIndex: 100 }}>
          <SessionTracePanel token={token} />
        </div>}
      </div>
    </DashboardProvider>
  );
}
