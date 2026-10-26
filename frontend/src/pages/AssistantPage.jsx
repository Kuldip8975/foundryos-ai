import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchMe, fetchWorkflow, runWorkflow } from '../api/workflows.js';
import { AskForm } from '../components/assistant/AskForm.jsx';
import { ProposalPanel } from '../components/assistant/ProposalPanel.jsx';
import { WorkflowHistory } from '../components/assistant/WorkflowHistory.jsx';
import { AnswerView, AuditTrail, StepsView } from '../components/assistant/WorkflowResult.jsx';
import { StatusBadge } from '../components/StatusBadge.jsx';
import { Card } from '../components/ui/Card.jsx';
import { ErrorCallout, LoadingState } from '../components/ui/StateViews.jsx';
import { formatDateTime, humanize, pluralize } from '../lib/format.js';
import { getSessionToken } from '../auth/session.js';

/**
 * Workflow assistant (Module 4; since Module 5 it uses the signed-in session).
 *
 * The server maps the account's role to an assistant role and limits
 * operators to their assigned machines; this page only shows what it is told.
 *
 * auth: { status: 'checking' | 'signed_in' | 'error', actor, error }
 * view: { kind: 'idle' }
 *     | { kind: 'loading', action: 'ask' | 'open' }
 *     | { kind: 'session', session }
 *     | { kind: 'error', error, action }
 */
export function AssistantPage() {
  const [token] = useState(() => getSessionToken());
  const [auth, setAuth] = useState({ status: 'checking', actor: null, error: null });
  const [view, setView] = useState({ kind: 'idle' });
  const [refreshToken, setRefreshToken] = useState(0);
  const controllerRef = useRef(null);
  const [attempt, setAttempt] = useState(0);

  // What the assistant may do for this account (asked from the server once).
  useEffect(() => {
    const controller = new AbortController();
    setAuth({ status: 'checking', actor: null, error: null });
    fetchMe(token, { signal: controller.signal })
      .then((actor) => setAuth({ status: 'signed_in', actor, error: null }))
      .catch((error) => {
        if (!controller.signal.aborted) setAuth({ status: 'error', actor: null, error });
      });
    return () => controller.abort();
  }, [token, attempt]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const run = useCallback(
    async (action, task) => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      setView({ kind: 'loading', action });
      try {
        const session = await task(controller.signal);
        if (!controller.signal.aborted) setView({ kind: 'session', session });
      } catch (error) {
        if (controller.signal.aborted) return;
        // A 401 ends the whole session (handled by the API client and the app).
        setView({ kind: 'error', error, action });
      } finally {
        if (action === 'ask') setRefreshToken((n) => n + 1); // failed runs are saved too
      }
    },
    [],
  );

  const ask = (question) => run('ask', (signal) => runWorkflow(token, question, { signal }));
  const open = useCallback((id) => run('open', (signal) => fetchWorkflow(token, id, { signal })), [run, token]);

  // After a decision, reload the session quietly so its status and audit trail are current.
  const reload = useCallback(
    async (id) => {
      try {
        const session = await fetchWorkflow(token, id);
        setView((current) => (current.kind === 'session' && current.session.id === id ? { kind: 'session', session } : current));
      } catch {
        // the decision result is already shown; a failed refresh is not fatal
      }
      setRefreshToken((n) => n + 1);
    },
    [token],
  );

  const updateProposal = (proposal) => {
    setView((current) =>
      current.kind === 'session' && current.session.id === proposal.session_id
        ? { kind: 'session', session: { ...current.session, proposal, proposal_status: proposal.status } }
        : current,
    );
    reload(proposal.session_id);
  };

  const actor = auth.actor;
  const busy = view.kind === 'loading';
  const failedSessionId =
    view.kind === 'error' ? view.error?.details?.find((d) => d?.session_id)?.session_id : null;
  const session = view.kind === 'session' ? view.session : null;

  return (
    <div className="assistant">
      <header className="page-header">
        <div>
          <h2 className="page-title">Workflow assistant</h2>
          <p className="page-subtitle">
            Ask about machines, downtime, production, quality and maintenance. Answers are AI-written from plant data
            and cite their evidence. Any change is only prepared, and a supervisor must approve it.
          </p>
        </div>
        {auth.status === 'signed_in' && (
          <div className="page-header__actions">
            <span className="signed-in">
              Using the assistant as <strong>{actor.name}</strong> ({humanize(actor.role)})
            </span>
          </div>
        )}
      </header>

      {auth.status === 'checking' && <LoadingState label="Checking what the assistant may do for you…" />}
      {auth.status === 'error' && (
        <Card title="The assistant is not available">
          <ErrorCallout
            error={auth.error}
            onRetry={auth.error?.status === 403 ? undefined : () => setAttempt((n) => n + 1)}
          />
        </Card>
      )}

      {auth.status === 'signed_in' && (
        <>
          <Card title="Ask a question" subtitle="The assistant uses read-only, allowlisted tools">
            <AskForm busy={busy} canPropose={actor.permissions.includes('maintenance:propose')} onAsk={ask} />
          </Card>

          {view.kind === 'loading' && (
            <Card title={view.action === 'ask' ? 'Working on it' : 'Loading'} busy>
              <LoadingState
                label={
                  view.action === 'ask'
                    ? 'The assistant is querying plant data with allowlisted tools. This usually takes 10–60 seconds…'
                    : 'Loading the workflow…'
                }
              />
            </Card>
          )}

          {view.kind === 'error' && (
            <Card title="Request failed">
              <ErrorCallout error={view.error} />
              {failedSessionId && (
                <button type="button" className="button--ghost button--small" onClick={() => open(failedSessionId)}>
                  View the saved failed attempt (#{failedSessionId})
                </button>
              )}
            </Card>
          )}

          {session && (
            <>
              <Card title="Answer" subtitle={`Question: ${session.question}`}>
                <div className="session-meta">
                  <StatusBadge status={`workflow_${session.status}`} />
                  <span className="muted small">
                    Asked by {session.actor} · {formatDateTime(session.created_at)} ·{' '}
                    {pluralize(session.tool_call_count, 'tool call')}
                  </span>
                </div>
                {session.status === 'completed' && session.answer && <AnswerView session={session} />}
                {session.status === 'failed' && (
                  <p className="callout callout--bad">
                    <strong>No answer.</strong> {session.error_message}{' '}
                    <span className="muted">({session.error_code})</span>
                  </p>
                )}
                {session.status === 'running' && (
                  <p className="callout callout--info">This question is still being processed.</p>
                )}
                {session.proposal && (
                  <ProposalPanel
                    key={session.proposal.id}
                    proposal={session.proposal}
                    actor={actor}
                    token={token}
                    onChange={updateProposal}
                    onStale={() => reload(session.id)}
                  />
                )}
              </Card>
              <Card
                title="How the answer was produced"
                subtitle="Each tool call the model asked for, as checked and run by the server"
              >
                <StepsView steps={session.steps} />
              </Card>
              <Card title="Audit trail" subtitle="Recorded by the server; cannot be edited">
                <AuditTrail events={session.audit_events} />
              </Card>
            </>
          )}

          <WorkflowHistory
            token={token}
            seesEveryone={actor.permissions.includes('workflow:view_all')}
            refreshToken={refreshToken}
            selectedId={session?.id ?? null}
            onSelect={open}
          />
        </>
      )}
    </div>
  );
}