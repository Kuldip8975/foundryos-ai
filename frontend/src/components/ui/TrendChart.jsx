import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { parseISODate } from '../../lib/dates.js';
import { formatPeriod } from '../../lib/format.js';
import { labelIndices, niceTicks } from '../../lib/scale.js';

const HEIGHT = 240;
const MARGIN = { top: 12, right: 16, bottom: 30, left: 52 };
const FALLBACK_WIDTH = 640;
const MARKER_LIMIT = 45; // above this many points, markers become clutter

/** Width of an element, tracked with ResizeObserver when available. */
function useElementWidth(ref) {
  const [width, setWidth] = useState(FALLBACK_WIDTH);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const next = Math.round(entry.contentRect.width);
      if (next > 0) setWidth(next);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

/** SVG path through the non-null points; a null value breaks the line. */
function linePath(points) {
  let path = '';
  let drawing = false;
  for (const point of points) {
    if (point.y == null) {
      drawing = false;
      continue;
    }
    path += `${drawing ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`;
    drawing = true;
  }
  return path;
}

/**
 * Time-series line chart (one shared y-axis, ≥1 series of the same unit).
 *
 * rows   [{ date: 'YYYY-MM-DD', [series.key]: number|null }]
 * series [{ key, label, color }]
 * Hover or arrow keys show a tooltip; a data table is always available.
 */
export function TrendChart({ rows, series, granularity, formatValue, formatTick, ariaLabel }) {
  const containerRef = useRef(null);
  const width = useElementWidth(containerRef);
  const [active, setActive] = useState(null);
  const tableId = useId();

  const geometry = useMemo(() => {
    const innerWidth = Math.max(120, width - MARGIN.left - MARGIN.right);
    const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
    const times = rows.map((row) => parseISODate(row.date).getTime());
    const t0 = times[0];
    const t1 = times[times.length - 1];
    const x = (i) =>
      t1 === t0 ? MARGIN.left + innerWidth / 2 : MARGIN.left + ((times[i] - t0) / (t1 - t0)) * innerWidth;

    const values = rows.flatMap((row) => series.map((s) => row[s.key])).filter((v) => typeof v === 'number');
    const ticks = niceTicks(Math.max(0, ...values));
    const top = ticks[ticks.length - 1];
    const y = (value) => MARGIN.top + innerHeight - (value / top) * innerHeight;

    const lines = series.map((s) => ({
      ...s,
      points: rows.map((row, i) => ({
        x: x(i),
        y: typeof row[s.key] === 'number' ? y(row[s.key]) : null,
      })),
    }));
    return { innerWidth, innerHeight, x, y, ticks, lines };
  }, [rows, series, width]);

  const { innerWidth, innerHeight, x, y, ticks, lines } = geometry;
  const showMarkers = rows.length <= MARKER_LIMIT;
  const xLabels = labelIndices(rows.length, width < 480 ? 3 : 6);
  const shortLabel = (date) =>
    granularity === 'month' ? formatPeriod(date, 'month') : formatPeriod(date, 'day').replace(/, \d{4}$/, '');

  function nearestIndex(clientX) {
    const rect = containerRef.current.getBoundingClientRect();
    const px = clientX - rect.left;
    let best = 0;
    for (let i = 1; i < rows.length; i += 1) {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    }
    return best;
  }

  function onKeyDown(event) {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const delta = event.key === 'ArrowRight' ? 1 : -1;
      setActive((current) => Math.min(rows.length - 1, Math.max(0, (current ?? (delta > 0 ? -1 : rows.length)) + delta)));
    } else if (event.key === 'Escape') {
      setActive(null);
    }
  }

  const activeRow = active != null ? rows[active] : null;
  const tooltipLeft = active != null ? Math.min(Math.max(x(active), 90), width - 90) : 0;

  return (
    <figure className="chart">
      {series.length > 1 && (
        <ul className="chart__legend" aria-label="Legend">
          {series.map((s) => (
            <li key={s.key}>
              <span className="chart__key" style={{ background: s.color }} aria-hidden="true" />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <div
        ref={containerRef}
        className="chart__plot"
        tabIndex={0}
        aria-describedby={tableId}
        onPointerMove={(event) => setActive(nearestIndex(event.clientX))}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKeyDown}
        onBlur={() => setActive(null)}
      >
        <svg width={width} height={HEIGHT} role="img" aria-label={ariaLabel} className="chart__svg">
          <g className="chart__grid">
            {ticks.map((tick) => (
              <g key={tick}>
                <line x1={MARGIN.left} x2={MARGIN.left + innerWidth} y1={y(tick)} y2={y(tick)} />
                <text x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                  {formatTick(tick)}
                </text>
              </g>
            ))}
          </g>
          <line
            className="chart__baseline"
            x1={MARGIN.left}
            x2={MARGIN.left + innerWidth}
            y1={MARGIN.top + innerHeight}
            y2={MARGIN.top + innerHeight}
          />
          <g className="chart__xlabels">
            {xLabels.map((i) => (
              <text
                key={rows[i].date}
                x={x(i)}
                y={HEIGHT - 8}
                textAnchor={rows.length === 1 ? 'middle' : i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'}
              >
                {shortLabel(rows[i].date)}
              </text>
            ))}
          </g>
          {active != null && (
            <line
              className="chart__crosshair"
              x1={x(active)}
              x2={x(active)}
              y1={MARGIN.top}
              y2={MARGIN.top + innerHeight}
            />
          )}
          {lines.map((line) => (
            <g key={line.key}>
              <path d={linePath(line.points)} fill="none" stroke={line.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              {line.points.map((point, i) =>
                point.y != null && (showMarkers || i === active) ? (
                  <circle
                    key={i}
                    cx={point.x}
                    cy={point.y}
                    r={i === active ? 5 : 4}
                    fill={line.color}
                    className="chart__marker"
                  />
                ) : null,
              )}
            </g>
          ))}
        </svg>
        {activeRow && (
          <div className="chart__tooltip" style={{ left: tooltipLeft }} aria-live="polite">
            <p className="chart__tooltip-title">{formatPeriod(activeRow.date, granularity)}</p>
            {series.map((s) => (
              <p key={s.key} className="chart__tooltip-row">
                <span className="chart__key" style={{ background: s.color }} aria-hidden="true" />
                <span>{s.label}</span>
                <strong>{formatValue(activeRow[s.key])}</strong>
              </p>
            ))}
          </div>
        )}
      </div>
      <details className="chart__table">
        <summary>Show data table</summary>
        <table id={tableId} className="data-table">
          <caption className="visually-hidden">{ariaLabel}</caption>
          <thead>
            <tr>
              <th scope="col">Period</th>
              {series.map((s) => (
                <th key={s.key} scope="col" className="num">
                  {s.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.date}>
                <th scope="row">{formatPeriod(row.date, granularity)}</th>
                {series.map((s) => (
                  <td key={s.key} className="num">
                    {formatValue(row[s.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}