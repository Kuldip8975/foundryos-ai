// Writes dist/_headers for Cloudflare Pages: the same security headers Caddy
// sends (deploy/Caddyfile), with the API origin allowed in connect-src.
// Run after `vite build` with the same VITE_API_BASE_URL:
//   node scripts/pages-headers.mjs
import { writeFileSync } from 'node:fs';

const raw = process.env.VITE_API_BASE_URL;
let apiOrigin;
try {
  apiOrigin = new URL(raw).origin;
} catch {
  console.error('VITE_API_BASE_URL must be set to the API URL, e.g. https://foundryos-api.duckdns.org/api/v1');
  process.exit(1);
}
if (!apiOrigin.startsWith('https://')) {
  console.error(`The API must use https:// (got ${apiOrigin}).`);
  process.exit(1);
}

const csp = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "media-src 'self'",
  `connect-src 'self' ${apiOrigin}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

const headers = `/*
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Content-Security-Policy: ${csp}
`;

writeFileSync(new URL('../dist/_headers', import.meta.url), headers);
console.log(`dist/_headers written (API: ${apiOrigin})`);
