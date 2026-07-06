"use client";

import { useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import { NetworkSphere } from "./NetworkSphere";
import { GridFloor } from "./GridFloor";
import { Fallback2D } from "./Fallback2D";

// Probes WebGL context creation without mounting a real <Canvas> (R3F/three throw deep inside
// the render pipeline, not at a boundary React's error boundaries can reliably catch before
// paint). "GPU unavailable" is a real environment on this machine's history, so the probe must
// fail closed: any exception, or a null context, means fallback.
function canCreateWebGL(): boolean {
  try {
    const probe = document.createElement("canvas");
    const gl = probe.getContext("webgl2") || probe.getContext("webgl");
    return !!gl;
  } catch {
    return false;
  }
}

function usePrefersReducedMotion(): boolean {
  // Lazy initializer reads the synchronous browser API directly at first render; the effect
  // below only subscribes to later changes, so no setState call is needed to seed the value.
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

export function Scene() {
  const reducedMotion = usePrefersReducedMotion();
  // Deferred to a lazy initializer for the same reason as usePrefersReducedMotion: this is a
  // synchronous probe, not a subscription, so it belongs in render rather than an effect body.
  // null on the server (no window); the client's first render replaces it with the real probe
  // result, which is a one-time client/server mismatch React reconciles on hydration.
  const [webglOK] = useState<boolean | null>(() => {
    if (typeof window === "undefined") return null;
    let ok = false;
    try {
      ok = canCreateWebGL();
    } catch {
      ok = false;
    }
    if (!ok) {
      console.warn("NetworkSphere: WebGL unavailable, rendering 2D canvas fallback");
    }
    return ok;
  });

  // Avoid a flash of the wrong renderer: render nothing for the one tick it takes to probe.
  if (webglOK === null) return null;

  if (!webglOK) {
    return <Fallback2D reducedMotion={reducedMotion} />;
  }

  return (
    <Canvas
      className="hud-bg-canvas"
      gl={{ antialias: true, alpha: true }}
      camera={{ fov: 55, near: 0.1, far: 400, position: [0, 2, 46] }}
      onCreated={({ gl }) => {
        gl.setClearColor(0x0d0708, 0);
      }}
      frameloop={reducedMotion ? "demand" : "always"}
    >
      <NetworkSphere reducedMotion={reducedMotion} />
      <GridFloor />
      {!reducedMotion && (
        <EffectComposer>
          <Bloom luminanceThreshold={0.2} luminanceSmoothing={0.9} intensity={0.6} mipmapBlur />
        </EffectComposer>
      )}
    </Canvas>
  );
}
