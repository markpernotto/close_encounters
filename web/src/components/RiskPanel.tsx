import type { AgencyRisk, RiskAssessmentItem } from '../types';

interface Props {
  risk: RiskAssessmentItem;
}

export default function RiskPanel({ risk }: Props) {
  return (
    <section className="risk-panel">
      <header className="risk-head">
        <h3>Cross-agency impact risk</h3>
        <span className="risk-coverage">{coverageLabel(risk.coverage)}</span>
        <span className="muted mono"> · {risk.assessment_date}</span>
      </header>

      <div className="risk-grid">
        <AgencyCard
          label="NASA Sentry"
          accent="usa"
          risk={risk.nasa}
        />
        <AgencyCard
          label="ESA NEOCC"
          accent="eu"
          risk={risk.esa}
        />
      </div>

      {risk.delta_palermo != null && risk.coverage === 'both' && (
        <p className="risk-delta">
          NASA minus ESA Palermo:{' '}
          <strong className="mono">
            {risk.delta_palermo >= 0 ? '+' : ''}
            {risk.delta_palermo.toFixed(3)}
          </strong>
          {Math.abs(risk.delta_palermo) > 0.1 && (
            <span className="muted">
              {' '}
              — meaningful disagreement between the agencies on this object
            </span>
          )}
        </p>
      )}

      {(risk.potential_impact_year_min != null ||
        risk.potential_impact_year_max != null) && (
        <p className="risk-window muted">
          Potential impact window:{' '}
          <span className="mono">
            {risk.potential_impact_year_min}
            {risk.potential_impact_year_max !== risk.potential_impact_year_min &&
              `–${risk.potential_impact_year_max}`}
          </span>
        </p>
      )}
    </section>
  );
}

function AgencyCard({
  label,
  accent,
  risk,
}: {
  label: string;
  accent: string;
  risk: AgencyRisk | null;
}) {
  if (!risk) {
    return (
      <div className={`agency-card agency-${accent} agency-empty`}>
        <header>{label}</header>
        <p className="muted">not tracked</p>
      </div>
    );
  }
  return (
    <div className={`agency-card agency-${accent}`}>
      <header>{label}</header>
      <dl>
        <Stat label="Torino" value={risk.torino_scale?.toString() ?? '—'} />
        <Stat
          label="Palermo (cum)"
          value={risk.palermo_scale?.toFixed(3) ?? '—'}
          mono
        />
        {risk.palermo_scale_max != null &&
          risk.palermo_scale_max !== risk.palermo_scale && (
            <Stat
              label="Palermo (max)"
              value={risk.palermo_scale_max.toFixed(3)}
              mono
            />
          )}
        <Stat
          label="Impact prob."
          value={
            risk.impact_probability != null
              ? risk.impact_probability.toExponential(2)
              : '—'
          }
          mono
        />
        {risk.n_impacts != null && (
          <Stat label="Scenarios" value={risk.n_impacts.toString()} />
        )}
      </dl>
    </div>
  );
}

function Stat({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="agency-stat">
      <dt>{label}</dt>
      <dd className={mono ? 'mono' : undefined}>{value}</dd>
    </div>
  );
}

function coverageLabel(coverage: string): string {
  if (coverage === 'both') return 'Tracked by both NASA and ESA';
  if (coverage === 'NASA only') return 'NASA Sentry only';
  if (coverage === 'ESA only') return 'ESA NEOCC only';
  return coverage;
}
