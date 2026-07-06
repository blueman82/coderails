"use client";

import { useEffect, useState } from "react";
import { useDashboardState } from "@/hooks/useDashboardState";
import { formatClockTime } from "@/hooks/useDashboardState";

const DATE_FMT = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "2-digit" });

function formatClockDate(date: Date): string {
  return DATE_FMT.format(date).toUpperCase().replace(/,/g, "").replace(/\s(\w{3})\s/, " · $1 ");
}

export function Header() {
  const { status, lastUpdate } = useDashboardState();
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
