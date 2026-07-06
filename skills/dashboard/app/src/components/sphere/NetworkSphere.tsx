"use client";
/* eslint-disable react-hooks/immutability --
   R3F's render loop is inherently imperative: useFrame mutates the Three.js scene graph (camera,
   group transforms, buffer attributes) every frame by design. useThree()'s camera is a mutable
   escape hatch the React Compiler's hook-immutability rule can't distinguish from React-owned
   state — the documented "incompatible library" case the plugin ships a separate, lower-severity
   rule for elsewhere. Disabling this rule for the whole file is intentional, not a workaround. */

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

// Network-first sphere: a wired mesh of nodes, not a dot cloud. Structure (plexus wiring, hub
// hierarchy) is the dominant visual texture, per the normative mockup
// (docs/coderails/specs/assets/2026-07-06-observability/dashboard-mockup.html).
const PARTICLE_COUNT = 1100;
const HUB_FRACTION = 0.08;
const RADIUS = 13;
const SHELL = 0.9;
const PLEXUS_LINK_DIST = 2.6;
const PLEXUS_RECOMPUTE_EVERY = 14;
const ROSE_HEX = 0xd9909a;
const OFF_WHITE_HEX = 0xf3ecec;

function makeSpriteTexture(): THREE.CanvasTexture {
  const size = 64;
  const cvs = document.createElement("canvas");
  cvs.width = size;
  cvs.height = size;
  const ctx = cvs.getContext("2d")!;
  const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.35, "rgba(240,210,214,0.9)");
  grad.addColorStop(0.7, "rgba(217,144,154,0.35)");
  grad.addColorStop(1, "rgba(217,144,154,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(cvs);
}

function buildSphereData() {
  const positions = new Float32Array(PARTICLE_COUNT * 3);
  const home = new Float32Array(PARTICLE_COUNT * 3);
  const phases = new Float32Array(PARTICLE_COUNT);
  const isHub = new Uint8Array(PARTICLE_COUNT);

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = RADIUS + (Math.random() - 0.5) * SHELL;
    const x = r * Math.sin(phi) * Math.cos(theta);
    const y = r * Math.sin(phi) * Math.sin(theta);
    const z = r * Math.cos(phi);
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;
    home[i * 3] = x;
    home[i * 3 + 1] = y;
    home[i * 3 + 2] = z;
    phases[i] = Math.random() * Math.PI * 2;
    isHub[i] = Math.random() < HUB_FRACTION ? 1 : 0;
  }

  const hubIdx: number[] = [];
  const satIdx: number[] = [];
  for (let i = 0; i < PARTICLE_COUNT; i++) (isHub[i] ? hubIdx : satIdx).push(i);

  return { positions, home, phases, hubIdx, satIdx };
}

function buildLayerPositions(source: Float32Array, idxList: number[]): Float32Array {
  const arr = new Float32Array(idxList.length * 3);
  for (let li = 0; li < idxList.length; li++) {
    const src = idxList[li] * 3;
    arr[li * 3] = source[src];
    arr[li * 3 + 1] = source[src + 1];
    arr[li * 3 + 2] = source[src + 2];
  }
  return arr;
}

function recomputePlexus(positions: Float32Array, geometry: THREE.BufferGeometry) {
  const verts: number[] = [];
  const n = positions.length / 3;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dx = positions[i * 3] - positions[j * 3];
      const dy = positions[i * 3 + 1] - positions[j * 3 + 1];
      const dz = positions[i * 3 + 2] - positions[j * 3 + 2];
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < PLEXUS_LINK_DIST * PLEXUS_LINK_DIST) {
        verts.push(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);
        verts.push(positions[j * 3], positions[j * 3 + 1], positions[j * 3 + 2]);
      }
    }
  }
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(verts), 3));
}

