import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import AllSkyChart from '../components/AllSkyChart';
import LocationPicker, { type LatLon } from '../components/LocationPicker';
import { fetchSky } from '../api';
import type { SkyResponse } from '../types';

const DEFAULT_LOCATION: LatLon = { lat: 44.29, lon: -121.55, label: 'Sisters, OR' };

export default function Sky() {
  const [location, setLocation] = useState<LatLon>(DEFAULT_LOCATION);
  const [data, setData] = useState<SkyResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    fetchSky(
      { lat: location.lat, lon: location.lon, minAltitude: 0 },
      controller.signal,
    )
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [location]);

  return (
    <section className="page">
      <header className="page-head">
        <h1>What's above you</h1>
        <p className="page-sub">
          Tracked near-Earth objects currently above the horizon, projected
          onto an all-sky chart — as if light pollution and clouds weren't in
          the way. Pick any location on Earth to see its sky instead of yours.
        </p>
      </header>

      <LocationPicker value={location} onChange={setLocation} />

      {loading && <p className="loading">Computing positions…</p>}
      {error && !loading && (
        <p className="error">Couldn't compute the sky: {error}</p>
      )}

      {data && !loading && (
        <>
          <p className="count">
            {data.count} object{data.count === 1 ? '' : 's'} above the horizon
            from {location.label}
            <span className="muted">
              {' '}· {new Date(data.observed_at).toUTCString()}
            </span>
          </p>

          {data.count === 0 ? (
            <p className="empty">
              Nothing tracked is above the horizon here right now. The
              warehouse currently follows a few dozen close-approach objects;
              most of the time, most of them are below the horizon or on the
              far side of the sky. Try a different location, or check back as
              the catalog grows.
            </p>
          ) : (
            <AllSkyChart objects={data.objects} />
          )}

          <p className="muted sky-footnote">
            Positions computed from JPL orbital elements via skyfield. This
            shows solar-system objects we track — not background stars or
            constellations (those are coming). Click any marker to open the
            object's full record. See{' '}
            <Link to="/">upcoming approaches</Link> for the time-ordered list.
          </p>
        </>
      )}
    </section>
  );
}
