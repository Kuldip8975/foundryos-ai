import { useId } from 'react';

/**
 * One headline figure.
 *
 * label  — what is measured (sentence case)
 * value  — already formatted for display
 * unit   — optional unit shown after the value (e.g. "units")
 * detail — supporting context (denominator, breakdown)
 * definition — how the figure is calculated; read out with the value
 * tone   — optional 'ok' | 'warn' | 'bad' accent, always paired with text
 */
export function KpiCard({ label, value, unit, detail, definition, tone, loading = false }) {
  const labelId = useId();
  const definitionId = useId();
  return (
    <div
      className={`kpi${tone ? ` kpi--${tone}` : ''}`}
      role="group"
      aria-labelledby={labelId}
      aria-describedby={definition ? definitionId : undefined}
      aria-busy={loading}
    >
      <p id={labelId} className="kpi__label">
        {label}
      </p>
      <p className="kpi__value">
        {loading ? (
          <span className="skeleton__line skeleton__line--value" />
        ) : (
          <>
            {value}
            {unit && <span className="kpi__unit"> {unit}</span>}
          </>
        )}
      </p>
      {detail && <p className="kpi__detail">{loading ? '\u00a0' : detail}</p>}
      {definition && (
        <p id={definitionId} className="kpi__definition">
          {definition}
        </p>
      )}
    </div>
  );
}