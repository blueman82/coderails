"use client";

import { useRef, useState } from "react";
import { useDashboardContext } from "@/components/DashboardProvider";
import type { ContextTrendSummary, TrendSession } from "@/lib/collect/contextTrend";

// Renders the contextTrend collector's series as a live panel: one dot per
// agentic-loop session (x = start date, y = orchestrator cache-read tokens
// per assistant turn), the 2026-07-17 cutover drawn as an annotation the
// series runs straight through — no gap, no color change, no causal claim.
//
// Whether the cutover's measures reduced token burn is not established (see
// the collector's header), and the panel is built to keep it that way:
// per-side medians and n are shown side by side, never a single "saved X%"
// headline, and the reserved caveat color carries the two facts that bound
// the reading (a small after-side n; row 1 — the measure expected to save the
// most — inert since it shipped, per PR #273 which removed its gate after it
// fired zero times).

// Below this many sessions a side's median is drawn in the caveat color and
// said in words to be uncallable. This is a presentation threshold, not a
// statistical test — it only picks how a median is styled and captioned; every
// session stays plotted either way, and no value is adjusted or withheld.
// 20 is a deliberately conservative round number: it sits above the ~10-session
// after-group that first prompted the caveat, so a median gets called readable
// only well clear of that size.
const MIN_READABLE_N = 20;

// ViewBox geometry. The height includes the x-axis band and compaction
// track — the container never clips its own axis labels.
const W = 302;
const H = 152;
const PLOT = { left: 30, right: 296, top: 8, bottom: 112 };
const TRACK_Y = 124; // compaction event ticks
const AXIS_Y = 140; // x tick labels baseline
const HOVER_RADIUS = 24; // nearest-point hit distance in viewBox units

// Compact token count for axis ticks and stat rows: 243158 -> "243K".
function fmtK(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(Math.round(n));
}

// "MM-DD" in UTC — the audit bins sessions in UTC; labels match its dates.
function fmtDay(ms: number): string {
  return new Date(ms).toISOString().slice(5, 10);
}

function perTurn(s: TrendSession): number {
  return s.cacheRead / s.turns;
}

interface Scales {
  x: (ms: number) => number;
  y: (tokens: number) => number;
  xMaxMs: number;
  yMaxTokens: number;
  rScale: (turns: number) => number;
}

function buildScales(trend: ContextTrendSummary): Scales {
  const lastMs = trend.sessions.length > 0 ? trend.sessions[trend.sessions.length - 1].startMs : trend.cutoverMs;
  // Half-day pad so the newest dot never sits on the frame edge.
  const xMaxMs = Math.max(lastMs, trend.cutoverMs) + 12 * 60 * 60_000;
  const maxPerTurn = Math.max(...trend.sessions.map(perTurn));
  const yMaxTokens = Math.max(100_000, Math.ceil(maxPerTurn / 100_000) * 100_000);
  const maxTurns = Math.max(...trend.sessions.map((s) => s.turns));
  return {
    x: (ms) => PLOT.left + ((ms - trend.windowStartMs) / (xMaxMs - trend.windowStartMs)) * (PLOT.right - PLOT.left),
    y: (tokens) => PLOT.bottom - (tokens / yMaxTokens) * (PLOT.bottom - PLOT.top),
    xMaxMs,
    yMaxTokens,
    // Dot area tracks the turn count — the denominator IS evidence weight,
    // so a 3-turn scheduled routine renders visibly smaller than a 500-turn
    // loop instead of carrying equal visual weight.
    rScale: (turns) => 1.4 + 2.6 * Math.sqrt(turns / maxTurns),
  };
}

// Per-side median segment + IQR wash. `wholeSide` spans the side's full x
// extent so the reference line reads as "this period", not a data series.
function SideMarks({
  trend,
  scales,
  side,
}: {
  trend: ContextTrendSummary;
  scales: Scales;
  side: "before" | "after";
}) {
  const stats = trend[side];
  if (stats.n === 0 || stats.medianPerTurn === null) return null;
  const x0 = side === "before" ? scales.x(trend.windowStartMs) : scales.x(trend.cutoverMs) + 2;
  const x1 = side === "before" ? scales.x(trend.cutoverMs) - 2 : PLOT.right;
  const yMed = scales.y(stats.medianPerTurn);
  const thin = stats.n < MIN_READABLE_N;
  const stroke = thin ? "var(--caveat)" : "rgba(243, 236, 236, 0.75)";
  const label = thin ? `med ${fmtK(stats.medianPerTurn)} · n=${stats.n} — too few` : `med ${fmtK(stats.medianPerTurn)} · n=${stats.n}`;
  return (
    <g data-testid={`trend-median-${side}`} data-thin={thin || undefined}>
      {stats.q1PerTurn !== null && stats.q3PerTurn !== null && (
        // IQR wash — series-hue at wash opacity per mark spec, both sides
        // identical so the band never implies a verdict.
        <rect
          x={x0}
          y={scales.y(stats.q3PerTurn)}
          width={x1 - x0}
          height={scales.y(stats.q1PerTurn) - scales.y(stats.q3PerTurn)}
          fill="var(--rose)"
          opacity={0.08}
        />
      )}
      <line x1={x0} y1={yMed} x2={x1} y2={yMed} stroke={stroke} strokeWidth={1.2} strokeDasharray={thin ? "3 2" : undefined} />
      {/* A thin (small-n) segment is usually also narrow — end-anchor its
          label at the segment's right edge so it grows leftward over the
          plot instead of clipping at the frame. */}
      <text
        x={thin ? x1 : (x0 + x1) / 2}
        y={yMed - 3.5}
        textAnchor={thin ? "end" : "middle"}
        fontSize={6.5}
        letterSpacing="0.06em"
        fill={thin ? "var(--caveat)" : "var(--grey)"}
      >
        {label.toUpperCase()}
      </text>
    </g>
  );
}

