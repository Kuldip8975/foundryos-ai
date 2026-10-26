import { useId } from 'react';

/**
 * Titled content card. Exposed to assistive technology as a region named by
 * its title; `busy` marks it as updating (aria-busy).
 */
export function Card({ title, subtitle, actions, busy = false, className = '', children }) {
  const titleId = useId();
  return (
    <section className={`card ${className}`} aria-labelledby={titleId} aria-busy={busy}>
      <header className="card__header">
        <div>
          <h3 id={titleId} className="card__title">
            {title}
          </h3>
          {subtitle && <p className="card__subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="card__actions">{actions}</div>}
      </header>
      <div className="card__body">{children}</div>
    </section>
  );
}