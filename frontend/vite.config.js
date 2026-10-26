import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The frontend reads VITE_* variables from the repository-root .env so the
// whole project has a single environment file. Vite only exposes variables
// prefixed with VITE_ to browser code; backend secrets in the same file are
// never bundled.
export default defineConfig({
  plugins: [react()],
  envDir: '..',
  server: {
    port: 5173,
    strictPort: true,
  },
  preview: {
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    env: {
      VITE_API_BASE_URL: 'http://api.test/api/v1',
    },
  },
});
