/**
 * Ranked horizontal bars (one series). Every row shows its label and value as
 * text; the bar itself is decorative (aria-hidden), so nothing depends on
 * reading colour or length.
 *
 * rows: [{ id, label, sublabel?, value: number, display: string, color? }]
 */
export function BarList({ rows, color = 'var(--series-1)', label }) {
  const max = Math.max(0, ...rows.map((row) => row.value));
  return (
    <ul className="bar-list" aria-label={label}>
      {rows.map((row) => {
        const width = max > 0 ? Math.max(1, (row.value / max) * 100) : 0;
        return (
          <li key={row.id} className="bar-list__row">
            <span className="bar-list__label">
              <span className="bar-list__name">{row.label}</span>
              {row.sublabel && <span className="bar-list__sublabel">{row.sublabel}</span>}
            </span>
            <span className="bar-list__track" aria-hidden="true">
              {row.value > 0 && (
                <span
                  className="bar-list__fill"
                  style={{ width: `${width}%`, background: row.color ?? color }}
                />
              )}
            </span>
            <span className="bar-list__value">{row.display}</span>
          </li>
        );
      })}
    </ul>
  );
}