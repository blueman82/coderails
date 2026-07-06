// Static SVG sparkline, ported from the mockup's canvas-drawn version (dashboard-mockup.html
// drawSparklines()). SVG is used here in place of canvas since the points are static placeholder
// data for Task 9a; Task 9b can swap the data source without touching the rendering.
export function Sparkline({ points }: { points: number[] }) {
  const w = 100;
  const h = 20;
  const d = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - p * h;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg className="hud-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke="rgba(217,144,154,0.8)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
