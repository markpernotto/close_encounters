import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5550,
    proxy: {
      // Proxy /api and /docs to the local FastAPI dev server during `npm run dev`.
      // In production (Vercel) these paths resolve via vercel.json rewrites instead.
      '/api': 'http://localhost:8000',
      '/docs': 'http://localhost:8000',
      '/openapi.json': 'http://localhost:8000',
    },
  },
});
