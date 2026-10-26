/**
 * Workflow assistant endpoints (Module 4). Every call sends the person's
 * access token as `Authorization: Bearer <token>`.
 *
 *   GET  /workflows/me                              → { name, role, permissions }
 *   POST /workflows                                 → WorkflowSession (201)
 *   GET  /workflows                                 → { items: WorkflowSessionSummary[], total, limit, offset }
 *   GET  /workflows/{id}                            → WorkflowSession
 *   POST /workflows/proposals/{id}/approve|reject   → Proposal
 */

import { getJson, sendJson } from './client.js';
import { fetchPage } from './manufacturing.js';

/** The server's whole-run budget is at most 160 s; the browser waits longer. */
export const WORKFLOW_TIMEOUT_MS = 180_000;
/** Approval executes one database transaction; allow more than an ordinary request. */
export const DECISION_TIMEOUT_MS = 30_000;

export const QUESTION_MIN = 3;
export const QUESTION_MAX = 1000;

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

/** Local check mirroring the server's rules, so obvious mistakes never leave the browser. */
export function validateQuestion(text) {
  const trimmed = (text ?? '').trim();
  if (trimmed.length < QUESTION_MIN) return `Ask a question of at least ${QUESTION_MIN} characters.`;
  if (trimmed.length > QUESTION_MAX) return `Keep the question under ${QUESTION_MAX} characters.`;
  return null;
}

/** A random key for one approve/reject decision; reused when the same decision is retried. */
export function newIdempotencyKey() {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi?.randomUUID) return `ui-${cryptoApi.randomUUID()}`;
  const bytes = new Uint8Array(16);
  cryptoApi.getRandomValues(bytes);
  return `ui-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
}

export function fetchMe(token, options = {}) {
  return getJson('/workflows/me', { ...options, headers: authHeaders(token) });
}

export async function runWorkflow(token, question, options = {}) {
  const { data } = await sendJson('/workflows', {
    ...options,
    headers: authHeaders(token),
    body: { question: question.trim() },
    timeoutMs: WORKFLOW_TIMEOUT_MS,
  });
  return data;
}

export function fetchWorkflows(token, params, options = {}) {
  return fetchPage('/workflows', params, { ...options, headers: authHeaders(token) });
}

export function fetchWorkflow(token, id, options = {}) {
  return getJson(`/workflows/${encodeURIComponent(id)}`, { ...options, headers: authHeaders(token) });
}

export async function approveProposal(token, proposalId, { argumentsHash, idempotencyKey, note }, options = {}) {
  const { data } = await sendJson(`/workflows/proposals/${encodeURIComponent(proposalId)}/approve`, {
    ...options,
    headers: authHeaders(token),
    body: { arguments_hash: argumentsHash, idempotency_key: idempotencyKey, note: note?.trim() || undefined },
    timeoutMs: DECISION_TIMEOUT_MS,
  });
  return data;
}

export async function rejectProposal(token, proposalId, { idempotencyKey, note }, options = {}) {
  const { data } = await sendJson(`/workflows/proposals/${encodeURIComponent(proposalId)}/reject`, {
    ...options,
    headers: authHeaders(token),
    body: { idempotency_key: idempotencyKey, note: note?.trim() || undefined },
    timeoutMs: DECISION_TIMEOUT_MS,
  });
  return data;
}