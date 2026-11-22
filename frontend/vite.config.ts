import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Docker Desktop on Windows does not always forward file system events into
// containers, so the dev server can be switched to polling (DEC A6).
const usePolling = process.env.VITE_USE_POLLING === 'true';
// Single origin (DEC-68): the browser talks to the Vite dev server only and
// `/api` is proxied to the backend.
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      '/api': { target: apiProxyTarget },
      // Uploaded images (DEC-70) are served by the backend.
      '/media': { target: apiProxyTarget },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
    // Containers on Windows/Docker Desktop render the first test of a file slowly.
    testTimeout: 15000,
  },
});
