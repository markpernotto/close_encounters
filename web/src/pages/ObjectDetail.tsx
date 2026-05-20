import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import ApproachesTable from '../components/ApproachesTable';
import OrbitHistoryTimeline from '../components/OrbitHistoryTimeline';
import PublicationsPanel from '../components/PublicationsPanel';
import RiskPanel from '../components/RiskPanel';
import {
  ApiError,
  fetchObject,
  fetchObjectApproaches,
  fetchObjectPublications,
  fetchOrbitHistory,
  fetchRiskForObject,
} from '../api';
import type {
  ApproachListResponse,
  ObjectDetail as ObjectDetailType,
  OrbitHistoryResponse,
  PublicationsResponse,
  RiskAssessmentItem,
} from '../types';

export default function ObjectDetail() {
  const { designation } = useParams<{ designation: string }>();
  const [obj, setObj] = useState<ObjectDetailType | null>(null);
  const [approaches, setApproaches] = useState<ApproachListResponse | null>(null);
  const [orbitHistory, setOrbitHistory] = useState<OrbitHistoryResponse | null>(null);
  const [risk, setRisk] = useState<RiskAssessmentItem | null>(null);
  const [publications, setPublications] = useState<PublicationsResponse | null>(null);
  const [error, setError] = useState<{ status?: number; message: string } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!designation) return;
    const controller = new AbortController();
    setLoading(true);
    const settleHistory = (e: Error) => {
      if (e.name !== 'AbortError') setOrbitHistory(null);
    };
    const settleRisk = (e: Error) => {
      // 404 here is expected (most objects aren't on a risk list)
      if (e.name !== 'AbortError') setRisk(null);
    };
    Promise.all([
      fetchObject(designation, controller.signal),
      fetchObjectApproaches(designation, controller.signal),
    ])
      .then(([o, a]) => {
        setObj(o);
        setApproaches(a);
        setError(null);
        // Optional fetches — fire after we know the object resolved
        fetchOrbitHistory(o.designation, controller.signal)
          .then(setOrbitHistory)
          .catch(settleHistory);
        fetchRiskForObject(o.designation, controller.signal)
          .then(setRisk)
          .catch(settleRisk);
        fetchObjectPublications(o.designation, controller.signal)
          .then(setPublications)
          .catch((e: Error) => {
            if (e.name !== 'AbortError') setPublications(null);
          });
      })
      .catch((e: Error) => {
        if (e.name === 'AbortError') return;
        if (e instanceof ApiError) setError({ status: e.status, message: e.message });
        else setError({ message: e.message });
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [designation]);

  if (loading) return <section className="page"><p className="loading">Loading…</p></section>;

  if (error?.status === 404) {
    return (
      <section className="page">
        <p className="error">
          Object <span className="mono">{designation}</span> not in the current snapshot.
        </p>
        <p>
          <Link to="/">Back to upcoming approaches</Link>
        </p>
      </section>
    );
  }

  if (error) {
    return (
      <section className="page">
        <p className="error">Couldn't load object {designation}: {error.message}</p>
      </section>
    );
  }

  if (!obj || !approaches) return null;

  return (
    <section className="page">
      <header className="page-head">
        <h1 className="mono">{obj.full_name || obj.designation}</h1>
        <p className="page-sub">
          {obj.orbit_class && <span className="tag">{obj.orbit_class}</span>}
          {obj.neo && <span className="tag">NEO</span>}
          {obj.pha && <span className="tag tag-warn">PHA</span>}
        </p>
      </header>

      <dl className="object-facts">
        <Fact label="SPK-ID" value={obj.spkid} mono />
        <Fact label="Designation" value={obj.designation} mono />
        <Fact label="Absolute magnitude H" value={obj.absolute_magnitude_h?.toFixed(2)} />
        <Fact
          label="Diameter"
          value={
            obj.diameter_km
              ? formatDiameter(obj.diameter_km)
              : obj.diameter_estimate_km
                ? `~${formatDiameter(obj.diameter_estimate_km)} (estimated)`
                : 'unknown'
          }
        />
        <Fact label="Albedo" value={obj.albedo?.toFixed(3)} />
        <Fact label="Rotation period" value={obj.rotation_period_h ? `${obj.rotation_period_h.toFixed(2)} h` : null} />
        <Fact label="Spectral class" value={obj.spec_class} />
        <Fact label="Observation arc" value={obj.observation_arc_days ? `${obj.observation_arc_days} days` : null} />
        <Fact label="Observations used" value={obj.n_observations?.toLocaleString()} />
        <Fact label="First observed" value={obj.first_observed} mono />
        <Fact label="Last observed" value={obj.last_observed} mono />
        <Fact label="Orbit solution date" value={obj.solution_date} mono />
      </dl>

      {(obj.discoverer || obj.discovery_date || obj.discovery_program || obj.discovery_facility) && (
        <section className="discovery-card">
          <h3>Discovery</h3>
          <dl className="discovery-facts">
            <Fact label="Date" value={obj.discovery_date} mono />
            <Fact
              label="Program"
              value={obj.discovery_program}
              mono
            />
            <Fact label="Facility" value={obj.discovery_facility} />
            <Fact label="Reported by" value={obj.discoverer} />
            <Fact label="MPEC" value={obj.discovery_mpec_id} mono />
          </dl>
          {obj.citation_text && (
            <blockquote className="citation-quote">
              {/* SBDB's `citation` is HTML-escaped already; render as plain text */}
              {obj.citation_text}
            </blockquote>
          )}
        </section>
      )}

      {risk && <RiskPanel risk={risk} />}

      <h2>Close approaches in current snapshot</h2>
      <ApproachesTable items={approaches.items} />

      {orbitHistory && orbitHistory.count > 0 && (
        <>
          <h2>Orbit-determination history</h2>
          <p className="muted">
            Each row is a JPL orbit revision. Newer rows reflect refined
            predictions as observation arcs lengthen.
          </p>
          <OrbitHistoryTimeline revisions={orbitHistory.revisions} />
        </>
      )}

      {publications && publications.count > 0 && (
        <>
          <h2>Publications</h2>
          <p className="muted">
            Citation graph for this object. Confidence reflects how
            certain we are the publication actually concerns this body
            (high = designation in title, medium = in abstract, low =
            matched only via full-text search).
          </p>
          <PublicationsPanel items={publications.items} />
        </>
      )}
    </section>
  );
}

function Fact({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | number | null | undefined;
  mono?: boolean;
}) {
  if (value == null || value === '') return null;
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : undefined}>{value}</dd>
    </div>
  );
}

function formatDiameter(km: number): string {
  if (km < 1) return `${Math.round(km * 1000)} m`;
  return `${km.toFixed(2)} km`;
}
