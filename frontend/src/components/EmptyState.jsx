export function EmptyState({ title, children }) {
  return (
    <section className="empty-state" aria-label={title}>
      <h2>{title}</h2>
      <div className="muted">{children}</div>
    </section>
  );
}
