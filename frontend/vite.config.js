import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Override with VITE_API_TARGET if the backend runs on another port.
const target = process.env.VITE_API_TARGET || 'http://localhost:8000'
const proxy = { '/api': { target, changeOrigin: true } }

export default defineConfig({
  plugins: [react()],
  // Proxy /api in dev and preview so the browser always sees a single origin
  // (in Docker, nginx does the same job).
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
})
