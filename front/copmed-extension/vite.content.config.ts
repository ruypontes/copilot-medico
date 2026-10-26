import { defineConfig } from 'vite'

// Content script (B51/B52/B53): o Chrome não carrega content script como módulo
// ES, então ele é empacotado à parte num IIFE único, com o registry de PEPs
// dentro. Roda depois do build principal (que limpa a dist) e só acrescenta
// dist/content.js.
export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    copyPublicDir: false,
    lib: {
      entry: 'src/content/main.ts',
      formats: ['iife'],
      name: 'CopmedContent',
      fileName: () => 'content.js',
    },
  },
})
