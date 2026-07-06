// Static placeholder — Task 9b binds the live clock, kernel status, and run state.
export function Header() {
  return (
    <header className="hud-header">
      <div>
        <div className="hud-wordmark">C.O.D.E.R.A.I.L.S</div>
        <div className="hud-wordmark-sub">Agentic Operating System · Observability Terminal</div>
      </div>
      <div className="hud-status-line">
        <span className="hud-status-dot" />
        <span>Kernel · Online — Runner · Alive</span>
      </div>
      <div className="hud-clock-block">
        <div className="hud-clock-big">
          <span>12:49</span>
          <span className="hud-clock-secs">:32</span>
        </div>
        <div className="hud-clock-date">SUN · JUL 06</div>
      </div>
    </header>
  );
}
