/**
 * "Download PDF" through the browser's own print dialog (choose "Save as PDF").
 *
 * No library and no server work: print styles in global.css hide navigation,
 * buttons, filters and anything marked `.no-print`, and show the `.print-only`
 * header with the page title, filters and who generated it. The document
 * title becomes the suggested file name.
 */

/** A file-name-safe title, e.g. "FoundryOS shift report 2026-01-14 A". */
export function pdfFileTitle(...parts) {
  return ['FoundryOS', ...parts]
    .filter(Boolean)
    .join(' ')
    .replace(/[\\/:*?"<>|]+/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 120);
}

export function printAsPdf(title) {
  const previous = document.title;
  document.title = title;
  const restore = () => {
    document.title = previous;
    window.removeEventListener('afterprint', restore);
  };
  window.addEventListener('afterprint', restore);
  try {
    window.print();
  } finally {
    // Some browsers return from print() before the dialog closes; afterprint restores then.
    setTimeout(restore, 1000);
  }
}