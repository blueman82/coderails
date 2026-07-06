import "@/styles/hud.css";
import { Header } from "@/components/Header";
import { RailLeft } from "@/components/RailLeft";
import { RailRight } from "@/components/RailRight";
import { BottomHero } from "@/components/BottomHero";
import { Scene } from "@/components/sphere/Scene";
import { DebugProbe } from "@/components/sphere/DebugProbe";

export default function Home() {
  return (
    <div className="hud-root">
      <DebugProbe />
      <Scene />
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
