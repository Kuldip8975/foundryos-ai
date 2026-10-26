import { StatusBadge } from '../StatusBadge.jsx';
import { DataTable } from '../ui/DataTable.jsx';
import { formatDateTime, humanize } from '../../lib/format.js';

export const TOOL_LABELS = {
  get_machine_status: 'Machine status',
  query_downtime: 'Downtime query',
  get_production_quality_metrics: 'Production & quality metrics',
  list_maintenance_requests: 'Maintenance requests',
  prepare_maintenance_request: 'Prepare maintenance request',
};

export function toolLabel(tool) {
  return TOOL_LABELS[tool] ?? `Unknown tool “${tool}”`;
}

const MAX_JSON_CHARS = 6000;

function JsonBlock({ value, label }) {
  let text = JSON.stringify(value, null, 2) ?? '';
  if (text.length > MAX_JSON_CHARS) text = `${text.slice(0, MAX_JSON_CHARS)}\n… (truncated)`;
  return (
    <pre className="json-block" aria-label={label}>
      {text}
    </pre>
  );
}

/** Evidence ids cited by a finding, each shown with the tool result it points to. */
function EvidenceChips({ ids, stepsByEvidence }) {
  return (
    <ul className="evidence" aria-label="Evidence">
      {ids.map((id) => {
        const step = stepsByEvidence[id];
        return (
          <li key={id} className="evidence__item">
            <a href={`#evidence-${id}`}>
              <code>{id}</code>
            </a>{' '}
            {step ? toolLabel(step.tool) : 'unknown evidence'}
          </li>
        );
      })}
    </ul>
  );
}

/** The validated final answer. Everything here is AI-written and labelled as such. */
export function AnswerView({ session }) {
  const { answer } = session;
  const stepsByEvidence = Object.fromEntries(
    session.steps.filter((step) => step.evidence_id).map((step) => [step.evidence_id, step]),
  );
  return (
    <article className="answer" aria-label={`Answer ${session.id}`}>
      <p className="ai-label">
        <strong>AI-generated answer.</strong> Written by {session.model ?? 'the AI model'} from the tool results below.
        Each finding cites the results it is based on; check them before acting.
      </p>
      {session.includes_synthetic_data && (
        <p className="callout callout--warn">
          The data used includes <strong>synthetic demonstration records</strong>, not real plant data.
        </p>
      )}
      <p className="answer__text">{answer.answer}</p>
      {answer.findings.length > 0 && (
        <section aria-label="Findings">
          <h4 className="subheading">Findings</h4>
          <ul className="findings">
            {answer.findings.map((finding, index) => (
              <li key={index} className="finding">
                <p>{finding.statement}</p>
                <EvidenceChips ids={finding.evidence} stepsByEvidence={stepsByEvidence} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {answer.limitations.length > 0 && (
        <section className="limitations" aria-label="Limitations">
          <h4 className="subheading">Limitations</h4>
          <ul>
            {answer.limitations.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}

/** Every tool call the model asked for — including refused ones — with its evidence. */
export function StepsView({ steps }) {
  if (steps.length === 0) {
    return <p className="muted small">The assistant answered without calling any tools.</p>;
  }
  return (
    <ol className="steps" aria-label="Tool calls">
      {steps.map((step) => (
        <li key={step.id} id={step.evidence_id ? `evidence-${step.evidence_id}` : undefined} className="step">
          <div className="step__header">
            <span className="step__title">
              {step.evidence_id && <code className="step__evidence">{step.evidence_id}</code>} {toolLabel(step.tool)}
            </span>
            <StatusBadge status={`step_${step.status}`} />
          </div>
          {step.error_message && (
            <p className="step__error">
              {step.error_message} <span className="muted">({step.error_code})</span>
            </p>
          )}
          <details>
            <summary>Arguments{step.result ? ' and result' : ''}</summary>
            <JsonBlock value={step.arguments} label={`Arguments of step ${step.sequence}`} />
            {step.result && <JsonBlock value={step.result} label={`Result of step ${step.sequence}`} />}
          </details>
        </li>
      ))}
    </ol>
  );
}

/** Append-only audit trail recorded by the server. */
export function AuditTrail({ events }) {
  return (
    <DataTable
      caption="Audit trail"
      columns={[
        { key: 'created_at', header: 'Time', render: (row) => formatDateTime(row.created_at) },
        { key: 'event_type', header: 'Event', render: (row) => humanize(row.event_type) },
        { key: 'actor', header: 'By' },
        {
          key: 'details',
          header: 'Details',
          render: (row) =>
            Object.entries(row.details ?? {})
              .filter(([, value]) => value !== null && value !== undefined)
              .map(([name, value]) => `${humanize(name)}: ${String(value)}`)
              .join(' · ') || '—',
        },
      ]}
      rows={events}
    />
  );
}