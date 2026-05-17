import { Link } from 'react-router-dom';
import type { AlertItem } from '../types';

const RULE_LABELS: Record<string, string> = {
  size_and_distance: 'Sizeable object inside the lunar distance',
  very_close_any_size: 'Very close, any size',
  short_arc_late_warning: 'Newly-discovered, short observation arc',
  risk_class_change: 'Risk class change',
};

export default function AlertsTable({ items }: { items: AlertItem[] }) {
  if (items.length === 0) {
    return (
      <p className="empty">
        No noteworthy approaches in the current snapshot. The catalog has many close passes;
        only the ones that cross our threshold rules show up here. See{' '}
        <Link to="/">Upcoming</Link> for the full list, or{' '}
        <a href="/ALERT_RULES.md">the rule definitions</a>.
      </p>
    );
  }

  return (
    <ul className="alerts">
      {items.map((a) => (
        <li key={a.alert_id} className="alert">
          <header className="alert-head">
            <span className="alert-rule">{RULE_LABELS[a.rule_id] ?? a.rule_id}</span>
            <span className="muted mono">fired {formatDate(a.fired_at)}</span>
          </header>
          <p className="alert-rationale">{a.rationale}</p>
          <footer className="alert-foot">
            {a.designation && (
              <Link to={`/objects/${encodeURIComponent(a.designation)}`} className="mono">
                {a.designation}
              </Link>
            )}
            {!a.designation && <span className="mono">spkid {a.spkid}</span>}
            <span className="muted">
              approach {formatDate(a.approach_date)}
            </span>
          </footer>
        </li>
      ))}
    </ul>
  );
}

function formatDate(iso: string): string {
  return iso.replace('T', ' ').replace(/:\d{2}(\.\d+)?(?=[+-Z])/, '');
}
