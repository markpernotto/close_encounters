import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ALTITUDE_RINGS,
  CARDINALS,
  altAzToChart,
  hazardColor,
  markerRadius,
} from '../lib/skyProjection';
import type { SkyObject } from '../types';

interface Props {
  objects: SkyObject[];
}

// SVG coordinate space: a square viewBox centered at (0,0) with the
// horizon circle at radius R. Chart-unit coords (-1..1) scale by R.
const R = 180;
const PAD = 28; // room for cardinal labels outside the horizon
const SIZE = (R + PAD) * 2;

export default function AllSkyChart({ objects }: Props) {
  const navigate = useNavigate();
  const [hovered, setHovered] = useState<SkyObject | null>(null);

  return (
    <div className="allsky-wrap">
      <svg
        className="allsky"
        viewBox={`${-R - PAD} ${-R - PAD} ${SIZE} ${SIZE}`}
        role="img"
        aria-label="All-sky chart of objects above the horizon"
      >
        {/* Sky disc */}
        <circle cx={0} cy={0} r={R} className="allsky-disc" />

        {/* Altitude rings */}
        {ALTITUDE_RINGS.map((ring) => (
          <circle
            key={ring.altitude}
            cx={0}
            cy={0}
            r={ring.radius * R}
            className="allsky-ring"
          />
        ))}

        {/* Cardinal cross + labels */}
        <line x1={-R} y1={0} x2={R} y2={0} className="allsky-cross" />
        <line x1={0} y1={-R} x2={0} y2={R} className="allsky-cross" />
        {CARDINALS.map((c) => (
          <text
            key={c.label}
            x={c.point.x * (R + 14)}
            y={c.point.y * (R + 14)}
            className="allsky-cardinal"
            textAnchor="middle"
            dominantBaseline="middle"
          >
            {c.label}
          </text>
        ))}

        {/* Objects */}
        {objects.map((obj) => {
          const p = altAzToChart(obj.altitude_deg, obj.azimuth_deg);
          return (
            <circle
              key={`${obj.spkid}`}
              cx={p.x * R}
              cy={p.y * R}
              r={markerRadius(obj)}
              fill={hazardColor(obj)}
              className="allsky-object"
              onMouseEnter={() => setHovered(obj)}
              onMouseLeave={() => setHovered(null)}
              onClick={() =>
                navigate(`/objects/${encodeURIComponent(obj.designation)}`)
              }
            >
              <title>
                {obj.designation} — alt {obj.altitude_deg.toFixed(0)}°, az{' '}
                {obj.azimuth_deg.toFixed(0)}°
              </title>
            </circle>
          );
        })}

        {/* Zenith marker */}
        <circle cx={0} cy={0} r={1.5} className="allsky-zenith" />
      </svg>

      <div className="allsky-readout">
        {hovered ? (
          <>
            <span className="mono">{hovered.designation}</span>
            {hovered.full_name && hovered.full_name !== hovered.designation && (
              <span className="muted"> · {hovered.full_name}</span>
            )}
            <br />
            <span className="muted">
              altitude {hovered.altitude_deg.toFixed(1)}° · azimuth{' '}
              {hovered.azimuth_deg.toFixed(1)}° · {hovered.distance_au.toFixed(3)} AU
              {hovered.pha && ' · PHA'}
            </span>
          </>
        ) : (
          <span className="muted">
            Hover a marker for details; click to open the object.{' '}
            Center = straight up, edge = horizon.
          </span>
        )}
      </div>

      <ul className="allsky-legend">
        <li>
          <span className="legend-dot" style={{ background: '#d9603b' }} /> potentially hazardous
        </li>
        <li>
          <span className="legend-dot" style={{ background: '#4f9fd6' }} /> near-Earth object
        </li>
        <li>
          <span className="legend-dot" style={{ background: '#9a9a90' }} /> other
        </li>
        <li className="muted">marker size ∝ diameter</li>
      </ul>
    </div>
  );
}
