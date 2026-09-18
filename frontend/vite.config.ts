import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Tailwind runs through PostCSS (postcss.config.js).
// For a hosted build set VITE_API_BASE to the API's URL; in dev, /api is proxied to the backend.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
  build: { emptyOutDir: false },
})
