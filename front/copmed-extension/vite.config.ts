import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // Além do popup (index.html), a extensão tem duas páginas próprias (B29):
      // offscreen.html grava a consulta com o popup fechado; microfone.html pede a permissão.
      input: {
        index: 'index.html',
        offscreen: 'offscreen.html',
        microfone: 'microfone.html',
      },
    },
  },
})
