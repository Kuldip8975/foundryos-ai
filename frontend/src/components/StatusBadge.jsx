const LABELS = {
  loading: 'Checking…',
  ready: 'Connected',
  not_ready: 'Degraded',
  unreachable: 'Offline',
  misconfigured: 'Not configured',
  pass: 'Pass',
  fail: 'Fail',
  skip: 'Skipped',
  // Module 2: downtime events
  ongoing: 'Ongoing',
  resolved: 'Resolved',
  // Module 2: maintenance requests (prefixed to keep keys unambiguous)
  request_open: 'Open',
  request_in_progress: 'In progress',
  request_resolved: 'Resolved',
  request_closed: 'Closed',
  request_cancelled: 'Cancelled',
  priority_critical: 'Critical',
  priority_high: 'High',
  priority_medium: 'Medium',
  priority_low: 'Low',
  // Module 3: AI shift reports
  report_pending: 'Generating',
  report_completed: 'Completed',
  report_failed: 'Failed',
  // Module 4: workflow assistant
  workflow_running: 'Running',
  workflow_completed: 'Answered',
  workflow_failed: 'Failed',
  step_ok: 'Ran',
  step_rejected: 'Refused',
  step_error: 'Error',
  proposal_pending_approval: 'Awaiting approval',
  proposal_executed: 'Executed',
  proposal_rejected: 'Rejected',
  proposal_expired: 'Expired',
  proposal_failed: 'Not executed',
  // Module 5: accounts
  account_active: 'Active',
  account_inactive: 'Deactivated',
  account_locked: 'Locked',
  account_password_pending: 'Must set password',
  event_ok: 'Succeeded',
  event_failed: 'Failed',
};

const TONES = {
  loading: 'neutral',
  ready: 'ok',
  pass: 'ok',
  not_ready: 'warn',
  skip: 'neutral',
  unreachable: 'bad',
  misconfigured: 'bad',
  fail: 'bad',
  ongoing: 'warn',
  resolved: 'ok',
  request_open: 'warn',
  request_in_progress: 'info',
  request_resolved: 'ok',
  request_closed: 'neutral',
  request_cancelled: 'neutral',
  priority_critical: 'bad',
  priority_high: 'warn',
  priority_medium: 'neutral',
  priority_low: 'neutral',
  report_pending: 'info',
  report_completed: 'ok',
  report_failed: 'bad',
  workflow_running: 'info',
  workflow_completed: 'ok',
  workflow_failed: 'bad',
  step_ok: 'ok',
  step_rejected: 'warn',
  step_error: 'bad',
  proposal_pending_approval: 'warn',
  proposal_executed: 'ok',
  proposal_rejected: 'neutral',
  proposal_expired: 'neutral',
  proposal_failed: 'bad',
  account_active: 'ok',
  account_inactive: 'neutral',
  account_locked: 'bad',
  account_password_pending: 'info',
  event_ok: 'ok',
  event_failed: 'bad',
};

/** Coloured pill that always carries a text label (colour is never the only cue). */
export function StatusBadge({ status }) {
  return (
    <span className={`badge badge--${TONES[status] ?? 'neutral'}`} data-status={status}>
      {LABELS[status] ?? status}
    </span>
  );
}