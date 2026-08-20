"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { hslToRgb, type AccentHsl } from "@/lib/runHue";

// Static perspective wireframe floor, rose-tinted, filling the lower third and fading toward the
// horizon under/behind the sphere. Re-tinted with the live accent hue each frame (see
// NetworkSphere.tsx) so it moves with the rest of the theme during a run.
const ROSE_HEX = 0xd9909a;
const GRID_SIZE = 140;
const GRID_DIV = 28;

function buildGridVerts(): Float32Array {
  const half = GRID_SIZE / 2;
  const verts: number[] = [];
  for (let g = 0; g <= GRID_DIV; g++) {
    const p = -half + (GRID_SIZE / GRID_DIV) * g;
    verts.push(-half, 0, p, half, 0, p);
    verts.push(p, 0, -half, p, 0, half);
  }
  return new Float32Array(verts);
}

export function GridFloor({ accent }: { accent: AccentHsl }) {
  const gridVerts = useMemo(() => buildGridVerts(), []);
  const materialRef = useRef<THREE.LineBasicMaterial>(null);
  const accentRef = useRef(accent);

  useEffect(() => {
    accentRef.current = accent;
  }, [accent]);

  useFrame(() => {
    const mat = materialRef.current;
    if (!mat) return;
    const rgb = hslToRgb(accentRef.current.h, accentRef.current.s, accentRef.current.l);
    mat.color.setRGB(rgb.r / 255, rgb.g / 255, rgb.b / 255);
  });

  return (
    <lineSegments position={[0, -13, 0]}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[gridVerts, 3]} />
      </bufferGeometry>
      <lineBasicMaterial ref={materialRef} color={ROSE_HEX} transparent opacity={0.45} />
    </lineSegments>
  );
}
