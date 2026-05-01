import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      // Any request to /check or /check-multi gets forwarded to the local SAM backend
      // This avoids CORS errors when the frontend and backend run on different ports
      '/check': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true
      },
      '/check-multi': {
        target: 'http://127.0.0.1:3000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist'
  }
})
