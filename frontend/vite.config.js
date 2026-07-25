import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// La construction ecrit directement dans backend/static : le conteneur de
// production sert l'interface et l'API depuis la meme origine, ce qui evite
// toute configuration CORS.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: fileURLToPath(new URL('../backend/static', import.meta.url)),
    emptyOutDir: true
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      }
    }
  }
})
