import { useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

function App() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function analyzeTrip() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/heatmap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          analytic_type: "tcm",
          latitude: 29.4241,
          longitude: -98.4936,
          start_date: "2026-08-23",
          forecast: false,
        }),
      });
      const payload = await response.json();
      if (!response.ok)
        throw new Error(payload.detail?.error || "Analysis unavailable");
      setResult(payload);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Analysis unavailable"
      );
    } finally {
      setLoading(false);
    }
  }

  const tile = result?.tiles?.[0];

  return (
    <main className="page-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">HA</span>
          <span>Heat-Aware Tourism Guide</span>
        </div>
        <span className="mode">Fixture mode</span>
      </header>
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">San Antonio · Alamo Plaza</p>
          <h1>Choose your walking window with better heat context.</h1>
          <p className="lede">
            A focused trip view for the walk from Menger Hotel to The Alamo,
            backed by the validated San Antonio fixture.
          </p>
          <button type="button" onClick={analyzeTrip} disabled={loading}>
            {loading ? "Loading analysis" : "Run heat analysis"}
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
        <aside className="scenario-panel">
          <div className="panel-label">Current trip</div>
          <div className="route-line">
            <span className="route-dot start" />
            <div>
              <small>Origin</small>
              <strong>Menger Hotel</strong>
            </div>
          </div>
          <div className="route-stem" />
          <div className="route-line">
            <span className="route-dot end" />
            <div>
              <small>Destination</small>
              <strong>The Alamo</strong>
            </div>
          </div>
          <div className="panel-footer">
            <span>Downtown San Antonio</span>
            <span>Historical fixture</span>
          </div>
        </aside>
      </section>
      {result && (
        <section className="result-strip" aria-live="polite">
          <div>
            <span className="metric-label">Heat reading</span>
            <strong>{tile?.value_celsius ?? "--"}°C</strong>
          </div>
          <div>
            <span className="metric-label">Source</span>
            <strong>{result.provenance?.source}</strong>
          </div>
          <div>
            <span className="metric-label">Data date</span>
            <strong>{result.provenance?.data_date}</strong>
          </div>
          <div>
            <span className="metric-label">Status</span>
            <strong>Analysis ready</strong>
          </div>
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
