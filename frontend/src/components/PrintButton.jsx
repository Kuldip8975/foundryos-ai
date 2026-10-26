import { printAsPdf } from '../lib/print.js';

/** Opens the browser's print dialog; choose "Save as PDF" to download. */
export function PrintButton({ title, label = 'Download PDF', disabled = false }) {
  return (
    <button
      type="button"
      className="button--ghost button--small no-print"
      onClick={() => printAsPdf(title)}
      disabled={disabled}
      title="Opens the print dialog. Choose “Save as PDF” as the printer."
    >
      {label}
    </button>
  );
}

/** Shown only on paper/PDF: what this document is, its scope and who generated it. */
export function PrintHeader({ title, lines = [], generatedBy }) {
  return (
    <div className="print-only print-header" aria-hidden="true">
      <p className="print-header__brand">FoundryOS AI</p>
      <h1 className="print-header__title">{title}</h1>
      {lines.filter(Boolean).map((line) => (
        <p key={line} className="print-header__line">
          {line}
        </p>
      ))}
      <p className="print-header__line">
        Generated {new Date().toLocaleString()}
        {generatedBy ? ` by ${generatedBy}` : ''}
      </p>
    </div>
  );
}