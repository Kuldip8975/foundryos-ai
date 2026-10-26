import { useEffect, useState } from 'react';

export const ROUTES = Object.freeze({
  home: '#/',
  dashboard: '#/dashboard',
  reports: '#/reports',
  assistant: '#/assistant',
  'my-work': '#/my-work',
  admin: '#/admin',
  account: '#/account',
});

/**
 * Current page from the URL hash ('#/reports' → 'reports'). The bare app URL
 * and unknown hashes give 'home', which opens the signed-in person's own
 * start page.
 */
export function routeFromHash(hash) {
  const match = Object.entries(ROUTES).find(([name, value]) => name !== 'home' && value === hash);
  return match ? match[0] : 'home';
}

export function navigate(route) {
  window.location.hash = ROUTES[route] ?? ROUTES.home;
}

/** Minimal hash routing: no dependency, works with any static file host. */
export function useHashRoute() {
  const [route, setRoute] = useState(() => routeFromHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(routeFromHash(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}