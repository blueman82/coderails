"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   Drag position is a genuinely client-only, pointer-driven value (no SSR equivalent) — same
   class of exception as Scene.tsx's WebGL probe and Header.tsx's live clock. */

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
