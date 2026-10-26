import { ROUTES } from '../hooks/useHashRoute.js';
import { PAGES } from '../lib/access.js';

/** Shown when someone opens a page their role does not include. */
export function ForbiddenState({ home }) {
  return (
    <section className="empty-state" aria-labelledby="forbidden-title">
      <h2 id="forbidden-title">This page is not part of your role</h2>
      <p className="muted">
        Your account does not include access to this page. If you need it, ask your administrator to change your
        role.
      </p>
      <a className="button-link" href={ROUTES[home]}>
        Go to {PAGES[home]?.label ?? 'your start page'}
      </a>
    </section>
  );
}