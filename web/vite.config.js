import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy keeps the browser on one origin, so CORS never becomes the
    // user's problem during local development.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true,
                rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
