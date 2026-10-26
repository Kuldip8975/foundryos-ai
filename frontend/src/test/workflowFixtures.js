/** Response bodies shaped like the Module 4 workflow API. */

export const TOKENS = {
  olga: 'olga-operator-token-0123456789abc',
  alice: 'alice-supervisor-token-0123456789',
};

export const OPERATOR = {
  name: 'olga',
  role: 'operator',
  permissions: ['data:read', 'maintenance:propose', 'workflow:run'],
};

export const SUPERVISOR = {
  name: 'alice',
  role: 'supervisor',
  permissions: ['actions:decide', 'data:read', 'maintenance:propose', 'workflow:run', 'workflow:view_all'],
};

export const HASH = 'ab12cd34ef56'.padEnd(64, '0');

export function step(overrides = {}) {
  return {
    id: 11,
    sequence: 1,
    round: 1,
    tool: 'get_machine_status',
    arguments: {},
    status: 'ok',
    evidence_id: 'E1',
    result: {
      machines: [{ code: 'MILL', name: 'Mill', state: 'down', open_maintenance_requests: 0 }],
      data_sources: { manual: 1, import: 0, synthetic: 0 },
    },
    error_code: null,
    error_message: null,
    duration_ms: 4,
    created_at: '2026-10-15T08:00:01Z',
    ...overrides,
  };
}

export function proposal(overrides = {}) {
  return {
    id: 7,
    session_id: 3,
    action_type: 'create_maintenance_request',
    arguments: { machine_code: 'MILL', issue_description: 'Spindle vibration above normal', priority: 'high' },
    preview: {
      action: 'create_maintenance_request',
      target: { machine_id: 1 },
      machine_code: 'MILL',
      machine_name: 'Mill',
      priority: 'high',
      issue_description: 'Spindle vibration above normal',
      initial_status: 'open',
      open_requests_for_machine: 0,
      requires_approval: true,
    },
    arguments_hash: HASH,
    status: 'pending_approval',
    proposed_by: 'olga',
    expires_at: '2026-10-15T08:15:00Z',
    result: null,
    result_record_type: null,
    result_record_id: null,
    error_code: null,
    error_message: null,
    created_at: '2026-10-15T08:00:02Z',
    decided_at: null,
    executed_at: null,
    approval: null,
    ...overrides,
  };
}

export function executed(base = proposal()) {
  return {
    ...base,
    status: 'executed',
    result: {
      maintenance_request_id: 42,
      external_ref: `wf-proposal-${base.id}`,
      machine_code: 'MILL',
      priority: 'high',
      status: 'open',
    },
    result_record_type: 'maintenance_request',
    result_record_id: 42,
    decided_at: '2026-10-15T08:05:00Z',
    executed_at: '2026-10-15T08:05:00Z',
    approval: {
      decision: 'approved',
      actor: 'alice',
      actor_role: 'supervisor',
      arguments_hash: HASH,
      note: null,
      created_at: '2026-10-15T08:05:00Z',
    },
  };
}

export function session(overrides = {}) {
  return {
    id: 3,
    actor: 'olga',
    actor_role: 'operator',
    question: 'Which machines are down?',
    status: 'completed',
    tool_call_count: 1,
    includes_synthetic_data: false,
    proposal_status: null,
    error_code: null,
    error_message: null,
    created_at: '2026-10-15T08:00:00Z',
    completed_at: '2026-10-15T08:00:05Z',
    provider: 'gemini',
    model: 'gemini-test',
    prompt_version: 'workflow-agent-v1',
    answer: {
      answer: 'MILL is down; LATHE is running.',
      findings: [{ statement: 'MILL has ongoing downtime.', evidence: ['E1'] }],
      limitations: ['State reflects recorded downtime, not live telemetry.'],
    },
    steps: [step()],
    proposal: null,
    audit_events: [
      { id: 1, proposal_id: null, event_type: 'workflow_started', actor: 'olga', details: { role: 'operator' }, created_at: '2026-10-15T08:00:00Z' },
      { id: 2, proposal_id: null, event_type: 'tool_call', actor: 'olga', details: { tool: 'get_machine_status', status: 'ok' }, created_at: '2026-10-15T08:00:01Z' },
      { id: 3, proposal_id: null, event_type: 'workflow_completed', actor: 'olga', details: { tool_calls: 1 }, created_at: '2026-10-15T08:00:05Z' },
    ],
    ...overrides,
  };
}

export function withProposal(base = session(), p = proposal()) {
  return {
    ...base,
    proposal: p,
    proposal_status: p.status,
    steps: [
      ...base.steps,
      step({ id: 12, sequence: 2, tool: 'prepare_maintenance_request', evidence_id: 'E2', result: p.preview }),
    ],
  };
}

export function summaryOf(s) {
  const { answer, steps, proposal: p, audit_events: events, provider, model, prompt_version: v, ...rest } = s;
  return rest;
}