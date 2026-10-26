import { useId, useState } from 'react';
import { changePassword, validateNewPassword } from '../api/auth.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { Card } from '../components/ui/Card.jsx';
import { ErrorCallout } from '../components/ui/StateViews.jsx';
import { roleName } from '../lib/access.js';
import { formatDateTime } from '../lib/format.js';

/** Change-password form. `required` is the first sign-in with a temporary password. */
export function ChangePasswordForm({ required = false, onDone }) {
  const { user, updateUser } = useAuth();
  const id = useId();
  const [values, setValues] = useState({ current: '', next: '', repeat: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const set = (field) => (event) => setValues((v) => ({ ...v, [field]: event.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    const found = {};
    if (!values.current) found.current = 'Enter your current password.';
    const problem = validateNewPassword(values.next, { username: user.username, current: values.current });
    if (problem) found.next = problem;
    else if (values.repeat !== values.next) found.repeat = 'The passwords do not match.';
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await changePassword(values.current, values.next);
      setValues({ current: '', next: '', repeat: '' });
      setSaved(true);
      updateUser(updated);
      onDone?.(updated);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const field = (name, label, autoComplete, hint) => (
    <div className="field">
      <label htmlFor={`${id}-${name}`}>{label}</label>
      <input
        id={`${id}-${name}`}
        type="password"
        autoComplete={autoComplete}
        value={values[name]}
        aria-invalid={errors[name] ? true : undefined}
        aria-describedby={`${id}-${name}-hint`}
        onChange={set(name)}
      />
      <span id={`${id}-${name}-hint`} className={errors[name] ? 'field__error' : 'field__hint'}>
        {errors[name] ?? hint}
      </span>
    </div>
  );

  return (
    <form className="password-form" onSubmit={submit} noValidate aria-label="Change password">
      {required && (
        <p className="callout callout--info">
          Your administrator gave you a temporary password. Choose your own password to continue.
        </p>
      )}
      {field('current', required ? 'Temporary password' : 'Current password', 'current-password', '')}
      {field('next', 'New password', 'new-password', 'At least 12 characters. A short sentence works well.')}
      {field('repeat', 'Repeat new password', 'new-password', '')}
      {error && <ErrorCallout error={error} />}
      {saved && !required && (
        <p className="callout callout--info" role="status">
          Password changed. Your other sessions were signed out.
        </p>
      )}
      <div>
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Change password'}
        </button>
      </div>
    </form>
  );
}

/** Full-page step after signing in with a temporary password; nothing else opens until it is done. */
export function RequiredPasswordChangePage() {
  const { user, signOut } = useAuth();
  return (
    <div className="gate">
      <Card
        title="Choose your password"
        subtitle={`Signed in as ${user.display_name} (${user.username})`}
        actions={
          <button type="button" className="button--ghost button--small" onClick={signOut}>
            Sign out
          </button>
        }
      >
        <ChangePasswordForm required />
      </Card>
    </div>
  );
}

/** The signed-in person's own account. */
export function AccountPage() {
  const { user } = useAuth();
  return (
    <div className="dashboard">
      <header className="page-header">
        <div>
          <h2 className="page-title">My account</h2>
          <p className="page-subtitle">Your role and machines are set by an administrator.</p>
        </div>
      </header>
      <Card title="Profile">
        <dl className="facts">
          <dt>Name</dt>
          <dd>{user.display_name}</dd>
          <dt>Username</dt>
          <dd>{user.username}</dd>
          <dt>Email</dt>
          <dd>{user.email ?? '—'}</dd>
          <dt>Role</dt>
          <dd>{roleName(user.role)}</dd>
          <dt>Machines</dt>
          <dd>
            {user.machine_scope === 'all'
              ? 'Whole plant'
              : user.machines.length
                ? user.machines.map((m) => `${m.code} (${m.name})`).join(', ')
                : 'None assigned yet'}
          </dd>
          <dt>Session ends</dt>
          <dd>
            {user.session_expires_at ? formatDateTime(user.session_expires_at) : '—'}, or after{' '}
            {user.idle_timeout_minutes} minutes without activity
          </dd>
        </dl>
      </Card>
      <Card title="Change password">
        <ChangePasswordForm />
      </Card>
    </div>
  );
}