import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { fetchCurrentUser, login as apiLogin, logout as apiLogout } from '../api/auth.js';
import { canOpen, homePage } from '../lib/access.js';
import { navigate, routeFromHash } from '../hooks/useHashRoute.js';
import { clearSessionToken, endSession, getSessionToken, onSessionEnded, setSessionToken } from './session.js';

/**
 * Who is signed in (Module 5).
 *
 * status: 'checking'   — a token from earlier in this tab is being verified
 *       | 'signed_out' — show the sign-in page (notice explains why, if needed)
 *       | 'signed_in'  — user is the server's description of the person
 *
 * The server is the only authority: the user object (role, permissions,
 * machines) always comes from GET /auth/me or the sign-in response.
 */
const AuthContext = createContext(null);

// Longest delay setTimeout supports reliably (~24.8 days).
const MAX_TIMER_MS = 2_147_000_000;

export function AuthProvider({ children }) {
  const [state, setState] = useState(() => ({
    status: getSessionToken() ? 'checking' : 'signed_out',
    user: null,
    notice: null,
  }));
  const checked = useRef(false);

  // A session ended by the server (expired, revoked, deactivated) returns to sign-in.
  useEffect(
    () =>
      onSessionEnded((error) => {
        setState({ status: 'signed_out', user: null, notice: error ?? null });
      }),
    [],
  );

  // A token kept from earlier in this tab is checked once with the server.
  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    if (!getSessionToken()) return;
    fetchCurrentUser()
      .then((user) => setState({ status: 'signed_in', user, notice: null }))
      .catch((error) => {
        clearSessionToken();
        setState({ status: 'signed_out', user: null, notice: error?.status === 401 ? error : null });
      });
  }, []);

  // End the session in the browser when its absolute lifetime is over. (The
  // server also ends it after inactivity; the next request then reports that.)
  const expiresAt = state.user?.session_expires_at;
  useEffect(() => {
    if (state.status !== 'signed_in' || !expiresAt) return undefined;
    const delay = new Date(expiresAt).getTime() - Date.now();
    if (Number.isNaN(delay)) return undefined;
    const timer = setTimeout(
      () =>
        endSession({
          kind: 'http',
          status: 401,
          code: 'session_expired',
          message: 'Your session has expired. Sign in again.',
        }),
      Math.min(Math.max(delay, 0), MAX_TIMER_MS),
    );
    return () => clearTimeout(timer);
  }, [state.status, expiresAt]);

  const signIn = useCallback(async (username, password) => {
    const result = await apiLogin(username, password);
    setSessionToken(result.access_token);
    const user = { ...result.user, session_expires_at: result.user.session_expires_at ?? result.expires_at };
    setState({ status: 'signed_in', user, notice: null });
    // Open the person's own start page unless they followed a link they may open.
    const route = routeFromHash(window.location.hash);
    if (route === 'home' || !canOpen(user, route)) navigate(homePage(user));
    return user;
  }, []);

  const signOut = useCallback(async () => {
    await apiLogout();
    clearSessionToken();
    setState({ status: 'signed_out', user: null, notice: { kind: 'signed_out' } });
  }, []);

  const updateUser = useCallback((user) => {
    setState((current) => ({ ...current, user: { ...current.user, ...user } }));
  }, []);

  const value = useMemo(() => ({ ...state, signIn, signOut, updateUser }), [state, signIn, signOut, updateUser]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** The signed-in person, or null outside <AuthProvider> (e.g. a page rendered on its own). */
export function useOptionalAuth() {
  return useContext(AuthContext);
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>');
  return context;
}