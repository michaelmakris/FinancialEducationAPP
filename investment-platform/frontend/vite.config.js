import { defineConfig } from 'vite'
import process from 'node:process'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on the LAN (0.0.0.0), not just localhost -- lets other devices on the same network (e.g. a phone) reach the dev server
    // The page only talks to the BFF, on the same origin, so the session cookie is first-party and SameSite=Strict works.
    proxy: {
      '/bff': { target: process.env.BFF_PROXY_TARGET || 'http://localhost:8080', changeOrigin: false },
    },
  },
})
