import { useEffect, useState } from 'react';
import ApproachesTable from '../components/ApproachesTable';
import { fetchUpcomingApproaches } from '../api';
import type { ApproachListResponse } from '../types';

export default function Home() {
  const [data, setData] = useState<ApproachListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchUpcomingApproaches({ days: 60, limit: 500 }, controller.signal)
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
        <h1>Upcoming close approaches</h1>
        <p className="page-sub">
          Next 60 days, sourced from NASA JPL CNEOS. Sort any column by clicking its header.
        </p>
      </header>

      {loading && <p className="loading">Loading…</p>}
      {error && !loading && (
        <p className="error">Couldn't load upcoming approaches: {error}</p>
      )}
      {data && !loading && (
        <>
          <p className="count">
            {data.count} approach{data.count === 1 ? '' : 'es'} in the next {data.window_days} days
            {data.snapshot_date && (
              <span className="muted"> · snapshot {data.snapshot_date}</span>
            )}
          </p>
          <ApproachesTable items={data.items} />
        </>
      )}
    </section>
  );
}
