import { configDefaults, defineConfig } from 'vitest/config'
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
  test: {
    // e2e/ é do Playwright (npm run test:e2e), não do Vitest.
    exclude: [...configDefaults.exclude, 'e2e/**'],
    // Os testes valem para os limites reais (120 min, partes de 5 min). O Vite também lê o
    // .env.local durante os testes: sem isto, quem encurta os prazos ali para o teste manual
    // (VITE_RECORDING_*) veria a suíte falhar.
    env: {
      VITE_RECORDING_CHUNK_SECONDS: '',
      VITE_RECORDING_MAX_SECONDS: '',
    },
  },
})
