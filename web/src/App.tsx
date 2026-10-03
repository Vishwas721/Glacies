export function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <h1>Glacies</h1>
        <span className="city">Bengaluru</span>
      </header>
      <main className="layout">
        <aside className="panel" aria-label="Scenario">
          <h2>Scenario</h2>
        </aside>
        <section className="map" aria-label="Map">
          Map arrives in Phase 7
        </section>
        <aside className="panel" aria-label="Metrics">
          <h2>Metrics</h2>
        </aside>
      </main>
    </div>
  );
}
