"""Sky-position math for Phase 4 — where is each object right now.

Given an object's osculating orbital elements (which we already store in
mart_objects_current) plus an observer's latitude/longitude and a time,
compute the object's altitude + azimuth in the observer's local sky.

Built on skyfield. Orbits are reconstructed from Keplerian elements via
skyfield's internal _KeplerOrbit constructor — the same one
skyfield.data.mpc.mpcorb_orbit uses — and combined with the JPL DE421
ephemeris for Earth + Sun positions.

The DE421 ephemeris (~17 MB) downloads on first use and caches under
api/_skyfield_data/. For serverless deployment this file should be
bundled with the function rather than downloaded per cold start (a
deployment concern tracked separately).

NOTE: _KeplerOrbit._from_mean_anomaly is a private skyfield API. It has
been stable across releases (mpcorb_orbit depends on it) but is pinned
loosely via skyfield>=1.49 — worth a smoke test after skyfield upgrades.
"""

from __future__ import annotations

import functools
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from skyfield.api import Loader, wgs84
from skyfield.constants import GM_SUN_Pitjeva_2005_km3_s2 as GM_SUN
from skyfield.data.spice import inertial_frames
from skyfield.keplerlib import _KeplerOrbit

EPHEMERIS_FILE = "de421.bsp"
_DATA_DIR = Path(__file__).resolve().parent / "_skyfield_data"

# NAIF code for the Sun (the orbits are heliocentric).
_SUN_CENTER = 10


@functools.lru_cache(maxsize=1)
def _loader() -> Loader:
    """A skyfield Loader pointed at the ephemeris.

    Prefer the bundled/committed copy in `_DATA_DIR` (shipped with the Vercel
    function via vercel.json `includeFiles`, or cached locally) — that path is
    read-only in production but needs no writes when the file already exists.
    Only if the file is missing do we fall back to a writable temp dir so a
    download can still succeed (slow, but it won't crash on the read-only
    serverless filesystem)."""
    if (_DATA_DIR / EPHEMERIS_FILE).exists():
        return Loader(str(_DATA_DIR))
    tmp = Path(tempfile.gettempdir()) / "neo_skyfield"
    tmp.mkdir(parents=True, exist_ok=True)
    return Loader(str(tmp))


@functools.lru_cache(maxsize=1)
def _ephemeris() -> Any:
    return _loader()(EPHEMERIS_FILE)


@functools.lru_cache(maxsize=1)
def _timescale() -> Any:
    # skyfield's timescale uses bundled leap-second data; no download.
    return _loader().timescale()


def build_orbit(
    *,
    a_au: float,
    e: float,
    i_deg: float,
    om_deg: float,
    w_deg: float,
    ma_deg: float,
    epoch_jd: float,
    name: str = "",
) -> Any:
    """Reconstruct a heliocentric Kepler orbit from osculating elements.

    Pure: needs only the timescale (bundled), not the ephemeris download.
    """
    p = a_au * (1.0 - e * e)  # semi-latus rectum
    t_epoch = _timescale().tt_jd(epoch_jd)
    orbit = _KeplerOrbit._from_mean_anomaly(
        p,
        e,
        i_deg,
        om_deg,
        w_deg,
        ma_deg,
        t_epoch,
        GM_SUN,
        _SUN_CENTER,
        name,
    )
    # Elements are in the J2000 ecliptic frame; rotate into the equatorial
    # frame skyfield works in.
    orbit._rotation = inertial_frames["ECLIPJ2000"].T
    return orbit


def compute_altaz(
    *,
    a_au: float,
    e: float,
    i_deg: float,
    om_deg: float,
    w_deg: float,
    ma_deg: float,
    epoch_jd: float,
    lat: float,
    lon: float,
    when: datetime,
    name: str = "",
) -> dict[str, Any]:
    """Compute the object's local altitude/azimuth for an observer.

    `when` must be timezone-aware. Returns altitude (deg, -90..90),
    azimuth (deg, 0..360), distance (AU), and an above_horizon flag.
    """
    eph = _ephemeris()
    ts = _timescale()
    sun = eph["sun"]
    earth = eph["earth"]

    orbit = build_orbit(
        a_au=a_au, e=e, i_deg=i_deg, om_deg=om_deg, w_deg=w_deg,
        ma_deg=ma_deg, epoch_jd=epoch_jd, name=name,
    )
    body = sun + orbit
    observer = earth + wgs84.latlon(lat, lon)
    t = ts.from_datetime(when)
    alt, az, dist = observer.at(t).observe(body).apparent().altaz()
    return {
        "altitude_deg": float(alt.degrees),
        "azimuth_deg": float(az.degrees),
        "distance_au": float(dist.au),
        "above_horizon": bool(alt.degrees > 0),
    }


