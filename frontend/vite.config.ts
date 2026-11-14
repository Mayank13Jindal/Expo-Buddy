import { defineConfig } from 'vitest/config'
import { VitePWA } from 'vite-plugin-pwa'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src/pwa',
      filename: 'sw.ts',
      registerType: 'prompt',
      injectManifest: { rollupFormat: 'iife', maximumFileSizeToCacheInBytes: 3000000 },
      manifest: {
        name: 'Expo Buddy',
        short_name: 'Expo Buddy',
        description: 'Keep your expo discoveries together.',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#f8faf7',
        theme_color: '#205c47',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
        share_target: {
          action: '/share-target',
          method: 'POST',
          enctype: 'multipart/form-data',
          params: {
            files: [
              {
                name: 'files',
                accept: [
                  'image/jpeg',
                  'image/png',
                  'image/webp',
                  'image/heic',
                  'image/heif',
                  'application/pdf',
                ],
              },
            ],
          },
        },
      },
    }),
  ],
  server: { proxy: { '/api': 'http://localhost:8000' } },
  test: { include: ['tests/**/*.test.ts'] },
})
