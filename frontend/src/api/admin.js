/**
 * Account administration endpoints (Module 5). The server allows these only
 * for admins; the client hides them from everyone else.
 *
 *   GET   /admin/users                         → { items: User[], total, limit, offset }
 *   POST  /admin/users                         → { user, temporary_password }
 *   PATCH /admin/users/{id}                    → User
 *   POST  /admin/users/{id}/status             { is_active } → User
 *   POST  /admin/users/{id}/reset-password     → { user, temporary_password }
 *   GET   /admin/audit-events                  → { items: AuditEvent[], total, limit, offset }
 */

import { validateNewPassword } from './auth.js';
import { sendJson } from './client.js';
import { fetchPage } from './manufacturing.js';

export const ROLES = Object.freeze([
  { value: 'operator', label: 'Operator', hint: 'Records production, quality and downtime for assigned machines' },
  { value: 'supervisor', label: 'Supervisor', hint: 'Plant-wide views, shift reports, approves maintenance' },
  { value: 'production_manager', label: 'Production manager', hint: 'Analytics and operational reporting' },
  { value: 'admin', label: 'Admin', hint: 'Manages accounts and reads the access log' },
]);

export function roleLabel(role) {
  return ROLES.find((r) => r.value === role)?.label ?? role;
}

export function fetchUsers(params, options) {
  return fetchPage('/admin/users', params, options);
}

export async function createUser(payload, options = {}) {
  const { data } = await sendJson('/admin/users', { ...options, body: payload });
  return data;
}

export async function updateUser(id, changes, options = {}) {
  const { data } = await sendJson(`/admin/users/${encodeURIComponent(id)}`, {
    ...options,
    method: 'PATCH',
    body: changes,
  });
  return data;
}

export async function setUserActive(id, isActive, options = {}) {
  const { data } = await sendJson(`/admin/users/${encodeURIComponent(id)}/status`, {
    ...options,
    body: { is_active: isActive },
  });
  return data;
}

/**
 * Set a new password. With `newPassword` the admin chooses it; without it the
 * server generates a one-time password (always changed at next sign-in).
 */
export async function resetUserPassword(id, { newPassword = '', requirePasswordChange = true } = {}, options = {}) {
  const body = newPassword
    ? { new_password: newPassword, require_password_change: requirePasswordChange }
    : {};
  const { data } = await sendJson(`/admin/users/${encodeURIComponent(id)}/reset-password`, {
    ...options,
    body,
  });
  return data;
}

export function fetchAuditEvents(params, options) {
  return fetchPage('/admin/audit-events', params, options);
}

/** Local checks mirroring the server's rules for a new account. */
export function validateNewUser({ username, displayName, email, role, password = '', repeat = '' }) {
  const errors = {};
  const name = (username ?? '').trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{2,49}$/.test(name)) {
    errors.username = "3–50 characters: letters, digits, '.', '_' or '-'.";
  }
  if (!(displayName ?? '').trim()) errors.displayName = 'Enter the person’s name.';
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) errors.email = 'Enter a valid email or leave it empty.';
  if (!ROLES.some((r) => r.value === role)) errors.role = 'Choose a role.';
  Object.assign(errors, validateChosenPassword(password, repeat, name));
  return errors;
}

/** An admin-chosen password is optional; when given it must follow the rules and match. */
export function validateChosenPassword(password, repeat, username = '') {
  if (!password) return {};
  const problem = validateNewPassword(password, { username });
  if (problem) return { password: problem };
  if (password !== repeat) return { repeat: 'The passwords do not match.' };
  return {};
}