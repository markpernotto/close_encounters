import type { OrbitRevisionItem } from '../types';

interface Props {
  revisions: OrbitRevisionItem[];
}

export default function OrbitHistoryTimeline({ revisions }: Props) {
  if (revisions.length === 0) {
    return (
      <p className="empty">
        No orbit-determination revisions recorded yet for this object.
      </p>
    );
  }

  // Reverse so newest revision is at the top
  const items = [...revisions].reverse();

  return (
    <ol className="orbit-timeline">
      {items.map((r, i) => (
        <li
          key={`${r.solution_date}-${i}`}
          className={`orbit-rev ${r.is_current ? 'current' : ''}`}
        >
          <header className="orbit-rev-head">
            <span className="orbit-rev-date mono">{r.solution_date}</span>
            {r.is_current && <span className="tag tag-current">current</span>}
          </header>
          <dl className="orbit-rev-facts">
            <Fact label="e" value={r.eccentricity?.toFixed(6)} />
            <Fact label="a (AU)" value={r.semi_major_axis_au?.toFixed(6)} />
            <Fact label="i (°)" value={r.inclination_deg?.toFixed(3)} />
            {r.sigma_a != null && (
              <Fact label="σa" value={r.sigma_a.toExponential(2)} mono />
            )}
            <Fact
              label="Valid"
              value={
                r.is_current
                  ? `${r.valid_from} → now`
                  : `${r.valid_from} → ${r.valid_to ?? '—'}`
              }
              mono
            />
          </dl>
        </li>
      ))}
    </ol>
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
    <div className="orbit-fact">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : undefined}>{value}</dd>
    </div>
  );
}
