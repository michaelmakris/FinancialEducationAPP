import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on the LAN (0.0.0.0), not just localhost -- lets other devices on the same network (e.g. a phone) reach the dev server
  },
})