export function ContextTrendPanel() {
  const { snapshot } = useDashboardContext();
  const trend = snapshot.contextTrend;
  const [hovered, setHovered] = useState<TrendSession | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const head = (
    <div className="hud-sec-head">
      <span className="hud-title">Context Trend</span>
      <span className="hud-suffix">CacheRead/Turn</span>
      <span className="hud-rule" />
    </div>
  );

  // contextTrend collects on its own SSE frame (it streams every coderails
  // orchestrator transcript,
  // far slower than the activity slice — see collect/index.ts). Its three
  // states map directly to what to render:
  //   undefined = that frame hasn't arrived yet → loading
  //   null      = frame arrived, source unreadable → unavailable
  //   summary   = data → the chart below
  // Keying off the field's own tri-state (rather than borrowing health's
  // load signal) is what lets it decouple from the activity frame without
  // flashing "unavailable" during the load window.
  if (trend === undefined) {
    return (
      <div className="hud-block" data-testid="context-trend">
        {head}
        <div className="hud-kpi-loading">loading…</div>
      </div>
    );
  }
  if (trend === null) {
    return (
      <div className="hud-block" data-testid="context-trend">
        {head}
        <div className="hud-kpi-unavailable">unavailable: no local usage source</div>
      </div>
    );
  }
  if (trend.sessions.length === 0) {
    return (
      <div className="hud-block" data-testid="context-trend">
        {head}
        <div className="hud-empty-state">no agentic-loop sessions since {fmtDay(trend.windowStartMs)}</div>
      </div>
    );
  }

  const scales = buildScales(trend);
  const compactionsSinceCutover = trend.compactions.filter((c) => c.timestampMs >= trend.cutoverMs).length;
  const lastCompaction = trend.compactions.length > 0 ? trend.compactions[trend.compactions.length - 1] : null;
  const cutoverX = scales.x(trend.cutoverMs);

  // Y gridlines on clean 100K steps (thinned to every 200K past 500K so the
  // left band never crowds).
  const yStep = scales.yMaxTokens > 500_000 ? 200_000 : 100_000;
  const yTicks: number[] = [];
  for (let v = 0; v <= scales.yMaxTokens; v += yStep) yTicks.push(v);
  // Weekly x ticks from the window start.
  const xTicks: number[] = [];
  for (let ms = trend.windowStartMs; ms <= scales.xMaxMs; ms += 7 * 24 * 60 * 60_000) xTicks.push(ms);

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || !trend) return;
    const rect = svg.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    const py = ((e.clientY - rect.top) / rect.height) * H;
    let best: TrendSession | null = null;
    let bestD = HOVER_RADIUS * HOVER_RADIUS;
    for (const s of trend.sessions) {
      const dx = scales.x(s.startMs) - px;
      const dy = scales.y(perTurn(s)) - py;
      const d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = s;
      }
    }
    setHovered(best);
  }

  return (
    <div className="hud-block" data-testid="context-trend">
      {head}

      <svg
        ref={svgRef}
        className="hud-trend-chart"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Orchestrator cache-read tokens per assistant turn, one dot per agentic-loop session, across the 2026-07-17 cutover"
        onMouseMove={onMove}
        onMouseLeave={() => setHovered(null)}
      >
        {/* Grid — solid hairlines, recessive. */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={PLOT.left} y1={scales.y(v)} x2={PLOT.right} y2={scales.y(v)} stroke="var(--hairline)" strokeWidth={1} />
            <text x={PLOT.left - 3} y={scales.y(v) + 2} textAnchor="end" fontSize={6.5} fill="var(--grey-dim)">
              {v === 0 ? "0" : fmtK(v)}
            </text>
          </g>
        ))}
        {xTicks.map((ms) => (
          <text key={ms} x={scales.x(ms)} y={AXIS_Y} textAnchor="middle" fontSize={6.5} letterSpacing="0.06em" fill="var(--grey-dim)">
            {fmtDay(ms)}
          </text>
        ))}

        {/* Cutover — an annotation, not a verdict: one hairline the series
            runs straight through, dots identical on both sides. */}
        <g data-testid="trend-cutover">
          <line x1={cutoverX} y1={PLOT.top} x2={cutoverX} y2={TRACK_Y + 4} stroke="var(--grey)" strokeWidth={1} />
          <text x={cutoverX + 3} y={PLOT.top + 5} fontSize={6.5} letterSpacing="0.08em" fill="var(--grey)">
            CUTOVER {fmtDay(trend.cutoverMs)}
          </text>
        </g>

        <SideMarks trend={trend} scales={scales} side="before" />
        <SideMarks trend={trend} scales={scales} side="after" />

        {/* Sessions — one hue on both sides of the cutover. Dot area tracks
            turn count; the surface-color ring keeps overlaps legible. */}
        {trend.sessions.map((s) => (
          <circle
            key={s.sessionId}
            data-testid="trend-dot"
            cx={scales.x(s.startMs)}
            cy={scales.y(perTurn(s))}
            r={scales.rScale(s.turns)}
            fill="var(--rose)"
            fillOpacity={0.85}
            stroke="var(--void)"
            strokeWidth={1}
          >
            <title>{`${fmtDay(s.startMs)} · ${Math.round(perTurn(s)).toLocaleString()} cache-read/turn · ${s.turns} turns`}</title>
          </circle>
        ))}
        {hovered && (
          <circle
            cx={scales.x(hovered.startMs)}
            cy={scales.y(perTurn(hovered))}
            r={scales.rScale(hovered.turns) + 2.5}
            fill="none"
            stroke="var(--off-white)"
            strokeWidth={1}
            pointerEvents="none"
          />
        )}

        {/* Compaction track: one tick per compaction boundary. The after
            side's emptiness is the point — named in the caveat color. */}
        <g data-testid="trend-compactions">
          <line x1={PLOT.left} y1={TRACK_Y + 4} x2={PLOT.right} y2={TRACK_Y + 4} stroke="var(--hairline)" strokeWidth={1} />
          <text x={PLOT.left - 3} y={TRACK_Y + 4} textAnchor="end" fontSize={6} fill="var(--grey-dim)">
            CMP
          </text>
          {trend.compactions
            .filter((c) => c.timestampMs >= trend.windowStartMs && c.timestampMs <= scales.xMaxMs)
            .map((c) => (
              <path
                key={c.timestampMs}
                d={`M ${scales.x(c.timestampMs)} ${TRACK_Y - 1} l 2.4 4.5 h -4.8 Z`}
                fill={c.trigger === "manual" ? "var(--grey)" : "var(--grey-dim)"}
              >
                <title>{`${fmtDay(c.timestampMs)} · ${c.trigger} compaction`}</title>
              </path>
            ))}
          {compactionsSinceCutover === 0 && (
            <text
              x={(cutoverX + PLOT.right) / 2}
              y={TRACK_Y + 2}
              textAnchor="middle"
              fontSize={6}
              letterSpacing="0.06em"
              fill="var(--caveat)"
            >
              0 SINCE CUTOVER
            </text>
          )}
        </g>
      </svg>

      <div className={`hud-trend-readout${hovered ? "" : " idle"}`} data-testid="trend-readout">
        {hovered
          ? `${fmtDay(hovered.startMs)} · ${Math.round(perTurn(hovered)).toLocaleString()}/turn · ${hovered.turns} turns · ${
              hovered.startMs < trend.cutoverMs ? "before" : "after"
            }`
          : "hover a session for detail"}
      </div>

      {(["before", "after"] as const).map((side) => {
        const stats = trend[side];
        return (
          <div className="hud-trend-row" key={side}>
            <span>
              {side} · n={stats.n}
            </span>
            <span className="hud-trend-fill" />
            <span className="hud-trend-value">
              {stats.medianPerTurn !== null && stats.q1PerTurn !== null && stats.q3PerTurn !== null
                ? `med ${fmtK(stats.medianPerTurn)}/turn · iqr ${fmtK(stats.q1PerTurn)}–${fmtK(stats.q3PerTurn)}`
                : "no sessions"}
            </span>
          </div>
        );
      })}

      {trend.after.n > 0 && trend.after.n < MIN_READABLE_N && (
        <div className="hud-trend-caveat">
          After side is n={trend.after.n} — too few sessions to call a trend either way.
        </div>
      )}
      {compactionsSinceCutover === 0 ? (
        <div className="hud-trend-caveat">
          Mandatory compaction (row 1, documented as the largest saving) has fired 0 times since the cutover
          {lastCompaction ? ` — last fired ${fmtDay(lastCompaction.timestampMs)}` : " — never in this data"}. Whatever
          moved this trend, it was not row 1.
        </div>
      ) : (
        <div className="hud-trend-row">
          <span>compactions since cutover</span>
          <span className="hud-trend-fill" />
          <span className="hud-trend-value">{compactionsSinceCutover}</span>
        </div>
      )}

      <div className="hud-trend-footer">
        Orch cache-read per assistant turn · loop sessions since {fmtDay(trend.windowStartMs)} · the cutover line is an
        annotation, not a verdict — attribution is indeterminate
      </div>
    </div>
  );
}
