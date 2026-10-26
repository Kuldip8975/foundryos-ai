/**
 * The sign-in session token (Module 5).
 *
 * Kept in sessionStorage: it survives a page reload but is forgotten when the
 * tab is closed, and it is never written to localStorage or cookies. When
 * storage is unavailable (private mode, blocked site data) the token lives in
 * memory only and the person signs in again after a reload.
 *
 * The server decides everything the token allows; the browser only carries it.
 */

export const SESSION_KEY = 'foundryos.session';

let memoryToken = '';
const endedListeners = new Set();

export function getSessionToken() {
  try {
    return window.sessionStorage.getItem(SESSION_KEY) || '';
  } catch {
    return memoryToken;
  }
}

export function setSessionToken(token) {
  try {
    window.sessionStorage.setItem(SESSION_KEY, token);
  } catch {
    memoryToken = token;
  }
}

export function clearSessionToken() {
  memoryToken = '';
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // nothing stored
  }
}

/** Subscribe to "the server ended this session" (expired, revoked, signed out elsewhere). */
export function onSessionEnded(listener) {
  endedListeners.add(listener);
  return () => endedListeners.delete(listener);
}

/** Forget the token and tell the app; `error` explains why (shown on the sign-in page). */
export function endSession(error = null) {
  clearSessionToken();
  for (const listener of [...endedListeners]) listener(error);
}