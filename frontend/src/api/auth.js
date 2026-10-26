/**
 * Sign-in and own-account endpoints (Module 5).
 *
 *   POST /auth/login     { username, password } → { access_token, expires_at, user }
 *   GET  /auth/me        → CurrentUser
 *   POST /auth/logout    → 204
 *   POST /auth/password  { current_password, new_password } → CurrentUser
 *
 * There is no sign-up: accounts are created by an admin.
 */

import { getJson, requestJson, sendJson } from './client.js';

export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;

export async function login(username, password, options = {}) {
  const { data } = await sendJson('/auth/login', {
    ...options,
    body: { username: username.trim(), password },
  });
  return data;
}

export function fetchCurrentUser(options = {}) {
  return getJson('/auth/me', options);
}

/** Ends the session on the server. Never throws: signing out locally must always work. */
export async function logout(options = {}) {
  try {
    await requestJson('/auth/logout', { ...options, method: 'POST' });
  } catch {
    // offline or already ended: the token is forgotten locally anyway
  }
}

export async function changePassword(currentPassword, newPassword, options = {}) {
  const { data } = await sendJson('/auth/password', {
    ...options,
    body: { current_password: currentPassword, new_password: newPassword },
  });
  return data;
}

/** Local checks mirroring the server's password rules (the server checks again). */
export function validateNewPassword(password, { username = '', current = '' } = {}) {
  if (password.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`;
  if (password.length > PASSWORD_MAX) return `Use at most ${PASSWORD_MAX} characters.`;
  if (password.trim() !== password) return 'Do not start or end the password with a space.';
  if (new Set(password).size < 5) return 'Use a less repetitive password.';
  if (username.length >= 3 && password.toLowerCase().includes(username.toLowerCase())) {
    return 'The password must not contain your username.';
  }
  if (current && password === current) return 'Choose a password different from the current one.';
  return null;
}