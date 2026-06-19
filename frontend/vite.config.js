import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // Use 127.0.0.1 (not "localhost") so the dev server doesn't try IPv6
      // (::1) first and fail — the backend binds to 127.0.0.1.
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
