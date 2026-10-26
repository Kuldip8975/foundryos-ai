import { useId, useState } from 'react';
import { useAuth } from '../auth/AuthContext.jsx';
import { DemoVideoDialog } from '../components/DemoVideoDialog.jsx';
import { config } from '../config/env.js';
import { describeApiError } from '../lib/errors.js';

export const DEMO_ACCOUNTS = [
  { username: 'demo.operator', label: 'Operator' },
  { username: 'demo.supervisor', label: 'Supervisor' },
  { username: 'demo.manager', label: 'Production manager' },
];

const CAPABILITIES = [
  {
    title: 'Manufacturing intelligence',
    text: 'Output, quality, downtime and maintenance for every line in one view, computed from plant records.',
  },
  {
    title: 'AI shift reports',
    text: 'A written summary of each shift, built only from that shift’s figures and traceable back to them.',
  },
  {
    title: 'Controlled workflow automation',
    text: 'The assistant prepares maintenance requests; a supervisor approves each one before anything changes.',
  },
];

function noticeText(notice) {
  if (!notice) return null;
  if (notice.kind === 'signed_out') return { tone: 'info', text: 'You signed out.' };
  if (notice.code === 'session_expired') {
    return { tone: 'warn', text: 'Your session expired. Sign in again to continue.' };
  }
  if (notice.code === 'session_revoked') {
    return { tone: 'warn', text: 'Your session was ended. Sign in again to continue.' };
  }
  return { tone: 'warn', text: 'Sign in to continue.' };
}

/**
 * Sign-in page shown to anyone without a valid session. There is no sign-up:
 * accounts are created by an administrator.
 */
export function LoginPage() {
  const { signIn, notice } = useAuth();
  const id = useId();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [demoOpen, setDemoOpen] = useState(false);

  const tryDemo = async (account) => {
    setUsername(account.username);
    setPassword(config.demoPassword);
    setFieldErrors({});
    setBusy(true);
    setError(null);
    try {
      await signIn(account.username, config.demoPassword);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    const errors = {};
    if (!username.trim()) errors.username = 'Enter your username or work email.';
    if (!password) errors.password = 'Enter your password.';
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(username, password);
    } catch (err) {
      setPassword('');
      setError(err);
      setBusy(false);
    }
  };

  const banner = !error ? noticeText(notice) : null;
  const failure = error ? describeApiError(error) : null;

  return (
    <div className="login">
      <aside className="login__story" aria-label="About FoundryOS AI">
        <div className="login__brand">
          <span className="brand__mark" aria-hidden="true">F</span>
          <span className="login__wordmark">FoundryOS AI</span>
        </div>
        <h1 className="login__headline">Every shift, measured and accounted for.</h1>
        <ul className="login__capabilities">
          {CAPABILITIES.map((item) => (
            <li key={item.title}>
              <strong>{item.title}</strong>
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
        <div className="login__demo">
          <button type="button" className="login__demo-button" onClick={() => setDemoOpen(true)}>
            <span className="login__play" aria-hidden="true" />
            View demo
          </button>
          <span>New here? Watch how operators, supervisors and admins use it.</span>
        </div>
        <p className="login__footnote">Private plant system. Accounts are issued by your administrator.</p>
      </aside>
      <DemoVideoDialog open={demoOpen} onClose={() => setDemoOpen(false)} />

      <main className="login__panel">
        <form className="login__form" onSubmit={submit} noValidate aria-labelledby={`${id}-title`}>
          <h2 id={`${id}-title`} className="login__title">
            Sign in
          </h2>
          <p className="muted login__lead">Use the account your administrator gave you.</p>

          {banner && (
            <p className={`callout callout--${banner.tone}`} role="status">
              {banner.text}
            </p>
          )}
          {failure && (
            <div className="callout callout--bad" role="alert">
              <strong>{failure.title}.</strong> {failure.message}
            </div>
          )}

          <div className="field">
            <label htmlFor={`${id}-user`}>Username or work email</label>
            <input
              id={`${id}-user`}
              name="username"
              type="text"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              value={username}
              aria-invalid={fieldErrors.username ? true : undefined}
              aria-describedby={fieldErrors.username ? `${id}-user-error` : undefined}
              onChange={(event) => setUsername(event.target.value)}
            />
            {fieldErrors.username && (
              <span id={`${id}-user-error`} className="field__error">
                {fieldErrors.username}
              </span>
            )}
          </div>

          <div className="field">
            <label htmlFor={`${id}-password`}>Password</label>
            <input
              id={`${id}-password`}
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              aria-invalid={fieldErrors.password ? true : undefined}
              aria-describedby={fieldErrors.password ? `${id}-password-error` : undefined}
              onChange={(event) => setPassword(event.target.value)}
            />
            {fieldErrors.password && (
              <span id={`${id}-password-error`} className="field__error">
                {fieldErrors.password}
              </span>
            )}
          </div>

          <button type="submit" className="login__submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          <p className="muted small">Forgot your password? Ask your administrator to reset it.</p>
        </form>
        {config.demoPassword && (
          <section className="login__try" aria-labelledby={`${id}-demo`}>
            <h3 id={`${id}-demo`}>Try the live demo</h3>
            <p className="muted small">
              Sign in as one of these roles. Synthetic data only; changes may be reset daily.
            </p>
            <div className="login__try-buttons">
              {DEMO_ACCOUNTS.map((account) => (
                <button
                  key={account.username}
                  type="button"
                  className="button--ghost button--small"
                  disabled={busy}
                  onClick={() => tryDemo(account)}
                >
                  {account.label}
                </button>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