export function NetworkSphere({ reducedMotion }: { reducedMotion: boolean }) {
  const { camera } = useThree();
  const groupRef = useRef<THREE.Group>(null);
  const satPointsRef = useRef<THREE.Points>(null);
  const hubPointsRef = useRef<THREE.Points>(null);
  const plexusRef = useRef<THREE.LineSegments>(null);

  const data = useMemo(() => buildSphereData(), []);
  const texture = useMemo(() => makeSpriteTexture(), []);

  const positionsRef = useRef(data.positions.slice());
  const plexusFrameCounter = useRef(0);
  const mouse = useRef({ x: 0, y: 0 });
  const smoothed = useRef({ x: 0, y: 0 });

  // Camera starts where the mockup places it; parallax nudges from here.
  useEffect(() => {
    camera.position.set(0, 2, 46);
  }, [camera]);

  useEffect(() => {
    function onMouseMove(e: MouseEvent) {
      mouse.current.x = (e.clientX / window.innerWidth - 0.5) * 2;
      mouse.current.y = (e.clientY / window.innerHeight - 0.5) * 2;
    }
    window.addEventListener("mousemove", onMouseMove);
    return () => window.removeEventListener("mousemove", onMouseMove);
  }, []);

  // Seed the initial plexus pass. When reducedMotion is set, useFrame below never re-triggers
  // it, so this single pass is the whole static frame's wiring.
  useEffect(() => {
    if (plexusRef.current) {
      recomputePlexus(positionsRef.current, plexusRef.current.geometry);
    }
  }, []);

  useFrame((state, delta) => {
    if (reducedMotion) return;
    const t = state.clock.getElapsedTime();
    const group = groupRef.current;
    if (!group) return;

    group.rotation.y = t * ((Math.PI * 2) / 90);
    group.rotation.x = Math.sin(t * 0.09) * 0.05;

    const breathe = 1 + Math.sin(t * ((Math.PI * 2) / 10)) * 0.015;
    group.scale.setScalar(breathe);

    const driftAmp = 0.35;
    const positions = positionsRef.current;
    const { home, phases } = data;
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const ph = phases[i];
      const nx = Math.sin(t * 0.6 + ph) * driftAmp;
      const ny = Math.cos(t * 0.5 + ph * 1.3) * driftAmp;
      const nz = Math.sin(t * 0.4 + ph * 0.7) * driftAmp;
      positions[i * 3] = home[i * 3] + nx;
      positions[i * 3 + 1] = home[i * 3 + 1] + ny;
      positions[i * 3 + 2] = home[i * 3 + 2] + nz;
    }

    function syncLayer(layer: THREE.Points | null, idx: number[]) {
      if (!layer) return;
      const arr = (layer.geometry.attributes.position as THREE.BufferAttribute).array as Float32Array;
      for (let li = 0; li < idx.length; li++) {
        const src = idx[li] * 3;
        arr[li * 3] = positions[src];
        arr[li * 3 + 1] = positions[src + 1];
        arr[li * 3 + 2] = positions[src + 2];
      }
      layer.geometry.attributes.position.needsUpdate = true;
    }
    syncLayer(satPointsRef.current, data.satIdx);
    syncLayer(hubPointsRef.current, data.hubIdx);

    // Twinkle on satellite/hub opacity, small oscillation like the reference.
    if (satPointsRef.current) {
      const mat = satPointsRef.current.material as THREE.PointsMaterial;
      mat.opacity = 0.55 + Math.sin(t * 3) * 0.04;
    }
    if (hubPointsRef.current) {
      const mat = hubPointsRef.current.material as THREE.PointsMaterial;
      mat.opacity = 0.9 + Math.sin(t * 2.4 + 1) * 0.05;
    }

    plexusFrameCounter.current++;
    if (plexusFrameCounter.current % PLEXUS_RECOMPUTE_EVERY === 0 && plexusRef.current) {
      recomputePlexus(positions, plexusRef.current.geometry);
    }

    // Damped mouse parallax on the camera.
    smoothed.current.x += (mouse.current.x - smoothed.current.x) * 0.02;
    smoothed.current.y += (mouse.current.y - smoothed.current.y) * 0.02;
    camera.position.x += (smoothed.current.x * 4 - camera.position.x) * 0.02;
    camera.position.y += (-smoothed.current.y * 2.4 + 2 - camera.position.y) * 0.02;
    camera.lookAt(0, 0, 0);

    void delta;
  });

  return (
    <>
      <fogExp2 attach="fog" args={[0x0d0708, 0.01]} />
      <group ref={groupRef}>
        <points ref={satPointsRef}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              args={[buildLayerPositions(data.positions, data.satIdx), 3]}
            />
          </bufferGeometry>
          <pointsMaterial
            color={OFF_WHITE_HEX}
            map={texture}
            size={0.34}
            transparent
            opacity={0.62}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            sizeAttenuation
          />
        </points>
        <points ref={hubPointsRef}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              args={[buildLayerPositions(data.positions, data.hubIdx), 3]}
            />
          </bufferGeometry>
          <pointsMaterial
            color={0xffffff}
            map={texture}
            size={1.1}
            transparent
            opacity={0.95}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
            sizeAttenuation
          />
        </points>
        <lineSegments ref={plexusRef}>
          <bufferGeometry />
          <lineBasicMaterial color={ROSE_HEX} transparent opacity={0.55} blending={THREE.AdditiveBlending} />
        </lineSegments>
      </group>
    </>
  );
}
