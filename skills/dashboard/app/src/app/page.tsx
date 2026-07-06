import "@/styles/hud.css";
import { Header } from "@/components/Header";
import { RailLeft } from "@/components/RailLeft";
import { RailRight } from "@/components/RailRight";
import { BottomHero } from "@/components/BottomHero";

export default function Home() {
  return (
    <div className="hud-root">
      {/* Placeholder slots for Task 9c (R3F sphere + 2D fallback) — layering/z-index fixed here
          so 9c drops content in without restructuring the stage. */}
      <canvas className="hud-bg-canvas" aria-hidden="true" />
      <div className="hud-floor-fade" />

      <div className="hud-stage">
        <Header />
        <RailLeft />
        <RailRight />
        <BottomHero />
      </div>
    </div>
  );
}
