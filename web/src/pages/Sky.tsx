import { lazy, Suspense, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import AllSkyChart from '../components/AllSkyChart';
import LocationPicker, { type LatLon } from '../components/LocationPicker';
import {
  fetchConstellations,
  fetchSky,
  fetchSkyTrack,
  fetchStarCatalog,
} from '../api';
import type {
  ConstellationData,
  SkyResponse,
  SkyTrackResponse,
  StarCatalog,
} from '../types';

// three.js is heavy; keep it out of the main bundle and load it only when the
// dome is actually shown.
const SkyDome = lazy(() => import('../components/SkyDome'));

// Time scrubber is hidden for now — in the alt/az frame its motion is mostly
// just Earth rotating, which reads as confusing rather than informative. The
// endpoint + dome track code stay in place; flip this to bring it back.
const SHOW_SCRUBBER = false;

const DEFAULT_LOCATION: LatLon = { lat: 44.29, lon: -121.55, label: 'Sisters, OR' };

type View = 'dome' | 'chart';

export default function Sky() {
  const [location, setLocation] = useState<LatLon>(DEFAULT_LOCATION);
  const [view, setView] = useState<View>('dome');
  const [data, setData] = useState<SkyResponse | null>(null);
  const [track, setTrack] = useState<SkyTrackResponse | null>(null);
  const [stars, setStars] = useState<StarCatalog | null>(null);
  const [constellations, setConstellations] = useState<ConstellationData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Background star + constellation catalogs are static and location-independent;
  // load them once. A failure here shouldn't blank the page — the dome still
  // renders the tracked objects without a starfield.
  useEffect(() => {
    const controller = new AbortController();
    fetchStarCatalog(controller.signal)
      .then(setStars)
      .catch(() => {});
    fetchConstellations(controller.signal)
      .then(setConstellations)
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setTrack(null);
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
    // The track (±48h paths for the scrubber) is heavier; only fetch it when
    // the scrubber is enabled. A failure here leaves the static dome intact.
    if (SHOW_SCRUBBER) {
      fetchSkyTrack(
        { lat: location.lat, lon: location.lon, minAltitude: 0 },
        controller.signal,
      )
        .then(setTrack)
        .catch(() => {});
    }
    return () => controller.abort();
  }, [location]);

  return (
    <section className="page">
      <header className="page-head">
        <h1>What's above you</h1>
        <p className="page-sub">
          Stand anywhere on Earth and look up with no light pollution, no
          clouds, no daylight. Stars and constellations are drawn from a real
          catalog; the colored markers are the near-Earth objects we track,
          placed from JPL orbital elements. Drag to look around.
        </p>
      </header>

      <LocationPicker value={location} onChange={setLocation} />

      <div className="view-toggle" role="tablist" aria-label="Sky view">
        <button
          type="button"
          role="tab"
          aria-selected={view === 'dome'}
          className={`view-tab ${view === 'dome' ? 'active' : ''}`}
          onClick={() => setView('dome')}
        >
          Dome
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === 'chart'}
          className={`view-tab ${view === 'chart' ? 'active' : ''}`}
          onClick={() => setView('chart')}
        >
          All-sky chart
        </button>
      </div>

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

          {view === 'dome' ? (
            <Suspense fallback={<p className="loading">Loading the dome…</p>}>
              <SkyDome
                objects={data.objects}
                track={track}
                stars={stars}
                constellations={constellations}
                lat={location.lat}
                lon={location.lon}
                when={new Date(data.observed_at)}
              />
            </Suspense>
          ) : data.count === 0 ? (
            <p className="empty">
              Nothing tracked is above the horizon here right now. The
              warehouse currently follows a few dozen close-approach objects;
              most of the time, most of them are below the horizon or on the
              far side of the sky. Try a different location, or switch to the
              dome to see the stars regardless.
            </p>
          ) : (
            <AllSkyChart objects={data.objects} />
          )}

          <p className="muted sky-footnote">
            Object positions computed from JPL orbital elements via skyfield;
            star and constellation positions converted to your local sky in the
            browser. Drag to look around, scroll to zoom; hover an object for
            its altitude and distance, and click to open its full record. See{' '}
            <Link to="/">upcoming approaches</Link> for the time-ordered list.
          </p>
        </>
      )}
    </section>
  );
}