def objects_above_horizon(
    objects: list[dict[str, Any]],
    *,
    lat: float,
    lon: float,
    when: datetime,
    min_altitude_deg: float = 0.0,
) -> list[dict[str, Any]]:
    """For a list of objects (each carrying orbital elements), return those
    above the given altitude threshold, each annotated with its alt/az.

    Objects missing any required element are skipped silently — we can't
    place them without a full element set, and a partial sky is better
    than an error.
    """
    result: list[dict[str, Any]] = []
    for obj in objects:
        elements = _extract_elements(obj)
        if elements is None:
            continue
        try:
            position = compute_altaz(
                **elements,
                lat=lat,
                lon=lon,
                when=when,
                name=str(obj.get("designation") or obj.get("spkid") or ""),
            )
        except Exception:  # noqa: BLE001 — a single bad orbit shouldn't 500 the sky
            continue
        if position["altitude_deg"] < min_altitude_deg:
            continue
        result.append({**obj, **position})
    result.sort(key=lambda o: o["altitude_deg"], reverse=True)
    return result


def time_axis(
    start: datetime, end: datetime, step_minutes: int
) -> list[datetime]:
    """The shared list of sample times from start..end (inclusive) at the step.

    Both bounds must be timezone-aware. At least two samples are returned even
    if the window is shorter than one step."""
    if step_minutes <= 0:
        raise ValueError("step_minutes must be positive")
    total_min = (end - start).total_seconds() / 60.0
    steps = max(1, int(total_min // step_minutes))
    return [start + timedelta(minutes=step_minutes * i) for i in range(steps + 1)]


def object_tracks(
    objects: list[dict[str, Any]],
    *,
    lat: float,
    lon: float,
    start: datetime,
    end: datetime,
    step_minutes: int = 30,
    min_altitude_deg: float = 0.0,
) -> dict[str, Any]:
    """Compute each object's alt/az track across a time window.

    For every object carrying a full element set, propagate its position at
    every sample time on a shared axis (vectorised through skyfield in one
    call per object). Objects that never rise above `min_altitude_deg`
    anywhere in the window are dropped, so the client only animates things
    that actually appear.

    Returns a dict with the shared time axis (`start`, `step_minutes`,
    `steps`) and, per object, a `samples` list of [alt_deg, az_deg, dist_au]
    aligned to that axis. Altitude/azimuth below the horizon are kept (not
    nulled) so the client can interpolate a continuous path and hide it
    itself."""
    eph = _ephemeris()
    ts = _timescale()
    sun = eph["sun"]
    earth = eph["earth"]
    observer = earth + wgs84.latlon(lat, lon)

    times = time_axis(start, end, step_minutes)
    t_array = ts.from_datetimes(times)

    tracks: list[dict[str, Any]] = []
    for obj in objects:
        elements = _extract_elements(obj)
        if elements is None:
            continue
        try:
            orbit = build_orbit(
                **elements,
                name=str(obj.get("designation") or obj.get("spkid") or ""),
            )
            body = sun + orbit
            alt, az, dist = observer.at(t_array).observe(body).apparent().altaz()
            alts = [float(v) for v in alt.degrees]
            azs = [float(v) for v in az.degrees]
            dists = [float(v) for v in dist.au]
        except Exception:  # noqa: BLE001 — one bad orbit shouldn't 500 the track
            continue
        if max(alts) < min_altitude_deg:
            continue
        samples = [
            [round(a, 3), round(z, 3), round(d, 6)]
            for a, z, d in zip(alts, azs, dists, strict=True)
        ]
        tracks.append({**obj, "samples": samples})

    # Brightest/biggest-first is a reasonable default ordering for the legend;
    # fall back to designation for stability.
    tracks.sort(
        key=lambda o: (-(o.get("diameter_km") or 0.0), str(o.get("designation") or ""))
    )
    return {
        "start": times[0],
        "step_minutes": step_minutes,
        "steps": len(times),
        "objects": tracks,
    }


def _extract_elements(obj: dict[str, Any]) -> dict[str, float] | None:
    """Pull the six elements + epoch from a mart_objects_current row.
    Returns None if any are missing."""
    mapping = {
        "a_au": obj.get("semi_major_axis_au"),
        "e": obj.get("eccentricity"),
        "i_deg": obj.get("inclination_deg"),
        "om_deg": obj.get("longitude_ascending_node_deg"),
        "w_deg": obj.get("argument_perihelion_deg"),
        "ma_deg": obj.get("mean_anomaly_deg"),
        "epoch_jd": obj.get("latest_epoch_jd"),
    }
    if any(v is None for v in mapping.values()):
        return None
    return {k: float(v) for k, v in mapping.items()}
