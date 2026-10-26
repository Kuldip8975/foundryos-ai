import { useState } from 'react';
import { fetchWorkflows } from '../../api/workflows.js';
import { formatDateTime } from '../../lib/format.js';
import { StatusBadge } from '../StatusBadge.jsx';
import { InlineSelect, PagedListCard } from '../dashboard/PagedListCard.jsx';

const ACTION_FILTERS = [
  { value: '', label: 'All' },
  { value: 'pending_approval', label: 'Awaiting approval' },
  { value: 'executed', label: 'Executed' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'expired', label: 'Expired' },
  { value: 'failed', label: 'Failed' },
];

function shorten(text, limit = 90) {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

/** Past questions (own ones; supervisors see everyone's), newest first. */
export function WorkflowHistory({ token, seesEveryone, refreshToken, selectedId, onSelect }) {
  const [proposalStatus, setProposalStatus] = useState('');
  const params = { proposal_status: proposalStatus || null };

  return (
    <PagedListCard
      title="Workflow history"
      subtitle={seesEveryone ? 'Everyone’s questions, newest first' : 'Your questions, newest first'}
      actions={
        <InlineSelect label="Action" value={proposalStatus} onChange={setProposalStatus} options={ACTION_FILTERS} />
      }
      scopeKey={JSON.stringify([params, refreshToken])}
      fetchPage={(page, options) => fetchWorkflows(token, { ...params, ...page }, options)}
      caption="Workflow sessions"
      emptyText="No questions match yet."
      columns={[
        { key: 'created_at', header: 'Asked', render: (row) => formatDateTime(row.created_at) },
        { key: 'actor', header: 'By' },
        { key: 'question', header: 'Question', render: (row) => shorten(row.question) },
        { key: 'status', header: 'Status', render: (row) => <StatusBadge status={`workflow_${row.status}`} /> },
        {
          key: 'proposal_status',
          header: 'Action',
          render: (row) => (row.proposal_status ? <StatusBadge status={`proposal_${row.proposal_status}`} /> : '—'),
        },
        {
          key: 'view',
          header: 'Details',
          render: (row) => (
            <button
              type="button"
              className="button--ghost button--small"
              aria-pressed={row.id === selectedId}
              aria-label={`View workflow ${row.id}`}
              onClick={() => onSelect(row.id)}
            >
              View
            </button>
          ),
        },
      ]}
    />
  );
}