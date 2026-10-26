import { StatusBadge } from './StatusBadge.jsx';

const CHECK_LABELS = {
  database: 'PostgreSQL database',
  migrations: 'Database migrations',
};

function ChecksTable({ checks }) {
  return (
    <table className="checks">
      <thead>
        <tr>
          <th scope="col">Component</th>
          <th scope="col">Status</th>
          <th scope="col">Latency</th>
          <th scope="col">Detail</th>
        </tr>
      </thead>
      <tbody>
        {checks.map((c) => (
          <tr key={c.name}>
            <td>{CHECK_LABELS[c.name] ?? c.name}</td>
            <td>
              <StatusBadge status={c.status} />
            </td>
            <td className="num">{c.latency_ms != null ? `${c.latency_ms} ms` : '—'}</td>
            <td>{c.detail ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Presentational panel for backend connectivity. All data comes from the
 * live /health endpoints via useBackendStatus — nothing here is simulated.
 */
export function BackendStatusPanel({ status }) {
  const { phase, liveness, readiness, error, checkedAt, refresh } = status;

  return (
    <section className="panel" aria-labelledby="backend-status-title" aria-busy={phase === 'loading'}>
      <header className="panel__header">
        <h2 id="backend-status-title">Backend connectivity</h2>
        <StatusBadge status={phase} />
      </header>

      {phase === 'loading' && (
        <p className="muted" role="status">
          Contacting the FoundryOS API…
        </p>
      )}

      {phase === 'misconfigured' && (
        <div className="callout callout--bad" role="alert">
          <strong>Frontend configuration error.</strong> {error?.message}
        </div>
      )}

      {phase === 'unreachable' && (
        <div className="callout callout--bad" role="alert">
          <strong>Cannot reach the API.</strong> {error?.message}
          {error?.requestId && <span className="muted"> (request id {error.requestId})</span>}
          <p className="muted">Check that the backend is running and that VITE_API_BASE_URL and CORS_ALLOWED_ORIGINS match.</p>
        </div>
      )}

      {(phase === 'ready' || phase === 'not_ready') && (
        <>
          <p>
            {liveness.service} API v{liveness.version} · environment <code>{liveness.environment}</code>
          </p>
          {phase === 'not_ready' && (
            <div className="callout callout--warn" role="alert">
              The API is running but is not ready to serve data. See the failing check below.
            </div>
          )}
          <ChecksTable checks={readiness.checks} />
        </>
      )}

      <footer className="panel__footer">
        <button type="button" onClick={refresh} disabled={phase === 'loading'}>
          {phase === 'loading' ? 'Checking…' : 'Re-check'}
        </button>
        {checkedAt && <span className="muted">Last checked {checkedAt.toLocaleTimeString()}</span>}
      </footer>
    </section>
  );
}
