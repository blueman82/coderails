"use client";
/* eslint-disable react-hooks/set-state-in-effect --
   Both effects below resolve genuinely client-only values (matchMedia, WebGL context creation)
   that do not exist during SSR. A lazy useState initializer can't replace this: React reuses the
   server-computed initial state through hydration instead of re-running the initializer on the
   client, so the client's real answer would never land. The one-tick "resolve after mount" delay
   is the correct, unavoidable shape for this kind of client-only check, not a workaround. */

import { useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import { NetworkSphere } from "./NetworkSphere";
import { GridFloor } from "./GridFloor";
import { Fallback2D } from "./Fallback2D";
import { useDashboardContext } from "@/components/DashboardProvider";
import { useRunLifecycle } from "@/hooks/useRunLifecycle";

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

// SSR always has no window, so this is a client-only value: it must resolve after mount via an
// effect (a lazy useState initializer would freeze at the server's answer through hydration,
// since React reuses the SSR-computed initial state rather than re-running the initializer on
// the client). The one-tick delay before the real value lands is intentional and unavoidable.
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

export function Scene() {
  const reducedMotion = usePrefersReducedMotion();
  const [webglOK, setWebglOK] = useState<boolean | null>(null);
  const { snapshot } = useDashboardContext();
  const { accent, boost } = useRunLifecycle(snapshot.runs);

  useEffect(() => {
    let ok = false;
    try {
      ok = canCreateWebGL();
    } catch {
      ok = false;
    }
    if (!ok) {
      console.warn("NetworkSphere: WebGL unavailable, rendering 2D canvas fallback");
    }
    setWebglOK(ok);
  }, []);

  // Avoid a flash of the wrong renderer: render nothing for the one tick it takes to probe.
  if (webglOK === null) return null;

  if (!webglOK) {
    return <Fallback2D reducedMotion={reducedMotion} accent={accent} />;
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
      <NetworkSphere reducedMotion={reducedMotion} accent={accent} boost={boost} />
      <GridFloor accent={accent} />
      {!reducedMotion && (
        <EffectComposer>
          <Bloom luminanceThreshold={0.2} luminanceSmoothing={0.9} intensity={0.6} mipmapBlur />
        </EffectComposer>
      )}
    </Canvas>
  );
}
