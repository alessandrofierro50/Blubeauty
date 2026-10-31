import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'BluBeauty',
        short_name: 'BluBeauty',
        description: 'Gestionale per la tua azienda',
        theme_color: '#2340a8',
        background_color: '#ffffff',
        display: 'standalone',
        lang: 'it',
        icons: [{ src: '/logo.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
      },
      // app in un solo file (~2 MB): il limite di precache deve stare sopra, altrimenti l'app non si apre offline
      workbox: { navigateFallbackDenylist: [/^\/api/], maximumFileSizeToCacheInBytes: 4 * 1024 * 1024 },
    }),
  ],
  build: { chunkSizeWarningLimit: 3000 },
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
