import { useState } from 'react';

export interface LatLon {
  lat: number;
  lon: number;
  label: string;
}

// A few notable dark-sky / observatory spots to make "somewhere else"
// one click. Central Oregon (this project's home turf) leads.
const PRESETS: LatLon[] = [
  { label: 'Sisters, OR', lat: 44.29, lon: -121.55 },
  { label: 'Mauna Kea, HI', lat: 19.82, lon: -155.47 },
  { label: 'Atacama, Chile', lat: -24.63, lon: -70.4 },
  { label: 'Siding Spring, AU', lat: -31.27, lon: 149.07 },
  { label: 'La Palma, ES', lat: 28.76, lon: -17.89 },
];

interface Props {
  value: LatLon;
  onChange: (loc: LatLon) => void;
}

export default function LocationPicker({ value, onChange }: Props) {
  const [latInput, setLatInput] = useState(String(value.lat));
  const [lonInput, setLonInput] = useState(String(value.lon));
  const [geoError, setGeoError] = useState<string | null>(null);

  function useMyLocation() {
    setGeoError(null);
    if (!('geolocation' in navigator)) {
      setGeoError('Geolocation not available in this browser.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = +pos.coords.latitude.toFixed(4);
        const lon = +pos.coords.longitude.toFixed(4);
        setLatInput(String(lat));
        setLonInput(String(lon));
        onChange({ lat, lon, label: 'My location' });
      },
      (err) => setGeoError(err.message || 'Could not get your location.'),
      { timeout: 10000 },
    );
  }

  function applyManual() {
    const lat = Number(latInput);
    const lon = Number(lonInput);
    if (Number.isNaN(lat) || lat < -90 || lat > 90) {
      setGeoError('Latitude must be between −90 and 90.');
      return;
    }
    if (Number.isNaN(lon) || lon < -180 || lon > 180) {
      setGeoError('Longitude must be between −180 and 180.');
      return;
    }
    setGeoError(null);
    onChange({ lat, lon, label: 'Custom' });
  }

  return (
    <div className="location-picker">
      <div className="location-row">
        <button type="button" className="loc-btn" onClick={useMyLocation}>
          Use my location
        </button>
        <span className="muted">or pick a dark-sky site:</span>
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            className={`loc-preset ${value.label === p.label ? 'active' : ''}`}
            onClick={() => {
              setLatInput(String(p.lat));
              setLonInput(String(p.lon));
              onChange(p);
            }}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="location-row">
        <label className="loc-field">
          lat
          <input
            type="text"
            inputMode="decimal"
            value={latInput}
            onChange={(e) => setLatInput(e.target.value)}
          />
        </label>
        <label className="loc-field">
          lon
          <input
            type="text"
            inputMode="decimal"
            value={lonInput}
            onChange={(e) => setLonInput(e.target.value)}
          />
        </label>
        <button type="button" className="loc-btn" onClick={applyManual}>
          Go
        </button>
        <span className="muted mono">
          {value.lat.toFixed(2)}, {value.lon.toFixed(2)} · {value.label}
        </span>
      </div>

      {geoError && <p className="error">{geoError}</p>}
    </div>
  );
}
