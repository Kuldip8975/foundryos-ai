/**
 * Which pages a signed-in person may open (Module 5).
 *
 * This only decides what the interface shows. The server checks every
 * request against the same permissions, so hiding a page is a convenience,
 * never the protection.
 */

export const PAGES = Object.freeze({
  // For people who work on assigned machines (operators); others see the whole plant.
  'my-work': { label: 'My machines', permission: 'production:record', assignedOnly: true },
  dashboard: { label: 'Dashboard', permission: 'analytics:read' },
  reports: { label: 'Shift reports', permission: 'reports:read' },
  assistant: { label: 'Workflow assistant', permission: 'assistant:use' },
  admin: { label: 'Users & access', permission: 'users:manage' },
  account: { label: 'My account', permission: null },
});

/** Navigation order. */
export const NAV_ORDER = ['my-work', 'dashboard', 'reports', 'assistant', 'admin'];

export function can(user, permission) {
  return Boolean(user?.permissions?.includes(permission));
}

export function canOpen(user, page) {
  const spec = PAGES[page];
  if (!spec) return false;
  if (spec.assignedOnly && user?.machine_scope !== 'assigned') return false;
  return spec.permission === null || can(user, spec.permission);
}

/** The page shown for "home": the server's suggestion if allowed, else the first allowed page. */
export function homePage(user) {
  if (user?.home && canOpen(user, user.home)) return user.home;
  return NAV_ORDER.find((page) => canOpen(user, page)) ?? 'account';
}

export function navItems(user) {
  return NAV_ORDER.filter((page) => canOpen(user, page)).map((page) => ({ page, label: PAGES[page].label }));
}

const ROLE_LABELS = {
  operator: 'Operator',
  supervisor: 'Supervisor',
  production_manager: 'Production manager',
  admin: 'Admin',
};

export function roleName(role) {
  return ROLE_LABELS[role] ?? role;
}