import { useEffect, useState } from 'react';
import AlertsTable from '../components/AlertsTable';
import { fetchAlerts } from '../api';
import type { AlertListResponse } from '../types';

export default function Alerts() {
  const [data, setData] = useState<AlertListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchAlerts({ limit: 100 }, controller.signal)
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
        <h1>Noteworthy alerts</h1>
        <p className="page-sub">
          Approaches that crossed a threshold rule: sizeable inside the lunar distance, very-close
          regardless of size, or new objects with short observation arcs and imminent approaches.
          Alerts are append-only — corrections appear as new alerts, never as edits.
        </p>
      </header>

      {loading && <p className="loading">Loading…</p>}
      {error && !loading && <p className="error">Couldn't load alerts: {error}</p>}
      {data && !loading && (
        <>
          <p className="count">
            {data.count} alert{data.count === 1 ? '' : 's'}
          </p>
          <AlertsTable items={data.items} />
        </>
      )}
    </section>
  );
}
