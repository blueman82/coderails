"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useDashboardState, initialDashboardState, type DashboardState } from "@/hooks/useDashboardState";

// One EventSource per page load, not one per panel: each panel (Header,
// RailLeft, RailRight, BottomHero) used to call useDashboardState() itself,
// which meant four independent SSE connections — four aggregators on the
// server (four fs.watch sets, four gh-polling timers) and four
// independently-drifting reconnect/lastUpdate states on the client. This
// provider calls the hook exactly once and hands the single resulting state
// down via context; leaf components read it with useDashboardContext()
// instead of calling the hook directly.
const DashboardContext = createContext<DashboardState>(initialDashboardState);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const state = useDashboardState();
  return <DashboardContext.Provider value={state}>{children}</DashboardContext.Provider>;
}

export function useDashboardContext(): DashboardState {
  return useContext(DashboardContext);
}
