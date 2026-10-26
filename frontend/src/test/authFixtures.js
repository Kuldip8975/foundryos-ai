/** Bodies shaped like the Module 5 /auth API, one per role. */
import { SESSION_KEY } from '../auth/session.js';
import { jsonResponse } from './fetchMock.js';

const PERMISSIONS = {
  operator: [
    'assistant:use', 'downtime:read', 'downtime:record', 'machines:read', 'maintenance:read',
    'production:read', 'production:record', 'quality:read', 'quality:record',
  ],
  supervisor: [
    'actions:approve', 'analytics:read', 'assistant:use', 'downtime:read', 'downtime:record', 'machines:read',
    'maintenance:manage', 'maintenance:read', 'production:read', 'production:record', 'quality:read',
    'quality:record', 'reports:generate', 'reports:read',
  ],
  production_manager: [
    'analytics:read', 'assistant:use', 'downtime:read', 'machines:read', 'maintenance:read',
    'master_data:manage', 'production:read', 'quality:read', 'reports:generate', 'reports:read',
  ],
  admin: ['audit:read', 'machines:read', 'users:manage'],
};

const HOME = { operator: 'my-work', supervisor: 'dashboard', production_manager: 'dashboard', admin: 'admin' };

export function currentUser(role, overrides = {}) {
  return {
    id: { operator: 4, supervisor: 2, production_manager: 3, admin: 1 }[role],
    username: { operator: 'olga', supervisor: 'sam', production_manager: 'pia', admin: 'ada' }[role],
    display_name: { operator: 'Olga Operator', supervisor: 'Sam Supervisor', production_manager: 'Pia Manager', admin: 'Ada Admin' }[role],
    email: null,
    role,
    permissions: PERMISSIONS[role],
    must_change_password: false,
    home: HOME[role],
    machine_scope: role === 'operator' ? 'assigned' : 'all',
    machines: role === 'operator' ? [{ id: 1, code: 'CNC-01', name: 'CNC mill', is_active: true }] : [],
    session_expires_at: '2099-01-01T00:00:00Z',
    idle_timeout_minutes: 30,
    ...overrides,
  };
}

export const SESSION_TOKEN = 'session-token-for-tests-0123456789abcdef';

/** Store a session token as if the person had signed in earlier in this tab. */
export function startSession(token = SESSION_TOKEN) {
  window.sessionStorage.setItem(SESSION_KEY, token);
}

export function loginResponse(user) {
  return jsonResponse({
    access_token: SESSION_TOKEN,
    token_type: 'bearer',
    expires_at: user.session_expires_at,
    user,
  });
}

export function authError(code, message, status = 401) {
  return jsonResponse({ error: { code, message, request_id: 'req-auth' } }, { status });
}