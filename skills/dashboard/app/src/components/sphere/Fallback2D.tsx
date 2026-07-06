"use client";

import { useEffect, useRef } from "react";
import { hslToRgb, type AccentHsl } from "@/lib/runHue";

// 2D-canvas plexus sphere: mirrors the WebGL sphere's palette and structure (rose rim, plexus
// wiring, depth-based fade) for environments where a WebGL context cannot be created. Re-tinted
// with the live accent hue each frame (via the `accent` prop) so the fallback path stays in sync
// with the rest of the theme during a run, same as the mockup's 2D fallback reads currentAccent.
// Ported from docs/coderails/specs/assets/2026-07-06-observability/dashboard-mockup.html.
const COUNT = 260;
const LINK_DIST = 46;

type Point3D = { theta: number; phi: number; phase: number; r: number };

function makePoints(): Point3D[] {
  const pts: Point3D[] = [];
  for (let i = 0; i < COUNT; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pts.push({ theta, phi, phase: Math.random() * Math.PI * 2, r: 1 + Math.random() * 1.6 });
  }
  return pts;
}

function project(theta: number, phi: number, rot: number, cx: number, cy: number, radius: number) {
  const x = Math.sin(phi) * Math.cos(theta + rot);
  const y = Math.sin(phi) * Math.sin(theta + rot) * 0.55;
  const z = Math.cos(phi);
  return { x: cx + x * radius, y: cy + y * radius * 1.5, z };
}

export function Fallback2D({ reducedMotion, accent }: { reducedMotion: boolean; accent: AccentHsl }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const accentRef = useRef(accent);
  accentRef.current = accent;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const pts = makePoints();
    let w = 0;
    let h = 0;
    let cx = 0;
    let cy = 0;
    let radius = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      w = window.innerWidth;
      h = window.innerHeight;
      cx = w / 2;
      cy = h / 2;
      radius = Math.min(w, h) * 0.24;
      canvas!.width = w * dpr;
      canvas!.height = h * dpr;
      canvas!.style.width = w + "px";
      canvas!.style.height = h + "px";
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    window.addEventListener("resize", resize);

    function drawFrame(rot: number) {
      ctx!.clearRect(0, 0, w, h);
      const proj = pts.map((p) => project(p.theta, p.phi, rot, cx, cy, radius));
      const rgb = hslToRgb(accentRef.current.h, accentRef.current.s, accentRef.current.l);
      const accentCss = `${rgb.r},${rgb.g},${rgb.b}`;

      // Plexus first (behind dots).
      for (let i = 0; i < proj.length; i++) {
        for (let j = i + 1; j < proj.length; j++) {
          const dx = proj[i].x - proj[j].x;
          const dy = proj[i].y - proj[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < LINK_DIST && proj[i].z > -0.3 && proj[j].z > -0.3) {
            const op = (1 - dist / LINK_DIST) * 0.1;
            ctx!.strokeStyle = `rgba(${accentCss},${op.toFixed(3)})`;
            ctx!.lineWidth = 1;
            ctx!.beginPath();
            ctx!.moveTo(proj[i].x, proj[i].y);
            ctx!.lineTo(proj[j].x, proj[j].y);
            ctx!.stroke();
          }
        }
      }

      for (let k = 0; k < proj.length; k++) {
        const pr = proj[k];
        const depth = (pr.z + 1) / 2;
        const twinkle = reducedMotion ? 1 : 0.6 + 0.4 * Math.sin(rot * 8 + pts[k].phase);
        const alpha = (0.25 + depth * 0.6) * twinkle;
        const isRim = depth < 0.4;
        ctx!.beginPath();
        ctx!.fillStyle = isRim ? `rgba(${accentCss},${alpha.toFixed(3)})` : `rgba(243,236,236,${alpha.toFixed(3)})`;
        ctx!.arc(pr.x, pr.y, pts[k].r * (0.6 + depth * 0.6), 0, Math.PI * 2);
        ctx!.fill();
      }
    }

    let raf = 0;
    if (reducedMotion) {
      drawFrame(0);
    } else {
      const frame = (tMs: number) => {
        drawFrame(tMs * 0.00015);
        raf = requestAnimationFrame(frame);
      };
      raf = requestAnimationFrame(frame);
    }

    return () => {
      window.removeEventListener("resize", resize);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [reducedMotion]);

  return <canvas ref={canvasRef} className="hud-bg-canvas" aria-hidden="true" />;
}
