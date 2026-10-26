import { useId, useRef, useState } from 'react';
import { approveProposal, newIdempotencyKey, rejectProposal } from '../../api/workflows.js';
import { formatDateTime, formatNumber, humanize } from '../../lib/format.js';
import { StatusBadge } from '../StatusBadge.jsx';
import { ErrorCallout, LoadingState } from '../ui/StateViews.jsx';

const STALE_CODES = new Set(['proposal_expired', 'proposal_not_pending', 'revalidation_failed', 'integrity_check_failed']);

function Preview({ proposal }) {
  const p = proposal.preview ?? {};
  const rows = [
    ['Action', 'Create a maintenance request'],
    ['Machine', p.machine_name ? `${p.machine_code} — ${p.machine_name}` : p.machine_code],
    ['Priority', humanize(p.priority)],
    ['Issue description', p.issue_description],
    ['Initial status', humanize(p.initial_status)],
    ['Open requests already on this machine', formatNumber(p.open_requests_for_machine ?? 0)],
    ['Prepared by', proposal.proposed_by],
    ['Approval expires', formatDateTime(proposal.expires_at)],
  ];
  return (
    <dl className="proposal__details">
      {rows.map(([label, value]) => (
        <div key={label} className="proposal__row">
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
      <div className="proposal__row">
        <dt>Approval code</dt>
        <dd>
          <code title={proposal.arguments_hash}>{proposal.arguments_hash.slice(0, 12)}</code>{' '}
          <span className="muted small">(binds the approval to exactly these details)</span>
        </dd>
      </div>
    </dl>
  );
}

function Outcome({ proposal }) {
  const decision = proposal.approval;
  switch (proposal.status) {
    case 'executed':
      return (
        <p className="callout callout--ok" role="status">
          Approved by <strong>{decision?.actor}</strong>. Maintenance request{' '}
          <strong>#{proposal.result_record_id}</strong> was created and confirmed in the database (reference{' '}
          <code>{proposal.result?.external_ref}</code>).
        </p>
      );
    case 'rejected':
      return (
        <p className="callout callout--info" role="status">
          {decision?.actor === proposal.proposed_by ? 'Withdrawn' : 'Rejected'} by <strong>{decision?.actor}</strong>
          . Nothing was created.{decision?.note ? ` Note: ${decision.note}` : ''}
        </p>
      );
    case 'expired':
      return (
        <p className="callout callout--warn" role="status">
          This proposal expired before anyone approved it. Nothing was created. Ask again to prepare a new one.
        </p>
      );
    case 'failed':
      return (
        <p className="callout callout--bad" role="status">
          Not executed: {proposal.error_message ?? 'the action failed its final checks'}. Nothing was created.
        </p>
      );
    default:
      return null;
  }
}

/**
 * A prepared action awaiting a human decision. Approve sends back the
 * proposal's binding hash and an idempotency key that is reused if the same
 * decision is retried (e.g. after a network error), so it cannot run twice.
 */
export function ProposalPanel({ proposal, actor, token, onChange, onStale }) {
  const ids = { reviewed: useId(), note: useId() };
  const [reviewed, setReviewed] = useState(false);
  const [note, setNote] = useState('');
  const [phase, setPhase] = useState(null); // 'approve' | 'reject' | null
  const [error, setError] = useState(null);
  const keys = useRef({});

  const keyFor = (decision) => {
    const name = `${proposal.id}:${decision}`;
    keys.current[name] ??= newIdempotencyKey();
    return keys.current[name];
  };

  const permissions = actor?.permissions ?? [];
  const canDecide = permissions.includes('actions:decide');
  const isAuthor = actor?.name === proposal.proposed_by;
  const canWithdraw = isAuthor && permissions.includes('maintenance:propose');
  const pending = proposal.status === 'pending_approval';
  const noteTooLong = note.trim().length > 500;

  const decide = async (decision) => {
    setPhase(decision);
    setError(null);
    try {
      const request =
        decision === 'approve'
          ? approveProposal(token, proposal.id, {
              argumentsHash: proposal.arguments_hash,
              idempotencyKey: keyFor('approve'),
              note,
            })
          : rejectProposal(token, proposal.id, { idempotencyKey: keyFor('reject'), note });
      onChange(await request);
    } catch (err) {
      setError(err);
      if (STALE_CODES.has(err?.code)) onStale?.();
    } finally {
      setPhase(null);
    }
  };

  return (
    <section className="proposal" aria-label="Proposed action">
      <div className="proposal__header">
        <h4 className="subheading">Proposed action — requires human approval</h4>
        <StatusBadge status={`proposal_${proposal.status}`} />
      </div>
      <Preview proposal={proposal} />
      <Outcome proposal={proposal} />

      {pending && phase && (
        <LoadingState
          label={
            phase === 'approve'
              ? 'Approving — re-checking the action and creating the maintenance request…'
              : 'Recording the rejection…'
          }
        />
      )}
      {error && <ErrorCallout error={error} />}

      {pending && !phase && canDecide && (
        <div className="proposal__decision">
          <label className="checkbox" htmlFor={ids.reviewed}>
            <input
              id={ids.reviewed}
              type="checkbox"
              checked={reviewed}
              onChange={(event) => setReviewed(event.target.checked)}
            />
            I have reviewed this action and the machine it applies to.
          </label>
          <div className="field">
            <label htmlFor={ids.note}>Note (optional)</label>
            <textarea
              id={ids.note}
              rows={2}
              value={note}
              aria-invalid={noteTooLong ? true : undefined}
              onChange={(event) => setNote(event.target.value)}
            />
            {noteTooLong && (
              <span className="field__error" role="alert">
                Keep the note under 500 characters.
              </span>
            )}
          </div>
          {isAuthor && (
            <p className="muted small">You prepared this action; another supervisor is normally required to approve it.</p>
          )}
          <div className="proposal__buttons">
            <button type="button" disabled={!reviewed || noteTooLong} onClick={() => decide('approve')}>
              Approve and create request
            </button>
            <button type="button" className="button--ghost" disabled={noteTooLong} onClick={() => decide('reject')}>
              Reject
            </button>
          </div>
        </div>
      )}

      {pending && !phase && !canDecide && (
        <div className="proposal__decision">
          <p className="muted">Waiting for a supervisor to approve or reject this action.</p>
          {canWithdraw && (
            <div className="proposal__buttons">
              <button type="button" className="button--ghost" onClick={() => decide('reject')}>
                Withdraw proposal
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}