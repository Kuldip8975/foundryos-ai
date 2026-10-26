import { describe, expect, it } from 'vitest';
import { parseApiBaseUrl } from './env.js';

describe('parseApiBaseUrl', () => {
  it('accepts an http URL and strips trailing slashes', () => {
    expect(parseApiBaseUrl('http://localhost:8000/api/v1/')).toEqual({
      apiBaseUrl: 'http://localhost:8000/api/v1',
      error: null,
    });
  });

  it('reports a missing value', () => {
    const result = parseApiBaseUrl('');
    expect(result.apiBaseUrl).toBeNull();
    expect(result.error).toMatch(/not set/);
  });

  it('rejects malformed and non-http URLs', () => {
    expect(parseApiBaseUrl('not a url').error).toMatch(/not a valid URL/);
    expect(parseApiBaseUrl('ftp://example.com').error).toMatch(/http or https/);
  });
});
