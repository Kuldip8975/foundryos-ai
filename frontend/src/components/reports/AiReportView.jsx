import { useMemo } from 'react';
import { StatusBadge } from '../StatusBadge.jsx';
import { flattenMetrics, formatMetricValue } from '../../lib/evidence.js';
import { formatDateTime } from '../../lib/format.js';

const KIND_LABELS = { measured_fact: 'Measured fact', possible_explanation: 'Possible explanation' };
const PRIORITY_LABELS = { high: 'High priority', medium: 'Medium priority', low: 'Low priority' };

/** Cited metric keys shown with the measured value each one refers to. */
function Evidence({ keys, values }) {
  return (
    <ul className="evidence" aria-label="Evidence">
      {keys.map((key) => (
        <li key={key} className="evidence__item">
          <code>{key}</code> = <strong>{key in values ? formatMetricValue(key, values[key]) : 'unknown'}</strong>
        </li>
      ))}
    </ul>
  );
}

function FindingList({ title, findings, values }) {
  return (
    <section className="report-section" aria-label={title}>
      <h4 className="subheading">{title}</h4>
      {findings.length === 0 ? (
        <p className="muted small">No observations.</p>
      ) : (
        <ul className="findings">
          {findings.map((finding, index) => (
            <li key={index} className={`finding finding--${finding.kind}`}>
              <span className={`kind kind--${finding.kind}`}>{KIND_LABELS[finding.kind]}</span>
              <p>{finding.statement}</p>
              <Evidence keys={finding.evidence} values={values} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * A persisted AI shift report. Completed reports show the validated content;
 * failed reports show the safe error recorded by the server.
 */
export function AiReportView({ report }) {
  const values = useMemo(() => flattenMetrics(report.metrics), [report.metrics]);
  const content = report.content;

  return (
    <article className="ai-report" aria-label={`Shift report ${report.id}`}>
      <header className="ai-report__meta">
        <StatusBadge status={`report_${report.status}`} />
        <span className="muted small">
          Report #{report.id} · created {formatDateTime(report.created_at)}
          {report.model ? ` · ${report.provider} / ${report.model}` : ''} · prompt {report.prompt_version}
        </span>
      </header>

      {report.includes_synthetic_data && (
        <p className="callout callout--info" role="note">
          Generated from <strong>synthetic demonstration data</strong> — not real company records.
        </p>
      )}

      {report.status === 'failed' && (
        <div className="callout callout--bad" role="alert">
          <strong>Generation failed.</strong> {report.error_message}{' '}
          <span className="muted">({report.error_code})</span>
        </div>
      )}
      {report.status === 'pending' && (
        <p className="callout callout--warn" role="status">
          This report is still being generated.
        </p>
      )}

      {content && (
        <>
          <div className="ai-label" role="note">
            <strong>AI-generated content.</strong> Numbers are taken from the measured metrics (each
            statement lists the metrics it relies on). “Possible explanation” items are hypotheses,
            not confirmed causes. Verify before acting.
          </div>
          <section className="report-section" aria-label="Executive summary">
            <h4 className="subheading">Executive summary</h4>
            <p className="report-summary">{content.executive_summary}</p>
          </section>
          <FindingList title="Production performance" findings={content.production_performance} values={values} />
          <FindingList title="Quality observations" findings={content.quality_observations} values={values} />
          <FindingList
            title="Downtime and maintenance"
            findings={content.downtime_maintenance_observations}
            values={values}
          />
          <section className="report-section" aria-label="Recommendations">
            <h4 className="subheading">Recommendations</h4>
            {content.recommendations.length === 0 ? (
              <p className="muted small">No recommendations.</p>
            ) : (
              <ol className="recommendations">
                {content.recommendations.map((item, index) => (
                  <li key={index} className={`recommendation recommendation--${item.priority}`}>
                    <StatusBadge status={`priority_${item.priority}`} />
                    <span className="visually-hidden">{PRIORITY_LABELS[item.priority]}: </span>
                    <p>
                      <strong>{item.action}</strong> {item.rationale}
                    </p>
                    <Evidence keys={item.evidence} values={values} />
                  </li>
                ))}
              </ol>
            )}
          </section>
          <section className="report-section" aria-label="Data limitations">
            <h4 className="subheading">Data limitations (as stated by the AI)</h4>
            {content.data_limitations.length === 0 ? (
              <p className="muted small">None stated.</p>
            ) : (
              <ul>
                {content.data_limitations.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
      <p className="muted small fingerprint">
        Data fingerprint <code>{report.input_fingerprint.slice(0, 16)}…</code> — identifies the exact metrics
        snapshot this report was generated from.
      </p>
    </article>
  );
}