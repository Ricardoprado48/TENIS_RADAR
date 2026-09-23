import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/icon.svg', 'icons/maskable-icon.svg'],
      manifest: {
        name: 'Tennis Radar',
        short_name: 'Tennis Radar',
        description: 'Radar estatístico de tênis para decisão pré-jogo.',
        lang: 'pt-BR',
        start_url: '/',
        display: 'standalone',
        background_color: '#0D1B1F',
        theme_color: '#0D1B1F',
        icons: [
          { src: '/icons/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
          { src: '/icons/maskable-icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Nunca cachear respostas da API (docs/018_PWA_ARQUITETURA.md, risco R6):
        // /api/health e /api/info de hoje, e qualquer rota futura de
        // calendario/radar/odds, precisam sempre vir da rede, nunca do cache
        // do service worker. So os assets estaticos do build sao precache.
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [],
      },
      devOptions: {
        enabled: false,
      },
    }),
  ],
  server: {
    // Evita CORS em dev: o front chama /api/* e o Vite repassa para o
    // FastAPI local (docs/018_PWA_ARQUITETURA.md risco R9).
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
})
