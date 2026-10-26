import { useId, useState } from 'react';
import { useApiResource } from '../../hooks/useApiResource.js';
import { Card } from '../ui/Card.jsx';
import { DataTable } from '../ui/DataTable.jsx';
import { Pagination } from '../ui/Pagination.jsx';
import { EmptyMessage, ErrorCallout, LoadingState } from '../ui/StateViews.jsx';

export const PAGE_SIZE = 10;

/** A labelled <select> for a card-level filter. */
export function InlineSelect({ label, value, onChange, options }) {
  const id = useId();
  return (
    <span className="inline-field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </span>
  );
}

/**
 * Card showing one page of a list endpoint, with Previous/Next pagination.
 *
 * `scopeKey` identifies the current filters; when it changes, the card returns
 * to the first page (stored per scope, so no reset effect is needed).
 * `fetchPage({ limit, offset }, { signal })` must resolve to { items, total, limit, offset }.
 */
export function PagedListCard({ title, subtitle, actions, scopeKey, fetchPage, columns, caption, emptyText }) {
  const [page, setPage] = useState({ scope: scopeKey, offset: 0 });
  const offset = page.scope === scopeKey ? page.offset : 0;

  const resource = useApiResource(
    ({ signal }) => fetchPage({ limit: PAGE_SIZE, offset }, { signal }),
    `${scopeKey}|${offset}`,
  );
  const { data, error, loading, reload } = resource;

  return (
    <Card title={title} subtitle={subtitle} actions={actions} busy={loading} className="card--wide">
      {error && <ErrorCallout error={error} onRetry={reload} />}
      {!error && !data && <LoadingState label={`Loading ${title.toLowerCase()}…`} />}
      {data && data.total === 0 && <EmptyMessage>{emptyText}</EmptyMessage>}
      {data && data.total > 0 && (
        <>
          <DataTable caption={caption} columns={columns} rows={data.items} />
          <Pagination
            label={`${title} pages`}
            total={data.total}
            limit={data.limit}
            offset={data.offset}
            disabled={loading}
            onChange={(next) => setPage({ scope: scopeKey, offset: next })}
          />
        </>
      )}
    </Card>
  );
}