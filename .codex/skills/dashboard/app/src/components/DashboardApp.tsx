"use client";

import type { PermissionProfile } from "@/lib/config";
import { DashboardProvider } from "@/components/DashboardProvider";
import { Header } from "@/components/Header";
import { RailLeft } from "@/components/RailLeft";
import { RailRight } from "@/components/RailRight";
import { BottomHero } from "@/components/BottomHero";
import { Scene } from "@/components/sphere/Scene";
import { RunProgressLayer } from "@/components/RunProgressLayer";
import { HudCallout } from "@/components/HudCallout";

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
      </div>
    </DashboardProvider>
  );
}
