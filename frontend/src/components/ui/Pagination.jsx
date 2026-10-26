import { formatNumber } from '../../lib/format.js';

/** Offset pagination matching the API envelope { total, limit, offset }. */
export function Pagination({ total, limit, offset, onChange, disabled = false, label = 'Pagination' }) {
  if (total === 0) return null;
  const first = offset + 1;
  const last = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;
  return (
    <nav className="pagination" aria-label={label}>
      <span className="muted">
        Showing {formatNumber(first)}–{formatNumber(last)} of {formatNumber(total)}
      </span>
      <div className="pagination__buttons">
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={disabled || !hasPrevious}
        >
          Previous
        </button>
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={() => onChange(offset + limit)}
          disabled={disabled || !hasNext}
        >
          Next
        </button>
      </div>
    </nav>
  );
}