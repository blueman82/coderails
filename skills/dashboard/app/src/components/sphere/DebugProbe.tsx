"use client";
import { useEffect, useState } from "react";
export function DebugProbe() {
  const [n, setN] = useState(0);
  useEffect(() => {
    console.warn("DEBUG_PROBE_MOUNTED");
    setN(1);
  }, []);
  return <div style={{ position: "fixed", top: 0, left: 0, zIndex: 9999, color: "lime", background: "black" }}>PROBE:{n}</div>;
}
