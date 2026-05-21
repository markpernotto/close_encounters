import { useId } from 'react';
import { asteroidVisual, seedFromString } from '../lib/asteroidVisual';

interface Props {
  designation: string;
  specClass: string | null;
  albedo: number | null;
  diameterKm: number | null;
  diameterEstimateKm: number | null;
  rotationPeriodH: number | null;
}

// A procedural, composition-driven portrait of the body: an SVG lit sphere
// tinted by taxonomy + albedo, with fractal-noise surface mottling. No image
// assets — everything is derived from the object's measured properties.
export default function AsteroidRender({
  designation,
  specClass,
  albedo,
  diameterKm,
  diameterEstimateKm,
  rotationPeriodH,
}: Props) {
  const v = asteroidVisual(specClass, albedo);
  const seed = seedFromString(designation);
  const uid = useId().replace(/:/g, '');
  const gid = `grad-${uid}`;
  const fid = `tex-${uid}`;
  const cid = `clip-${uid}`;
  const freq = (0.6 + v.roughness * 0.9).toFixed(2);

  const diameter = diameterKm ?? diameterEstimateKm;
  const diameterEstimated = diameterKm == null && diameterEstimateKm != null;

  return (
    <section className="asteroid-render">
      <svg
        viewBox="0 0 200 200"
        className="asteroid-svg"
        role="img"
        aria-label={`Procedural ${v.groupLabel} rendering of ${designation}`}
      >
        <defs>
          <radialGradient id={gid} cx="36%" cy="32%" r="80%">
            <stop offset="0%" stopColor={v.litHex} />
            <stop offset="55%" stopColor={v.baseHex} />
            <stop offset="100%" stopColor={v.shadowHex} />
          </radialGradient>
          <filter id={fid} x="0" y="0" width="100%" height="100%">
            <feTurbulence
              type="fractalNoise"
              baseFrequency={freq}
              numOctaves="3"
              seed={seed}
              result="n"
            />
            <feColorMatrix in="n" type="saturate" values="0" />
          </filter>
          <clipPath id={cid}>
            <circle cx="100" cy="100" r="94" />
          </clipPath>
        </defs>
        <g clipPath={`url(#${cid})`}>
          <circle cx="100" cy="100" r="94" fill={`url(#${gid})`} />
          {/* Procedural surface mottling — grayscale noise blended over the
              lit sphere reads as craters and regolith variation. */}
          <rect
            x="0"
            y="0"
            width="200"
            height="200"
            filter={`url(#${fid})`}
            opacity={0.22}
            style={{ mixBlendMode: 'overlay' }}
          />
        </g>
        <circle
          cx="100"
          cy="100"
          r="94"
          fill="none"
          stroke="rgba(0,0,0,0.35)"
          strokeWidth="1"
        />
      </svg>

      <div className="asteroid-render-text">
        <div className="asteroid-group">{v.groupLabel}</div>
        <p className="asteroid-desc">{v.description}</p>
        <ul className="asteroid-stats">
          {diameter != null && (
            <li>
              ~{formatKm(diameter)} across{diameterEstimated ? ' (estimated)' : ''}
            </li>
          )}
          {rotationPeriodH != null && (
            <li>rotates once every {formatHours(rotationPeriodH)}</li>
          )}
        </ul>
        {!v.characterized && (
          <p className="asteroid-note muted">
            No spectral type or albedo on record — this is a generic stand-in,
            not a depiction of measured composition.
          </p>
        )}
        {v.characterized && (
          <p className="asteroid-note muted">
            Color and brightness are derived from this object's measured
            spectral class and albedo; surface detail is illustrative.
          </p>
        )}
      </div>
    </section>
  );
}

function formatKm(km: number): string {
  if (km < 1) return `${Math.round(km * 1000)} m`;
  return `${km.toFixed(km < 10 ? 2 : 1)} km`;
}

function formatHours(h: number): string {
  if (h < 1) return `${Math.round(h * 60)} minutes`;
  if (h < 48) return `${h.toFixed(1)} hours`;
  return `${(h / 24).toFixed(1)} days`;
}
