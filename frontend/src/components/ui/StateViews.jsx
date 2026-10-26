import { describeApiError } from '../../lib/errors.js';

/** Inline loading indicator; announced politely to screen readers. */
export function LoadingState({ label = 'Loading…' }) {
  return (
    <div className="state state--loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

/** Placeholder blocks shown while the first response is loading. */
export function Skeleton({ lines = 3 }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton__line" />
      ))}
    </div>
  );
}

/** Small "no data" message inside a card. */
export function EmptyMessage({ children }) {
  return <p className="state state--empty">{children}</p>;
}

/** API failure with an optional retry action. */
export function ErrorCallout({ error, onRetry, compact = false }) {
  const { title, message, requestId, validation } = describeApiError(error);
  return (
    <div className={`callout ${validation ? 'callout--warn' : 'callout--bad'}`} role="alert">
      <strong>{title}.</strong> {!compact && message}
      {requestId && <span className="muted"> (request id {requestId})</span>}
      {onRetry && (
        <div className="callout__actions">
          <button type="button" className="button button--small" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}