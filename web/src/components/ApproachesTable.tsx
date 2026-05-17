import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { ApproachItem } from '../types';

type SortKey =
  | 'approach_date'
  | 'distance_ld'
  | 'v_rel_km_s'
  | 'diameter_estimate_km'
  | 'designation';

type SortDir = 'asc' | 'desc';

interface Props {
  items: ApproachItem[];
  initialSort?: { key: SortKey; dir: SortDir };
}

export default function ApproachesTable({ items, initialSort }: Props) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>(
    initialSort ?? { key: 'approach_date', dir: 'asc' },
  );

  const sorted = useMemo(() => {
    const copy = [...items];
    copy.sort((a, b) => compare(a, b, sort.key, sort.dir));
    return copy;
  }, [items, sort]);

  function toggleSort(key: SortKey) {
    setSort((prev) =>
      prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
    );
  }

  if (items.length === 0) {
    return <p className="empty">No approaches in this window.</p>;
  }

  return (
    <table className="approaches">
      <thead>
        <tr>
          <Th sort={sort} k="designation" onClick={toggleSort}>
            Object
          </Th>
          <Th sort={sort} k="approach_date" onClick={toggleSort}>
            Approach (UTC)
          </Th>
          <Th sort={sort} k="distance_ld" onClick={toggleSort} align="right">
            Distance (LD)
          </Th>
          <Th sort={sort} k="v_rel_km_s" onClick={toggleSort} align="right">
            Velocity (km/s)
          </Th>
          <Th sort={sort} k="diameter_estimate_km" onClick={toggleSort} align="right">
            Est. diameter
          </Th>
          <th>Orbit class</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={`${r.spkid}-${r.approach_date}`}>
            <td>
              <Link to={`/objects/${encodeURIComponent(r.designation)}`} className="mono">
                {r.designation || r.spkid}
              </Link>
              {r.full_name && r.full_name !== r.designation && (
                <span className="muted"> · {r.full_name}</span>
              )}
            </td>
            <td className="mono">{formatDate(r.approach_date)}</td>
            <td className="num">{formatLD(r.distance_ld)}</td>
            <td className="num">{formatNumber(r.v_rel_km_s, 1)}</td>
            <td className="num">{formatDiameter(r.diameter_estimate_km)}</td>
            <td>{r.orbit_class ?? <span className="muted">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Th({
  sort,
  k,
  onClick,
  align,
  children,
}: {
  sort: { key: SortKey; dir: SortDir };
  k: SortKey;
  onClick: (k: SortKey) => void;
  align?: 'right';
  children: React.ReactNode;
}) {
  const active = sort.key === k;
  return (
    <th className={align === 'right' ? 'num' : undefined}>
      <button
        type="button"
        className={`sort-btn ${active ? 'active' : ''}`}
        onClick={() => onClick(k)}
        aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
      >
        {children}
        <span className="sort-indicator">{active ? (sort.dir === 'asc' ? '▲' : '▼') : ''}</span>
      </button>
    </th>
  );
}

function compare(a: ApproachItem, b: ApproachItem, key: SortKey, dir: SortDir): number {
  const av = a[key];
  const bv = b[key];
  // Nulls sort last regardless of direction.
  if (av == null && bv == null) return 0;
  if (av == null) return 1;
  if (bv == null) return -1;
  const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv));
  return dir === 'asc' ? cmp : -cmp;
}

function formatDate(iso: string): string {
  // Trim seconds; keep timezone in the displayed form so users know UTC.
  return iso.replace('T', ' ').replace(/:\d{2}(\.\d+)?(?=[+-Z])/, '');
}

function formatNumber(v: number | null, digits = 2): string {
  return v == null ? '—' : v.toFixed(digits);
}

function formatLD(v: number | null): string {
  return v == null ? '—' : v.toFixed(2);
}

function formatDiameter(km: number | null): string {
  if (km == null) return '—';
  if (km < 1) return `${Math.round(km * 1000)} m`;
  return `${km.toFixed(2)} km`;
}
