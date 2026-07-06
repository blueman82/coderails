"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   `pos` genuinely needs a one-time re-seed once the caller's window.innerWidth/Height-derived
   anchor resolves past its {0,0} SSR placeholder (see the effect below) — there is no pure-render
   derivation of "adopt this later value exactly once, then never again," same class of exception
   as this file's siblings (Header.tsx, RailLeft.tsx, Scene.tsx). */

import { useEffect, useRef, useState } from "react";

export interface Point {
  x: number;
  y: number;
}

export interface DraggableCalloutState {
  boxRef: React.RefObject<HTMLDivElement | null>;
  style: { left: number; top: number };
  dragging: boolean;
  leader: { left: number; top: number; width: number; height: number };
  onPointerDown: (e: React.PointerEvent) => void;
}

// Draggable HUD callout with a leader line back to a fixed anchor point, ported from the
// mockup's makeDraggable(): pointer-capture drag, leader attaches to the callout's nearest
// edge-centre to the anchor so it never crosses through the box.
export function useDraggableCallout(anchor: Point, initial: Point): DraggableCalloutState {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState(initial);
  const [dragging, setDragging] = useState(false);
  const [leader, setLeader] = useState({ left: 0, top: 0, width: 1, height: 1 });
  const dragStart = useRef<{ x: number; y: number; origLeft: number; origTop: number } | null>(null);

  // `anchor`/`initial` are {0,0} on first render (the caller's own window.innerWidth/Height
  // effect hasn't resolved yet — see HudCallout.tsx/RunProgress.tsx) and `useState(initial)`
  // only ever reads that first, wrong value: without this, `pos` stays pinned at the
  // pre-resolution {-260,-10}-ish position forever, rendering the callout permanently
  // off-screen. Re-seed `pos` from `initial` exactly once, the first time initial stops being
  // the {0,0}-derived placeholder — never again after that, so a user drag isn't fought.
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    if (anchor.x === 0 && anchor.y === 0) return; // still the pre-resolution placeholder
    seededRef.current = true;
    setPos(initial);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor.x, anchor.y]);

  function updateLeader(left: number, top: number) {
    const box = boxRef.current;
    if (!box) return;
    const rect = box.getBoundingClientRect();
    const boxX = left + rect.width / 2 < anchor.x ? left + rect.width : left;
    const boxY = top + rect.height / 2 < anchor.y ? top + rect.height : top;
    setLeader({
      left: Math.min(boxX, anchor.x),
      top: Math.min(boxY, anchor.y),
      width: Math.max(1, Math.abs(anchor.x - boxX)),
      height: Math.max(1, Math.abs(anchor.y - boxY)),
    });
  }

  useEffect(() => {
    updateLeader(pos.x, pos.y);
    function onResize() {
      updateLeader(pos.x, pos.y);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos.x, pos.y]);

  function onPointerDown(e: React.PointerEvent) {
    if ((e.target as HTMLElement).closest("[data-callout-close]")) return;
    dragStart.current = { x: e.clientX, y: e.clientY, origLeft: pos.x, origTop: pos.y };
    setDragging(true);
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }

  useEffect(() => {
    if (!dragging) return;
    function onMove(e: PointerEvent) {
      const start = dragStart.current;
      if (!start) return;
      const next = { x: start.origLeft + (e.clientX - start.x), y: start.origTop + (e.clientY - start.y) };
      setPos(next);
      updateLeader(next.x, next.y);
    }
    function onUp() {
      setDragging(false);
      dragStart.current = null;
    }
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging]);

  return { boxRef, style: { left: pos.x, top: pos.y }, dragging, leader, onPointerDown };
}
