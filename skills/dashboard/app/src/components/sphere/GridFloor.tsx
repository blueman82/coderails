"use client";

import { useMemo } from "react";

// Static perspective wireframe floor, rose-tinted, filling the lower third and fading toward the
// horizon under/behind the sphere. Ported from the normative mockup (see NetworkSphere.tsx).
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

export function GridFloor() {
  const gridVerts = useMemo(() => buildGridVerts(), []);

  return (
    <lineSegments position={[0, -13, 0]}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[gridVerts, 3]} />
      </bufferGeometry>
      <lineBasicMaterial color={ROSE_HEX} transparent opacity={0.45} />
    </lineSegments>
  );
}
