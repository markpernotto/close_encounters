import type {
  PublicationConfidence,
  PublicationItem,
  PublicationRelationship,
} from '../types';

const RELATIONSHIP_LABELS: Record<PublicationRelationship, string> = {
  discovery: 'Discovery announcement',
  recovery: 'Recovery',
  follow_up: 'Follow-up',
  risk_assessment: 'Risk assessment',
};

const CONFIDENCE_LABELS: Record<PublicationConfidence, string> = {
  high: 'high confidence',
  medium: 'medium confidence',
  low: 'low confidence',
};

export default function PublicationsPanel({
  items,
}: {
  items: PublicationItem[];
}) {
  if (items.length === 0) {
    return (
      <p className="empty">
        No publications resolved yet for this object. The citation graph is
        built incrementally — see <code>make resolve-citations</code>.
      </p>
    );
  }

  // Group by relationship so discovery sits above follow-ups visually
  const grouped = groupByRelationship(items);

  return (
    <div className="publications">
      {grouped.map(([rel, group]) => (
        <section key={rel} className="publications-group">
          <h3 className="publications-group-head">
            {RELATIONSHIP_LABELS[rel]}{' '}
            <span className="muted">({group.length})</span>
          </h3>
          <ul className="publications-list">
            {group.map((p) => (
              <PublicationCard key={p.publication_id} item={p} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function PublicationCard({ item }: { item: PublicationItem }) {
  return (
    <li className={`publication confidence-${item.confidence}`}>
      <header className="publication-head">
        <a
          href={item.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="publication-title"
        >
          {item.title}
        </a>
        <span className={`confidence-badge confidence-${item.confidence}`}>
          {CONFIDENCE_LABELS[item.confidence]}
        </span>
      </header>
      <p className="publication-meta">
        {item.authors && item.authors.length > 0 && (
          <span className="muted">
            {item.authors.slice(0, 3).join(', ')}
            {item.authors.length > 3 && ` +${item.authors.length - 3}`}
          </span>
        )}
        {item.publication_date && (
          <span className="muted mono"> · {item.publication_date}</span>
        )}
        {item.mpec_id && <span className="mono"> · {item.mpec_id}</span>}
        {item.ads_bibcode && (
          <span className="mono"> · {item.ads_bibcode}</span>
        )}
        {item.doi && <span className="mono"> · doi:{item.doi}</span>}
      </p>
      <p className="publication-reason muted">{item.confidence_reason}</p>
    </li>
  );
}

function groupByRelationship(
  items: PublicationItem[],
): [PublicationRelationship, PublicationItem[]][] {
  const order: PublicationRelationship[] = [
    'discovery',
    'recovery',
    'risk_assessment',
    'follow_up',
  ];
  const groups: Record<PublicationRelationship, PublicationItem[]> = {
    discovery: [],
    recovery: [],
    risk_assessment: [],
    follow_up: [],
  };
  for (const item of items) {
    if (groups[item.relationship]) groups[item.relationship].push(item);
  }
  return order
    .filter((rel) => groups[rel].length > 0)
    .map((rel) => [rel, groups[rel]]);
}
