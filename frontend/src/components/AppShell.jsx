import { useAuth } from '../auth/AuthContext.jsx';
import { config } from '../config/env.js';
import { ROUTES } from '../hooks/useHashRoute.js';
import { navItems, roleName } from '../lib/access.js';

/** Page frame: brand, the navigation this person may use, and their account menu. */
export function AppShell({ route, children }) {
  const { user, signOut } = useAuth();
  const items = navItems(user);

  return (
    <div className="shell">
      <header className="shell__header">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">F</span>
          <div>
            <h1 className="brand__name">FoundryOS AI</h1>
            <p className="brand__tagline">Manufacturing intelligence &amp; workflow automation</p>
          </div>
        </div>
        <nav className="main-nav" aria-label="Main">
          {items.map((item) => (
            <a
              key={item.page}
              href={ROUTES[item.page]}
              className="main-nav__link"
              aria-current={route === item.page ? 'page' : undefined}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="account-menu" aria-label="Your account">
          <a
            href={ROUTES.account}
            className="account-menu__who"
            aria-current={route === 'account' ? 'page' : undefined}
          >
            <span className="account-menu__name">{user.display_name}</span>
            <span className="account-menu__role">{roleName(user.role)}</span>
          </a>
          <button type="button" className="button--ghost button--small" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <main className="shell__main">{children}</main>

      <footer className="shell__footer muted">
        <span>Build mode: {config.mode}</span>
        <span>API: {config.apiBaseUrl ?? 'not configured'}</span>
      </footer>
    </div>
  );
}