import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
// Source: BLUEPRINT.md §16 Frontend Architecture, §23 Deployment Architecture
export default defineConfig({
  plugins: [react()],

  // Proxy browser requests to the backend's exact bare REST and WebSocket routes.
  // Production: Nginx handles proxying (see frontend/nginx.conf)
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },

  // Vitest configuration (inline to avoid separate config file)
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/tests/setup.js',
    include: ['src/tests/**/*.test.{js,jsx}'],
    coverage: {
      reporter: ['text', 'json', 'html'],
      include: ['src/api/**', 'src/store/**', 'src/hooks/**', 'src/mocks/**'],
    },
  },
});
