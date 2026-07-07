import type { ReactNode } from "react";
import { DashboardContext } from "../../src/components/DashboardProvider";
import type { DashboardSnapshot } from "../../src/hooks/useDashboardState";

// Test-only provider: wraps a fixed snapshot in DashboardContext without going through
// useDashboardState (which opens a real EventSource) — lets panel component tests render
// against an arbitrary snapshot via renderToStaticMarkup, same technique
// DashboardProvider.test.ts already uses for its own assertions.
export function DashboardContextTestProvider({
  snapshot,
  children,
}: {
  snapshot: DashboardSnapshot;
  // Optional so createElement(Provider, props, child) typechecks — TS's
  // function-component overload doesn't count rest-arg children against a
  // required `children` prop.
  children?: ReactNode;
}) {
  return (
    <DashboardContext.Provider value={{ snapshot, status: "online", lastUpdate: 0 }}>
      {children}
    </DashboardContext.Provider>
  );
}
