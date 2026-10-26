import { afterEach, describe, expect, it, vi } from 'vitest';
import { pdfFileTitle, printAsPdf } from './print.js';

afterEach(() => {
  vi.useRealTimers();
});

describe('Download PDF', () => {
  it('builds a safe file title', () => {
    expect(pdfFileTitle('shift report', '2026-01-15', 'shift A')).toBe('FoundryOS shift report 2026-01-15 shift A');
    expect(pdfFileTitle('dashboard', '', null, 'a/b:c')).toBe('FoundryOS dashboard a-b-c');
  });

  it('prints with the PDF title and restores the page title afterwards', () => {
    vi.useFakeTimers();
    document.title = 'FoundryOS AI';
    let titleWhilePrinting = null;
    const print = vi.spyOn(window, 'print').mockImplementation(() => {
      titleWhilePrinting = document.title;
    });
    printAsPdf('FoundryOS dashboard all dates');
    expect(print).toHaveBeenCalledTimes(1);
    expect(titleWhilePrinting).toBe('FoundryOS dashboard all dates');
    window.dispatchEvent(new Event('afterprint'));
    expect(document.title).toBe('FoundryOS AI');
    vi.runAllTimers();
    expect(document.title).toBe('FoundryOS AI');
  });
});