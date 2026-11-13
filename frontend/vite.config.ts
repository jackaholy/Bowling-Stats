import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on :8000 (`cd backend && .venv/bin/uvicorn app.main:app --reload`).
// Proxying /api keeps the app same-origin, so the backend needs no CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
