"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   The live clock is a genuinely client-only value (SSR has no "now"); it must resolve after mount
   via an effect, same shape as Scene.tsx's usePrefersReducedMotion. */

import { useEffect, useState } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import { formatClockTime } from "@/hooks/useDashboardState";

const WEEKDAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

function formatClockDate(date: Date): string {
  const day = String(date.getDate()).padStart(2, "0");
  return `${WEEKDAYS[date.getDay()]} · ${MONTHS[date.getMonth()]} ${day}`;
}

export function Header() {
  const { status, lastUpdate } = useDashboardContext();
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const clock = now ? formatClockTime(now) : "--:--:--";
  const [hhmm, secs] = clock.includes(":") ? [clock.slice(0, 5), clock.slice(6)] : ["--:--", "--"];
  const dateLabel = now ? formatClockDate(now) : "";

  const isOnline = status === "online";
  const statusLabel = isOnline ? "Kernel · Online — Runner · Alive" : "Kernel · Reconnecting…";
  const lastUpdateLabel = lastUpdate ? `Last Update ${formatClockTime(new Date(lastUpdate))}` : null;

  return (
    <header className="hud-header">
      <div>
        <div className="hud-wordmark">C.O.D.E.R.A.I.L.S</div>
        <div className="hud-wordmark-sub">Agentic Operating System · Observability Terminal</div>
      </div>
      <div className="hud-status-line">
        <span className={`hud-status-dot${isOnline ? "" : " reconnecting"}`} />
        <span>{statusLabel}</span>
        {lastUpdateLabel && <span className="hud-status-last-update">{lastUpdateLabel}</span>}
      </div>
      <div className="hud-clock-block">
        <div className="hud-clock-big">
          <span>{hhmm}</span>
          <span className="hud-clock-secs">:{secs}</span>
        </div>
        <div className="hud-clock-date">{dateLabel}</div>
      </div>
    </header>
  );
}
