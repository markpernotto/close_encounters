import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchRiskOverview } from '../api';
import type { RiskOverviewResponse } from '../types';

export default function Risk() {
  const [data, setData] = useState<RiskOverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchRiskOverview(controller.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  return (
    <section className="page">
      <header className="page-head">
        <h1>Cross-agency impact risk</h1>
        <p className="page-sub">
          Two agencies — NASA Sentry and ESA NEOCC — independently compute
          impact-risk projections for newly-discovered and long-tracked
          objects. They mostly agree, but not always. The disagreements
          themselves are interesting: different observation arcs,
          different orbital-fit pipelines, different cutoffs.
        </p>
      </header>

      {loading && <p className="loading">Loading…</p>}
      {error && !loading && (
        <p className="error">Couldn't load risk overview: {error}</p>
      )}
      {data && !loading && (
        <>
          <p className="count">
            {data.total.toLocaleString()} objects tracked
            {data.assessment_date && (
              <span className="muted"> · snapshot {data.assessment_date}</span>
            )}
          </p>

          <h2>Cross-agency coverage</h2>
          <CoverageBars coverage={data.coverage} total={data.total} />

          <div className="risk-summary-grid">
            <div className="risk-summary-card">
              <h3>Elevated Torino</h3>
              <p className="risk-big-number">{data.elevated_torino}</p>
              <p className="muted">
                objects currently at Torino &gt; 0 (rare; almost all such
                ratings are retracted as observation arcs lengthen)
              </p>
            </div>

            {data.highest_palermo && (
              <div className="risk-summary-card">
                <h3>Highest Palermo cumulative</h3>
                <p className="mono risk-big-number">
                  <Link
                    to={`/objects/${encodeURIComponent(
                      data.highest_palermo.designation,
                    )}`}
                  >
                    {data.highest_palermo.designation}
                  </Link>
                </p>
                <p className="muted">
                  NASA{' '}
                  <span className="mono">
                    {data.highest_palermo.nasa?.palermo_scale?.toFixed(3) ?? '—'}
                  </span>{' '}
                  · ESA{' '}
                  <span className="mono">
                    {data.highest_palermo.esa?.palermo_scale?.toFixed(3) ?? '—'}
                  </span>
                </p>
              </div>
            )}
          </div>

          <h2>About the scales</h2>
          <dl className="scale-explainer">
            <dt>Torino scale (0–10)</dt>
            <dd>
              Integer hazard scale. <strong>0</strong> = no special concern
              (where almost everything sits). 1 = casual concern. 2–4 =
              meriting attention. ≥5 = serious concern. The famous public
              cases of Torino &gt; 0 — 99942 Apophis (briefly 4), 2024 YR4
              (briefly 3) — all eventually fell back to 0.
            </dd>
            <dt>Palermo scale (logarithmic)</dt>
            <dd>
              Compares an object's impact risk to a background
              "no-warning" baseline. Most are around −5 or lower; the
              "interesting" cutoff is roughly −2. The cumulative
              (cum) version aggregates across all impact scenarios; the
              max version is the single most-concerning scenario.
            </dd>
          </dl>
        </>
      )}
    </section>
  );
}

function CoverageBars({
  coverage,
  total,
}: {
  coverage: Record<string, number>;
  total: number;
}) {
  const order = ['both', 'NASA only', 'ESA only'];
  return (
    <ul className="coverage-bars">
      {order.map((key) => {
        const n = coverage[key] ?? 0;
        const pct = total > 0 ? (n / total) * 100 : 0;
        return (
          <li key={key} className="coverage-row">
            <span className="coverage-label">{key}</span>
            <div className="coverage-bar-track">
              <div
                className={`coverage-bar coverage-${key.replace(' ', '-')}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            <span className="coverage-count mono">{n.toLocaleString()}</span>
            <span className="coverage-pct muted mono">{pct.toFixed(1)}%</span>
          </li>
        );
      })}
    </ul>
  );
}
