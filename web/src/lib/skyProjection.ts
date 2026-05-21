// Sky projection + visual mapping for the all-sky chart.
//
// Projection: azimuthal equidistant, "look-up" orientation. The chart is a
// unit circle. Zenith (altitude 90°) is the center; the horizon (altitude
// 0°) is the edge. North is up; East is to the LEFT — the convention for a
// chart you hold overhead facing north, so it matches the real sky rather
// than a ground map.
//
// Visual mapping follows exoplanet_citation's procedural philosophy: let the
// measured data drive the rendering. Marker size scales with diameter;
// color encodes hazard class.

import type { SkyObject } from '../types';

export interface ChartPoint {
  x: number; // -1..1, +x = right (West)
  y: number; // -1..1, +y = down (South), SVG-friendly
}

/** Project an alt/az position to a point on the unit-circle chart. */
export function altAzToChart(altitudeDeg: number, azimuthDeg: number): ChartPoint {
  // radius: 0 at zenith, 1 at horizon
  const r = Math.max(0, Math.min(1, (90 - altitudeDeg) / 90));
  const az = (azimuthDeg * Math.PI) / 180;
  // North (az 0) → up (−y); East (az 90) → left (−x); look-up convention.
  return { x: -r * Math.sin(az), y: -r * Math.cos(az) };
}

/** Altitude ring radii to draw as reference circles (degrees → unit radius). */
export const ALTITUDE_RINGS = [
  { altitude: 60, radius: (90 - 60) / 90 },
  { altitude: 30, radius: (90 - 30) / 90 },
  { altitude: 0, radius: 1 },
];

/** Cardinal direction label positions on the horizon (look-up convention). */
export const CARDINALS: { label: string; point: ChartPoint }[] = [
  { label: 'N', point: altAzToChart(0, 0) },
  { label: 'E', point: altAzToChart(0, 90) },
  { label: 'S', point: altAzToChart(0, 180) },
  { label: 'W', point: altAzToChart(0, 270) },
];

export type HazardClass = 'pha' | 'neo' | 'other';

// Only the hazard flags are needed — accept any object carrying them (a full
// SkyObject or a SkyObjectTrack), not just SkyObject.
type HazardFields = Pick<SkyObject, 'pha' | 'neo'>;
type SizeFields = Pick<SkyObject, 'diameter_km'>;

export function hazardClass(obj: HazardFields): HazardClass {
  if (obj.pha) return 'pha';
  if (obj.neo) return 'neo';
  return 'other';
}

/** Marker color by hazard class — the one visual channel that carries
 * meaning. PHAs (potentially hazardous) stand out warm; NEOs cool; the
 * rest neutral. */
export function hazardColor(obj: HazardFields): string {
  switch (hazardClass(obj)) {
    case 'pha':
      return '#d9603b'; // warm orange-red
    case 'neo':
      return '#4f9fd6'; // cool blue
    default:
      return '#9a9a90'; // neutral
  }
}

/** Marker radius (in chart-unit terms, scaled by the SVG later) from
 * diameter. Log-scaled so a 10 km body isn't 1000× a 10 m one, with a
 * floor so tiny/unknown objects stay visible. */
export function markerRadius(obj: SizeFields): number {
  const km = obj.diameter_km;
  if (km == null || km <= 0) return 0.9; // unknown size → small but visible
  // log10(km) maps roughly [-3 (1 m) .. 1 (10 km)] → scale into [0.7 .. 2.4]
  const logKm = Math.log10(km);
  const t = Math.max(0, Math.min(1, (logKm + 3) / 4));
  return 0.7 + t * 1.7;
}
