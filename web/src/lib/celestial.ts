// Equatorial (RA/Dec) → horizontal (alt/az) conversion, client-side.
//
// Stars are effectively fixed on the celestial sphere, so converting their
// catalog RA/Dec into an observer's local alt/az needs no ephemeris — just
// the local sidereal time (from longitude + UTC) and standard spherical
// trig. This is the textbook conversion; doing it in the browser keeps the
// star catalog a static asset and lets the sky update instantly as the user
// changes location or time.

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

/** Julian Date from a JS Date (UTC). */
export function julianDate(date: Date): number {
  return date.getTime() / 86400000 + 2440587.5;
}

/** Greenwich Mean Sidereal Time in degrees (0..360) for a given JD. */
export function gmstDegrees(jd: number): number {
  const d = jd - 2451545.0;
  const t = d / 36525;
  let gmst =
    280.46061837 +
    360.98564736629 * d +
    0.000387933 * t * t -
    (t * t * t) / 38710000;
  gmst %= 360;
  if (gmst < 0) gmst += 360;
  return gmst;
}

export interface AltAz {
  altitude_deg: number;
  azimuth_deg: number; // from North, increasing eastward (0=N, 90=E, 180=S, 270=W)
}

/**
 * Convert equatorial coordinates to horizontal for an observer.
 *
 * @param raDeg right ascension in degrees (0..360)
 * @param decDeg declination in degrees (−90..90)
 * @param latDeg observer latitude
 * @param lonDeg observer longitude (east positive)
 * @param when observation time
 */
export function equatorialToHorizontal(
  raDeg: number,
  decDeg: number,
  latDeg: number,
  lonDeg: number,
  when: Date,
): AltAz {
  const jd = julianDate(when);
  const lst = (gmstDegrees(jd) + lonDeg) % 360; // local sidereal time, deg
  let haDeg = lst - raDeg; // hour angle
  haDeg = ((haDeg % 360) + 360) % 360;

  const ha = haDeg * DEG;
  const dec = decDeg * DEG;
  const lat = latDeg * DEG;

  const sinAlt =
    Math.sin(lat) * Math.sin(dec) + Math.cos(lat) * Math.cos(dec) * Math.cos(ha);
  const alt = Math.asin(Math.max(-1, Math.min(1, sinAlt)));

  // Azimuth from North, eastward.
  const cosAz =
    (Math.sin(dec) - Math.sin(lat) * sinAlt) / (Math.cos(lat) * Math.cos(alt));
  let az = Math.acos(Math.max(-1, Math.min(1, cosAz)));
  if (Math.sin(ha) > 0) az = 2 * Math.PI - az;

  return { altitude_deg: alt * RAD, azimuth_deg: (az * RAD) % 360 };
}

/**
 * Convert an alt/az direction to a 3D unit vector for the sky dome.
 *
 * Convention (Y-up, observer at origin looking out):
 *   zenith (alt 90)  → +Y
 *   North  (az 0)    → −Z
 *   East   (az 90)   → +X
 *   South  (az 180)  → +Z
 *   West   (az 270)  → −X
 *
 * Returned as a plain [x, y, z] so this module stays free of a three.js
 * import; callers wrap it in a Vector3.
 */
export function altAzToVector3(
  altitudeDeg: number,
  azimuthDeg: number,
  radius = 1,
): [number, number, number] {
  const alt = altitudeDeg * DEG;
  const az = azimuthDeg * DEG;
  const cosAlt = Math.cos(alt);
  return [
    radius * cosAlt * Math.sin(az), // +X east
    radius * Math.sin(alt), // +Y up
    -radius * cosAlt * Math.cos(az), // −Z north
  ];
}
