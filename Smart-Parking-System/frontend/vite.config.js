import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws':  {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
        // Suppress "write ECONNABORTED" noise — expected when the browser
        // closes the tab or refreshes before the server sends its next frame.
        on: { error: () => {} },
      },
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  }
})
